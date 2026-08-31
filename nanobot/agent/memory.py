"""Memory storage, transcript archiving, and legacy consolidation coordination."""

# Tool schemas are installed by the ``@tool_parameters`` class decorator at
# runtime; static analyzers cannot observe that it clears ``parameters`` from
# ``__abstractmethods__`` before these classes are instantiated.
# pyright: reportAbstractUsage=false, reportPrivateUsage=false

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import weakref
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator, cast

from loguru import logger

from nanobot.llm_usage.context import llm_usage_source
from nanobot.runtime_context import public_history_messages
from nanobot.session.manager import (
    MIN_COMPACTED_REPLAY_MESSAGES,
    Session,
    SessionManager,
)
from nanobot.session.summary import session_summary_from_metadata
from nanobot.utils.gitstore import GitStore
from nanobot.utils.helpers import (
    content_with_media_breadcrumbs,
    ensure_dir,
    estimate_prompt_tokens_chain,
    strip_think,
    truncate_text,
    truncate_text_to_tokens,
)
from nanobot.utils.prompt_templates import render_template
from nanobot.utils.workspace_prompts import (
    WORKSPACE_PROMPT_MAX_CHARS,
    has_workspace_prompt_override,
    load_workspace_prompt_override,
    workspace_prompt_file,
)

if TYPE_CHECKING:
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.utils.llm_runtime import LLMRuntime

# ---------------------------------------------------------------------------
# MemoryStore — pure file I/O layer
# ---------------------------------------------------------------------------


class MemoryStore:
    """Pure file I/O for memory files: MEMORY.md, history.jsonl, SOUL.md, USER.md."""

    _DEFAULT_MAX_HISTORY = 1000
    # Durable files whose real working-tree delta grounds Dream commit messages.
    # Deliberately excludes memory/.dream_cursor so progress bookkeeping never
    # appears as a durable-memory edit in the audit record.
    _DREAM_CONTENT_PATHS = ("SOUL.md", "USER.md", "memory/MEMORY.md")
    # Per-file cap when embedding current contents into the Dream prompt. The
    # durable files are tiny in practice (~5 KB total), but a runaway file must
    # not unbounded the prompt.
    _DREAM_FILE_EMBED_CAP = 8000
    _LEGACY_ENTRY_START_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}[^\]]*)\]\s*")
    _LEGACY_TIMESTAMP_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s*")
    _LEGACY_RAW_MESSAGE_RE = re.compile(
        r"^\[\d{4}-\d{2}-\d{2}[^\]]*\]\s+[A-Z][A-Z0-9_]*(?:\s+\[tools:\s*[^\]]+\])?:"
    )

    def __init__(self, workspace: Path, max_history_entries: int = _DEFAULT_MAX_HISTORY):
        self.workspace = workspace
        self.max_history_entries = max_history_entries
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "history.jsonl"
        self.legacy_history_file = self.memory_dir / "HISTORY.md"
        self.soul_file = workspace / "SOUL.md"
        self.user_file = workspace / "USER.md"
        self._cursor_file = self.memory_dir / ".cursor"
        self._dream_cursor_file = self.memory_dir / ".dream_cursor"
        self._corruption_logged = False  # rate-limit invalid cursor warning
        self._malformed_entry_logged = False  # rate-limit bad history shape warning
        self._oversize_logged = False  # rate-limit oversized-entry warning
        self._dream_prompt_oversize_logged = False
        self._append_lock = threading.Lock()  # serialize cursor allocation + append
        self._git = GitStore(workspace, tracked_files=[
            "SOUL.md", "USER.md", "memory/MEMORY.md", "memory/.dream_cursor",
        ])
        self._maybe_migrate_legacy_history()

    @property
    def git(self) -> GitStore:
        return self._git

    # -- generic helpers -----------------------------------------------------

    @staticmethod
    def read_file(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def _maybe_migrate_legacy_history(self) -> None:
        """One-time upgrade from legacy HISTORY.md to history.jsonl.

        The migration is best-effort and prioritizes preserving as much content
        as possible over perfect parsing.
        """
        if not self.legacy_history_file.exists():
            return
        if self.history_file.exists() and self.history_file.stat().st_size > 0:
            return

        try:
            legacy_text = self.legacy_history_file.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            logger.exception("Failed to read legacy HISTORY.md for migration")
            return

        entries = self._parse_legacy_history(legacy_text)
        try:
            if entries:
                self._write_entries(entries)
                last_cursor = entries[-1]["cursor"]
                self._cursor_file.write_text(str(last_cursor), encoding="utf-8")
                # Default to "already processed" so upgrades do not replay the
                # user's entire historical archive into Dream on first start.
                self._dream_cursor_file.write_text(str(last_cursor), encoding="utf-8")

            backup_path = self._next_legacy_backup_path()
            self.legacy_history_file.replace(backup_path)
            logger.info(
                "Migrated legacy HISTORY.md to history.jsonl ({} entries)",
                len(entries),
            )
        except Exception:
            logger.exception("Failed to migrate legacy HISTORY.md")

    def _parse_legacy_history(self, text: str) -> list[dict[str, Any]]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return []

        fallback_timestamp = self._legacy_fallback_timestamp()
        entries: list[dict[str, Any]] = []
        chunks = self._split_legacy_history_chunks(normalized)

        for cursor, chunk in enumerate(chunks, start=1):
            timestamp = fallback_timestamp
            content = chunk
            match = self._LEGACY_TIMESTAMP_RE.match(chunk)
            if match:
                timestamp = match.group(1)
                remainder = chunk[match.end():].lstrip()
                if remainder:
                    content = remainder

            entries.append({
                "cursor": cursor,
                "timestamp": timestamp,
                "content": content,
            })
        return entries

    def _split_legacy_history_chunks(self, text: str) -> list[str]:
        lines = text.split("\n")
        chunks: list[str] = []
        current: list[str] = []
        saw_blank_separator = False

        for line in lines:
            if saw_blank_separator and line.strip() and current:
                chunks.append("\n".join(current).strip())
                current = [line]
                saw_blank_separator = False
                continue
            if self._should_start_new_legacy_chunk(line, current):
                chunks.append("\n".join(current).strip())
                current = [line]
                saw_blank_separator = False
                continue
            current.append(line)
            saw_blank_separator = not line.strip()

        if current:
            chunks.append("\n".join(current).strip())
        return [chunk for chunk in chunks if chunk]

    def _should_start_new_legacy_chunk(self, line: str, current: list[str]) -> bool:
        if not current:
            return False
        if not self._LEGACY_ENTRY_START_RE.match(line):
            return False
        if self._is_raw_legacy_chunk(current) and self._LEGACY_RAW_MESSAGE_RE.match(line):
            return False
        return True

    def _is_raw_legacy_chunk(self, lines: list[str]) -> bool:
        first_nonempty = next((line for line in lines if line.strip()), "")
        match = self._LEGACY_TIMESTAMP_RE.match(first_nonempty)
        if not match:
            return False
        return first_nonempty[match.end():].lstrip().startswith("[RAW]")

    def _legacy_fallback_timestamp(self) -> str:
        try:
            return datetime.fromtimestamp(
                self.legacy_history_file.stat().st_mtime,
            ).strftime("%Y-%m-%d %H:%M")
        except OSError:
            return datetime.now().strftime("%Y-%m-%d %H:%M")

    def _next_legacy_backup_path(self) -> Path:
        candidate = self.memory_dir / "HISTORY.md.bak"
        suffix = 2
        while candidate.exists():
            candidate = self.memory_dir / f"HISTORY.md.bak.{suffix}"
            suffix += 1
        return candidate

    # -- MEMORY.md (long-term facts) -----------------------------------------

    def read_memory(self) -> str:
        return self.read_file(self.memory_file)

    def write_memory(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    # -- SOUL.md -------------------------------------------------------------

    def read_soul(self) -> str:
        return self.read_file(self.soul_file)

    def write_soul(self, content: str) -> None:
        self.soul_file.write_text(content, encoding="utf-8")

    # -- USER.md -------------------------------------------------------------

    def read_user(self) -> str:
        return self.read_file(self.user_file)

    def write_user(self, content: str) -> None:
        self.user_file.write_text(content, encoding="utf-8")

    # -- context injection (used by context.py) ------------------------------

    def get_memory_context(self) -> str:
        long_term = self.read_memory()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    # -- history.jsonl — append-only, JSONL format ---------------------------

    def _normalize_history_entry(
        self,
        entry: str,
        *,
        max_chars: int | None = None,
    ) -> str:
        """Return the exact bounded, model-safe text accepted by the journal."""
        limit = max_chars if max_chars is not None else _HISTORY_ENTRY_HARD_CAP
        raw = entry.rstrip()
        content = strip_think(raw)
        if len(content) > limit:
            if not self._oversize_logged:
                self._oversize_logged = True
                logger.warning(
                    "history entry exceeds {} chars ({}); truncating. "
                    "Usually means a caller forgot its own cap; "
                    "further occurrences suppressed.",
                    limit,
                    len(content),
                )
            content = truncate_text(content, limit)
        return content

    def append_history(
        self,
        entry: str,
        *,
        max_chars: int | None = None,
        session_key: str | None = None,
    ) -> int:
        """Append *entry* to history.jsonl and return its auto-incrementing cursor.

        Entries are passed through `strip_think` to drop template-level leaks
        (e.g. unclosed `<think` prefixes, `<channel|>` markers) before being
        persisted. If the cleaned content is empty but the raw entry wasn't,
        the record is persisted with an empty string rather than falling back
        to the raw leak — otherwise `strip_think`'s guarantees would be
        undone when Dream consumes the journal entry.

        A defensive cap (*max_chars*, default ``_HISTORY_ENTRY_HARD_CAP``) is
        applied as a final safety net: individual callers should cap their own
        content more tightly; this default only exists to catch unintentional
        large writes (e.g. an LLM echoing its input back as a "summary").
        """
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        raw = entry.rstrip()
        content = self._normalize_history_entry(entry, max_chars=max_chars)
        # Cursor allocation and the append must be atomic: concurrent writers
        # could otherwise read the same current cursor and emit duplicates.
        with self._append_lock:
            cursor = self._next_cursor()
            if raw and not content:
                logger.debug(
                    "history entry {} stripped to empty (likely template leak); "
                    "persisting empty content to avoid re-polluting Dream input",
                    cursor,
                )
            record = {"cursor": cursor, "timestamp": ts, "content": content}
            if session_key:
                record["session_key"] = session_key
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._cursor_file.write_text(str(cursor), encoding="utf-8")
        return cursor

    @staticmethod
    def _valid_cursor(value: Any) -> int | None:
        """Non-negative int cursors only; reject bool (``isinstance(True, int)`` is True)."""
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def _iter_valid_entries(self) -> Iterator[tuple[dict[str, Any], int]]:
        """Yield ``(entry, cursor)`` for well-formed entries; warn once on corruption."""
        poisoned: Any = None
        malformed_cursor: int | None = None
        for entry in self._read_entries():
            raw = entry.get("cursor")
            if raw is None:
                continue
            cursor = self._valid_cursor(raw)
            if cursor is None:
                poisoned = raw
                continue
            if not self._valid_history_payload(entry):
                malformed_cursor = cursor
                continue
            yield entry, cursor
        if poisoned is not None and not self._corruption_logged:
            self._corruption_logged = True
            logger.warning(
                "history.jsonl contains an invalid cursor ({!r}); dropping it. "
                "Usually caused by an external writer; further occurrences suppressed.",
                poisoned,
            )
        if malformed_cursor is not None and not self._malformed_entry_logged:
            self._malformed_entry_logged = True
            logger.warning(
                "history.jsonl contains a malformed entry at cursor {}; dropping it. "
                "Usually caused by an external writer; further occurrences suppressed.",
                malformed_cursor,
            )

    @staticmethod
    def _valid_history_payload(entry: dict[str, Any]) -> bool:
        if not isinstance(entry.get("timestamp"), str):
            return False
        if not isinstance(entry.get("content"), str):
            return False
        session_key = entry.get("session_key")
        return session_key is None or isinstance(session_key, str)

    def _read_cursor_counter(self) -> int | None:
        """Return the persisted cursor counter when it is usable."""
        if not self._cursor_file.exists():
            return None
        with suppress(ValueError, OSError):
            cursor = int(self._cursor_file.read_text(encoding="utf-8").strip())
            if cursor >= 0:
                return cursor
        return None

    def _next_cursor(self) -> int:
        """Read the current cursor counter and return the next value."""
        cursor_counter = self._read_cursor_counter()
        last = self._read_last_entry() or {}
        last_cursor = self._valid_cursor(last.get("cursor"))
        if cursor_counter is not None:
            if last_cursor is not None:
                return max(cursor_counter, last_cursor) + 1
            max_history_cursor = max((c for _, c in self._iter_valid_entries()), default=0)
            return max(cursor_counter, max_history_cursor) + 1

        # Fast path: trust the tail when intact.  Otherwise scan the whole
        # file and take ``max`` — that stays correct even if the monotonic
        # invariant was broken by external writes.
        if last_cursor is not None:
            return last_cursor + 1
        return max((c for _, c in self._iter_valid_entries()), default=0) + 1

    def read_unprocessed_history(self, since_cursor: int) -> list[dict[str, Any]]:
        """Return history entries with a valid cursor > *since_cursor*."""
        return [e for e, c in self._iter_valid_entries() if c > since_cursor]

    def compact_history(self) -> None:
        """Drop oldest processed entries without discarding pending Dream input."""
        if self.max_history_entries <= 0:
            return
        entries = self._read_entries()
        if len(entries) <= self.max_history_entries:
            return
        last_dream_cursor = self.get_last_dream_cursor()
        first_unprocessed = next(
            (
                index
                for index, entry in enumerate(entries)
                if (
                    (cursor := self._valid_cursor(entry.get("cursor"))) is not None
                    and cursor > last_dream_cursor
                )
            ),
            len(entries),
        )
        keep_from = min(len(entries) - self.max_history_entries, first_unprocessed)
        kept = entries[keep_from:]
        if len(kept) > self.max_history_entries:
            logger.warning(
                "History compaction retained {} unprocessed entries beyond the configured "
                "limit of {}",
                len(kept),
                self.max_history_entries,
            )
        self._write_entries(kept)

    # -- JSONL helpers -------------------------------------------------------

    def _read_entries(self) -> list[dict[str, Any]]:
        """Read all entries from history.jsonl."""
        entries: list[dict[str, Any]] = []
        with suppress(FileNotFoundError):
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            parsed: object = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(parsed, dict):
                            entries.append(cast(dict[str, Any], parsed))

        return entries

    def _read_last_entry(self) -> dict[str, Any] | None:
        """Read the last entry from the JSONL file efficiently."""
        try:
            with open(self.history_file, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                if size == 0:
                    return None
                read_size = min(size, 4096)
                f.seek(size - read_size)
                data = f.read().decode("utf-8")
                lines = [line for line in data.split("\n") if line.strip()]
                if not lines:
                    return None
                parsed: object = json.loads(lines[-1])
                return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else None
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _write_entries(self, entries: list[dict[str, Any]]) -> None:
        """Overwrite history.jsonl with the given entries (atomic write)."""
        tmp_path = self.history_file.with_suffix(self.history_file.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.history_file)

            # fsync the directory so the rename is durable.
            # On Windows, opening a directory with O_RDONLY raises
            # PermissionError — skip the dir sync there (NTFS
            # journals metadata synchronously).
            with suppress(PermissionError):
                fd = os.open(str(self.history_file.parent), os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    # -- dream cursor --------------------------------------------------------

    def get_last_dream_cursor(self) -> int:
        if self._dream_cursor_file.exists():
            with suppress(ValueError, OSError):
                return int(self._dream_cursor_file.read_text(encoding="utf-8").strip())
        return 0

    def set_last_dream_cursor(self, cursor: int) -> None:
        self._dream_cursor_file.write_text(str(cursor), encoding="utf-8")

    def get_latest_cursor(self) -> int:
        return max(self._next_cursor() - 1, 0)

    @property
    def dream_prompt_file(self) -> Path:
        return workspace_prompt_file(self.workspace, "dream")

    def has_dream_prompt_override(self) -> bool:
        return has_workspace_prompt_override(self.dream_prompt_file)

    @staticmethod
    def default_dream_prompt() -> str:
        from nanobot.agent.skills import BUILTIN_SKILLS_DIR

        return render_template(
            "agent/dream.md",
            strip=True,
            skill_creator_path=str(BUILTIN_SKILLS_DIR / "skill-creator" / "SKILL.md"),
        )

    def _dream_template(self) -> str:
        text, original_chars = load_workspace_prompt_override(self.dream_prompt_file)
        if text is not None:
            if (
                original_chars > WORKSPACE_PROMPT_MAX_CHARS
                and not self._dream_prompt_oversize_logged
            ):
                self._dream_prompt_oversize_logged = True
                logger.warning(
                    "workspace Dream prompt exceeds {} chars ({}); truncating. "
                    "Further occurrences suppressed.",
                    WORKSPACE_PROMPT_MAX_CHARS, original_chars,
                )
            return text
        return self.default_dream_prompt()

    def build_dream_prompt(self, *, max_entries: int = 20) -> tuple[str, int] | None:
        """Build the Dream prompt with unprocessed history context.

        Returns ``(prompt, last_cursor)`` or ``None`` if nothing to process.

        The current contents of the durable memory files (SOUL.md, USER.md,
        memory/MEMORY.md) are embedded so the model edits the real files rather
        than a stale mental model — eliminating a class of failed/out-of-bounds
        edits that previously produced hallucinated audit records.
        """
        last_cursor = self.get_last_dream_cursor()
        entries = self.read_unprocessed_history(since_cursor=last_cursor)
        if not entries:
            return None

        batch = entries[:max_entries]
        history_text = "\n".join(
            f"[{e['timestamp']}] {truncate_text(e['content'], 1000)}"
            for e in batch
        )
        template = self._dream_template()
        files_section = self._render_current_memory_files()
        prompt = (
            f"{template}\n\n{files_section}\n\n"
            f"## Conversation History\n{history_text}"
        )
        return (prompt, batch[-1]["cursor"])

    def _render_current_memory_files(self) -> str:
        """Render the durable memory files' current contents for the Dream prompt.

        Missing files render as ``(empty)``; oversized files are capped. The
        section is the ground truth the model must edit against.
        """
        files = [
            ("SOUL.md", self.soul_file),
            ("USER.md", self.user_file),
            ("memory/MEMORY.md", self.memory_file),
        ]
        blocks: list[str] = []
        for label, path in files:
            try:
                content = path.read_text(encoding="utf-8") if path.exists() else ""
            except OSError:
                content = ""
            if len(content) > self._DREAM_FILE_EMBED_CAP:
                content = truncate_text(content, self._DREAM_FILE_EMBED_CAP) + "\n...[truncated]"
            blocks.append(f"### {label}\n{content}" if content.strip() else f"### {label}\n(empty)")
        return "## Current Memory Files\n" + "\n\n".join(blocks)

    def dream_content_diff(self) -> str:
        """Structured summary of uncommitted changes to the durable memory files.

        Returns "" when git is unavailable or no content file changed. This is
        the ground-truth input for diff-grounded Dream commit messages.
        """
        if not self._git.is_initialized():
            return ""
        return self._git.summarize_working_tree(list(self._DREAM_CONTENT_PATHS))

    def build_dream_tools(self) -> ToolRegistry:
        """Build the restricted tool registry used by Dream runs."""
        from nanobot.agent.skills import BUILTIN_SKILLS_DIR
        from nanobot.agent.tools.apply_patch import ApplyPatchTool
        from nanobot.agent.tools.file_state import FileStates
        from nanobot.agent.tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool
        from nanobot.agent.tools.registry import ToolRegistry

        tools = ToolRegistry()
        file_states = FileStates()
        workspace = self.workspace
        skills_dir = workspace / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)

        extra_read = [BUILTIN_SKILLS_DIR] if BUILTIN_SKILLS_DIR.exists() else None
        editable_files = [self.memory_file, self.soul_file, self.user_file]

        tools.register(ReadFileTool(
            workspace=workspace,
            allowed_dir=workspace,
            extra_read_allowed_dirs=extra_read,
            file_states=file_states,
        ))
        tools.register(EditFileTool(
            workspace=workspace,
            allowed_dir=skills_dir,
            extra_write_allowed_files=editable_files,
            file_states=file_states,
        ))
        tools.register(ApplyPatchTool(
            workspace=workspace,
            allowed_dir=skills_dir,
            extra_write_allowed_files=editable_files,
            file_states=file_states,
        ))
        tools.register(WriteFileTool(
            workspace=workspace,
            allowed_dir=skills_dir,
            extra_write_allowed_files=editable_files,
            file_states=file_states,
        ))
        return tools

    @staticmethod
    def dream_run_completed(
        resp: object | None,
    ) -> bool:
        """Return True when the Dream agent reached a normal terminal response."""
        metadata = getattr(resp, "metadata", None)
        if not isinstance(metadata, dict):
            return False
        return cast(dict[str, Any], metadata).get("_stop_reason") == "completed"

    @staticmethod
    def dream_incompletion_reason(
        resp: object | None,
    ) -> str:
        """Human-readable explanation of why a Dream run cannot advance."""
        metadata = getattr(resp, "metadata", None)
        if isinstance(metadata, dict):
            stop_reason = cast(dict[str, Any], metadata).get("_stop_reason", "unknown")
        else:
            stop_reason = "missing response metadata"
        return f"stop_reason: {stop_reason}"

    # -- message formatting utility ------------------------------------------

    @staticmethod
    def _format_messages(messages: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for message in messages:
            content = content_with_media_breadcrumbs(
                message.get("role"),
                message.get("content", ""),
                message.get("media"),
            )
            if not content:
                continue
            tools_used = message.get("tools_used")
            tools = (
                f" [tools: {', '.join(cast(list[str], tools_used))}]"
                if tools_used
                else ""
            )
            raw_timestamp = message.get("timestamp")
            timestamp = str(raw_timestamp) if raw_timestamp is not None else "?"
            role = str(message.get("role") or "unknown")
            lines.append(f"[{timestamp[:16]}] {role.upper()}{tools}: {content}")
        return "\n".join(lines)

    def raw_archive(
        self,
        messages: list[dict[str, Any]],
        *,
        max_chars: int | None = None,
        session_key: str | None = None,
    ) -> str:
        """Persist and return a bounded raw checkpoint when summarization degrades."""
        checkpoint = self._build_raw_checkpoint(messages, max_chars=max_chars)
        self.append_history(checkpoint, session_key=session_key)
        logger.warning(
            "Memory consolidation degraded: raw-archived {} messages", len(messages)
        )
        return checkpoint

    def _build_raw_checkpoint(
        self,
        messages: list[dict[str, Any]],
        *,
        max_chars: int | None = None,
    ) -> str:
        """Build the same bounded checkpoint as :meth:`raw_archive` without writing it."""
        limit = max_chars if max_chars is not None else _RAW_ARCHIVE_MAX_CHARS
        checkpoint = (
            f"[RAW] {len(messages)} messages\n"
            f"{self._format_messages(public_history_messages(messages))}"
        )
        return self._normalize_history_entry(checkpoint, max_chars=limit)

    # ------------------------------------------------------------------
    # Dream helpers
    # ------------------------------------------------------------------

    @staticmethod
    def dream_session_key() -> str:
        """Return a unique session key for a Dream run, e.g. ``dream:20260528-100000``."""
        return f"dream:{datetime.now():%Y%m%d-%H%M%S}"

    @staticmethod
    def build_dream_commit_message(prefix: str, diff_body: str) -> str:
        """Build a Dream commit message grounded in the real working-tree diff.

        *diff_body* is a structured, machine-derived summary of the actual file
        changes (see :meth:`dream_content_diff` /
        :meth:`GitStore.summarize_working_tree`). The LLM narrative is
        deliberately excluded so the audit record (``/dream-log``) reflects the
        filesystem's truth, not the model's self-report.

        An empty *diff_body* yields the bare *prefix*, which ``auto_commit``
        turns into a no-op when there is nothing to stage.
        """
        diff_body = (diff_body or "").strip()
        if not diff_body:
            return prefix
        return f"{prefix}\n\n{diff_body}"

    @staticmethod
    def prune_dream_sessions(sessions: SessionManager, *, keep: int = 10) -> None:
        """Remove the oldest Dream session files, keeping only the N most recent.

        Only current base64url-encoded Dream session keys are considered.
        Non-dream session files are never touched.
        """
        with sessions.locked_session_files() as sessions_dir:
            dream_files: list[tuple[Path, str]] = []
            for path in sessions_dir.glob("*.jsonl"):
                decoded_key = SessionManager.decode_storage_key(path.stem)
                if decoded_key is not None and decoded_key.startswith("dream:"):
                    dream_files.append((path, decoded_key))
            dream_files.sort(key=lambda item: item[0].stat().st_mtime)

            for path, key in dream_files[: max(0, len(dream_files) - keep)]:
                if sessions.delete_session(key):
                    logger.debug("Pruned old dream session: {}", path.stem)
                else:
                    logger.warning("Failed to prune dream session {}", path)


# ---------------------------------------------------------------------------
# Memory ingestion and legacy context-pressure coordination
# ---------------------------------------------------------------------------

# Raw fallbacks use a tighter cap. Completed model summaries may scale with the
# configured generation budget, while append_history() still enforces the
# emergency hard cap against pathological provider output.
_RAW_ARCHIVE_MAX_CHARS = 16_000   # fallback dump (LLM failed)
_HISTORY_ENTRY_HARD_CAP = 64_000  # emergency cap in append_history


class MemoryArchiver:
    """Write durable transcript batches to the Memory ingestion journal.

    The archiver deliberately has no SessionManager dependency: it may read a
    captured transcript batch and append to history.jsonl, but it cannot mutate
    provider continuation state or advance a session watermark.
    """

    def __init__(
        self,
        store: MemoryStore,
        build_messages: Callable[..., list[dict[str, Any]]],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
        resolve_prompt_context: Callable[[Session], tuple[str | None, Path | None]] | None = None,
    ) -> None:
        self.store = store
        self._build_messages = build_messages
        self._get_tool_definitions = get_tool_definitions
        self._resolve_prompt_context = resolve_prompt_context

    def _raw_checkpoint(
        self,
        messages: list[dict[str, Any]],
        *,
        session_key: str,
        previous_summary: str | None,
        max_tokens: int,
    ) -> str:
        """Persist the failed chunk and return a bounded replacement checkpoint."""
        raw = self.store.raw_archive(messages, session_key=session_key)
        token_limit = max(1, max_tokens)
        if not previous_summary:
            return truncate_text_to_tokens(raw, token_limit)

        combined = (
            "[Previous archived context]\n"
            f"{previous_summary}\n\n"
            "[Newly archived raw context]\n"
            f"{raw}"
        )
        bounded = truncate_text_to_tokens(combined, token_limit)
        if bounded == combined:
            return combined

        # Keep evidence from both sides when their full concatenation cannot fit.
        section_limit = max(1, (token_limit - 32) // 2)
        return truncate_text_to_tokens(
            "[Previous archived context]\n"
            f"{truncate_text_to_tokens(previous_summary, section_limit)}\n\n"
            "[Newly archived raw context]\n"
            f"{truncate_text_to_tokens(raw, section_limit)}",
            token_limit,
        )

    async def archive(
        self,
        messages: list[dict[str, Any]],
        *,
        runtime: LLMRuntime,
        session_key: str,
        request_messages: list[dict[str, Any]],
        request_tools: list[dict[str, Any]],
        previous_summary: str | None = None,
    ) -> str | None:
        """Execute a prepared archive request and persist its result."""
        if not messages:
            return None

        def raw_fallback() -> str:
            return self._raw_checkpoint(
                messages,
                session_key=session_key,
                previous_summary=previous_summary,
                max_tokens=runtime.generation.max_tokens,
            )

        try:
            with llm_usage_source("dream"):
                response = await runtime.provider.chat_with_retry(
                    model=runtime.model,
                    messages=request_messages,
                    tools=request_tools,
                    temperature=runtime.generation.temperature,
                    max_tokens=runtime.generation.max_tokens,
                    reasoning_effort=runtime.generation.reasoning_effort,
                )
        except Exception:
            logger.warning("Memory archive provider call failed, raw-dumping to history")
            return raw_fallback()
        if response.finish_reason in {"error", "length"}:
            logger.warning(
                "Memory archive provider did not complete ({}), raw-dumping to history",
                response.finish_reason,
            )
            return raw_fallback()
        if response.has_tool_calls is True:
            logger.warning("Memory archive provider returned tool calls, raw-dumping to history")
            return raw_fallback()
        summary = response.content
        if not summary or not summary.strip():
            logger.warning("Memory archive provider returned no summary, raw-dumping to history")
            return raw_fallback()
        summary = self.store._normalize_history_entry(summary)
        if not summary:
            logger.warning("Memory archive provider summary was not safe to replay, raw-dumping")
            return raw_fallback()
        if summary == "(nothing)":
            return "(nothing)"
        self.store.append_history(summary, session_key=session_key)
        return summary

    async def archive_session(
        self,
        session: Session,
        *,
        archive_end: int,
        runtime: LLMRuntime,
        input_token_budget: int,
    ) -> str | None:
        """Archive a captured session prefix without mutating the session."""
        messages = list(session.messages[session.last_archived:archive_end])
        if not messages:
            return None
        session_summary = session_summary_from_metadata(
            session.metadata,
            fallback_last_active=session.updated_at,
        )
        previous_summary = session_summary["text"] if session_summary else None

        def raw_fallback() -> str:
            return self._raw_checkpoint(
                messages,
                session_key=session.key,
                previous_summary=previous_summary,
                max_tokens=runtime.generation.max_tokens,
            )

        if input_token_budget <= 0:
            logger.debug(
                "Memory archive has no safe input budget for {}; raw-dumping",
                session.key,
            )
            return raw_fallback()
        prefix = Session(
            key=session.key,
            messages=list(session.messages[:archive_end]),
            last_consolidated=session.last_archived,
        )
        history = prefix.get_history(max_tokens=input_token_budget)
        archive_history = Session(
            key=session.key,
            messages=messages,
        ).get_history()
        if not archive_history or history[-len(archive_history):] != archive_history:
            logger.debug(
                "Memory archive cannot replay the full chunk for {}; raw-dumping",
                session.key,
            )
            return raw_fallback()
        prompt = render_template("agent/consolidator_archive.md", strip=True)
        channel = session.key.split(":", 1)[0] if ":" in session.key else None
        workspace: Path | None = None
        if self._resolve_prompt_context is not None:
            channel, workspace = self._resolve_prompt_context(session)
        request_messages = self._build_messages(
            history=history,
            current_message=prompt,
            channel=channel,
            session_summary=session_summary,
            workspace=workspace,
        )
        tools = self._get_tool_definitions()
        estimated, source = estimate_prompt_tokens_chain(
            runtime.provider,
            runtime.model,
            request_messages,
            tools,
        )
        if estimated > input_token_budget:
            logger.debug(
                "Memory archive prefix exceeds budget for {}; raw-dumping: {}/{} via {}",
                session.key,
                estimated,
                input_token_budget,
                source,
            )
            return raw_fallback()
        return await self.archive(
            messages,
            runtime=runtime,
            session_key=session.key,
            request_messages=request_messages,
            request_tools=tools,
            previous_summary=previous_summary,
        )


class Consolidator:
    """Legacy context-pressure coordinator backed by a MemoryArchiver."""

    _SAFETY_BUFFER = 1024  # extra headroom for tokenizer estimation drift

    def __init__(
        self,
        store: MemoryStore,
        sessions: SessionManager,
        build_messages: Callable[..., list[dict[str, Any]]],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
        resolve_prompt_context: Callable[[Session], tuple[str | None, Path | None]] | None = None,
    ):
        self.store = store
        self.sessions = sessions
        self._build_messages = build_messages
        self._get_tool_definitions = get_tool_definitions
        self.archiver = MemoryArchiver(
            store=store,
            build_messages=build_messages,
            get_tool_definitions=get_tool_definitions,
            resolve_prompt_context=resolve_prompt_context,
        )
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    def get_lock(self, session_key: str) -> asyncio.Lock:
        """Return the shared consolidation lock for one session."""
        return self._locks.setdefault(session_key, asyncio.Lock())

    def pick_consolidation_boundary(
        self,
        session: Session,
    ) -> int | None:
        """Return the fixed user-led boundary before the recent replay tail."""
        if not session.messages:
            return None
        boundary = max(0, len(session.messages) - MIN_COMPACTED_REPLAY_MESSAGES)
        while boundary > 0 and session.messages[boundary].get("role") != "user":
            boundary -= 1
        if (
            boundary <= session.last_archived
            or session.messages[boundary].get("role") != "user"
        ):
            return None
        return boundary

    @staticmethod
    def _full_replay_history(
        session: Session,
    ) -> list[dict[str, Any]]:
        """Return all messages that can reach the next model prompt."""
        if not session.messages:
            return []
        return session.get_history()

    @staticmethod
    def _set_last_summary(
        session: Session,
        summary: str,
        *,
        last_active: datetime | None = None,
    ) -> None:
        if summary != "(nothing)":
            session.metadata["_last_summary"] = {
                "text": summary,
                "last_active": (last_active or session.updated_at).isoformat(),
            }

    def estimate_session_prompt_tokens(
        self,
        session: Session,
        *,
        runtime: LLMRuntime,
    ) -> tuple[int, str]:
        """Estimate prompt size from the full replayable session history."""
        history = self._full_replay_history(session)
        channel = session.key.split(":", 1)[0] if ":" in session.key else None
        summary = session_summary_from_metadata(
            session.metadata,
            fallback_last_active=session.updated_at,
        )
        probe_messages = self._build_messages(
            history=history,
            current_message="[token-probe]",
            channel=channel,
            session_summary=summary,
        )
        return estimate_prompt_tokens_chain(
            runtime.provider,
            runtime.model,
            probe_messages,
            self._get_tool_definitions(),
        )

    def _input_token_budget(self, runtime: LLMRuntime) -> int:
        """Available input token budget for consolidation LLM."""
        return (
            runtime.context_window_tokens
            - runtime.generation.max_tokens
            - self._SAFETY_BUFFER
        )

    async def archive_session(
        self,
        session: Session,
        *,
        archive_end: int,
        runtime: LLMRuntime,
    ) -> str | None:
        """Compatibility wrapper for the extracted MemoryArchiver."""
        return await self.archiver.archive_session(
            session,
            archive_end=archive_end,
            runtime=runtime,
            input_token_budget=self._input_token_budget(runtime),
        )

    async def maybe_consolidate_by_tokens(
        self,
        session: Session,
        *,
        runtime: LLMRuntime,
    ) -> None:
        """Archive one fixed old prefix when the prompt exceeds the safe budget.

        The budget reserves space for completion tokens and a safety buffer
        so the LLM request never exceeds the context window.
        """
        lock = self.get_lock(session.key)
        async with lock:
            # Refresh session reference: AutoCompact may have replaced it.
            fresh = self.sessions.get_or_create(session.key)
            if fresh is not session:
                session = fresh
            if runtime.context_window_tokens <= 0:
                return
            if not session.messages:
                return

            budget = self._input_token_budget(runtime)
            estimated, source = self.estimate_session_prompt_tokens(
                session,
                runtime=runtime,
            )
            if estimated <= 0:
                return
            if estimated < budget:
                unarchived_count = len(session.messages) - session.last_archived
                logger.debug(
                    "Token consolidation idle {}: {}/{} via {}, msgs={}",
                    session.key,
                    estimated,
                    runtime.context_window_tokens,
                    source,
                    unarchived_count,
                )
                return

            end_idx = self.pick_consolidation_boundary(session)
            if end_idx is None:
                logger.debug(
                    "Token consolidation: no safe fixed boundary for {}",
                    session.key,
                )
                return

            chunk = session.messages[session.last_archived:end_idx]
            if not chunk:
                return

            logger.info(
                "Token consolidation for {}: {}/{} via {}, chunk={} msgs",
                session.key,
                estimated,
                runtime.context_window_tokens,
                source,
                len(chunk),
            )
            summary = await self.archive_session(
                session,
                archive_end=end_idx,
                runtime=runtime,
            )
            if summary is None:
                return
            self._set_last_summary(session, summary)
            session.last_archived = end_idx
            self.sessions.save(session)

    async def compact_idle_session(
        self,
        session_key: str,
        *,
        runtime: LLMRuntime,
        max_suffix: int = MIN_COMPACTED_REPLAY_MESSAGES,
    ) -> str | None:
        """Archive the full idle tail while keeping recent messages replayable.

        ``max_suffix`` remains accepted for SDK compatibility. Replay retention
        is now derived independently from archive progress using the project-wide
        compacted-session window.
        """
        if max_suffix != MIN_COMPACTED_REPLAY_MESSAGES:
            logger.debug(
                "Idle-session compact for {} uses the fixed replay window ({}, requested {})",
                session_key,
                MIN_COMPACTED_REPLAY_MESSAGES,
                max_suffix,
            )
        lock = self.get_lock(session_key)
        async with lock:
            self.sessions.invalidate(session_key)
            session = self.sessions.get_or_create(session_key)

            archive_start = session.last_archived
            messages_to_archive = list(session.messages[archive_start:])
            if not messages_to_archive:
                return ""

            last_active = session.updated_at
            archive_end = archive_start + len(messages_to_archive)
            summary = await self.archive_session(
                session,
                archive_end=archive_end,
                runtime=runtime,
            )
            if summary is None:
                return None

            self._set_last_summary(session, summary, last_active=last_active)

            # A turn can append while the provider call is in flight. Advance only
            # through the captured batch so new messages remain eligible next time.
            session.last_archived = archive_end
            self.sessions.save(session)

            visible = session.get_history(
                max_messages=MIN_COMPACTED_REPLAY_MESSAGES,
                extend_to_user=True,
            )

            logger.info(
                "Idle-session compact for {}: archived={}, visible={}, retained={}, summary={}",
                session_key,
                len(messages_to_archive),
                len(visible),
                len(session.messages),
                bool(summary),
            )

            return summary
