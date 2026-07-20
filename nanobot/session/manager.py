"""Session management for conversation history."""

import base64
import errno
import json
import os
import re
import shutil
from collections import OrderedDict
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from weakref import WeakValueDictionary

from loguru import logger

from nanobot.config.paths import get_legacy_sessions_dir
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    public_history_message,
)
from nanobot.utils.helpers import (
    ensure_dir,
    estimate_message_tokens,
    find_legal_message_start,
    image_placeholder_text,
    recent_message_start_index,
    safe_filename,
    strip_think,
)
from nanobot.utils.subagent_channel_display import scrub_subagent_announce_body

FILE_MAX_MESSAGES = 2000
SESSION_CACHE_MAX_SIZE = 128
MIN_REPLAY_MAX_MESSAGES = 120
REPLAY_TOKENS_PER_MESSAGE = 100
_MESSAGE_TIME_PREFIX_RE = re.compile(r"^\[Message Time: [^\]]+\]\n?")
_LOCAL_IMAGE_BREADCRUMB_RE = re.compile(r"^\[image: (?:/|~)[^\]]+\]\s*$")
_TOOL_CALL_ECHO_RE = re.compile(r'^\s*(?:generate_image|message)\([^)]*\)\s*$')
_SESSION_PREVIEW_MAX_CHARS = 120
_SESSION_LIST_PREVIEW_MAX_RECORDS = 200
_SESSION_LIST_PREVIEW_MAX_CHARS = 1_000_000
_FORK_VOLATILE_METADATA_KEYS = {
    "goal_state",
    "pending_user_turn",
    "runtime_checkpoint",
    "thread_goal",
    "title",
    "title_user_edited",
}


def replay_max_messages_for_context(context_window_tokens: int | None) -> int:
    if not context_window_tokens or context_window_tokens <= 0:
        return FILE_MAX_MESSAGES
    return min(
        FILE_MAX_MESSAGES,
        max(MIN_REPLAY_MAX_MESSAGES, context_window_tokens // REPLAY_TOKENS_PER_MESSAGE),
    )


def _sanitize_assistant_replay_text(content: str) -> str:
    """Remove internal replay artifacts that the model may have copied before.

    These strings are useful as runtime/session metadata, but when they appear
    in assistant examples they become demonstrations for the model to repeat.
    """
    content = _MESSAGE_TIME_PREFIX_RE.sub("", content, count=1)
    lines = [
        line
        for line in content.splitlines()
        if not _LOCAL_IMAGE_BREADCRUMB_RE.match(line)
        and not _TOOL_CALL_ECHO_RE.match(line)
    ]
    return "\n".join(lines).strip()


def _text_preview(content: Any) -> str:
    """Return compact display text for session lists."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                value = block.get("text")
                if isinstance(value, str):
                    parts.append(value)
        text = " ".join(parts)
    else:
        return ""
    text = _sanitize_assistant_replay_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _SESSION_PREVIEW_MAX_CHARS:
        text = text[: _SESSION_PREVIEW_MAX_CHARS - 1].rstrip() + "…"
    return text


def _message_preview_text(message: dict[str, Any]) -> str:
    """Session list preview text; subagent inject blobs are shortened for display."""
    message = public_history_message(message)
    content: Any = message.get("content")
    if message.get("injected_event") == "subagent_result" and isinstance(content, str):
        content = scrub_subagent_announce_body(content)
    return _text_preview(content)


def _metadata_title(metadata: Any) -> str:
    if not isinstance(metadata, dict):
        return ""
    title = metadata.get("title")
    if not isinstance(title, str):
        return ""
    if metadata.get("title_user_edited") is True:
        return title
    return strip_think(title)


@dataclass
class RetentionResult:
    dropped: list[dict]
    already_consolidated_count: int


@dataclass
class Session:
    """A conversation session."""

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files

    def __post_init__(self) -> None:
        # An out-of-range offset (corrupt metadata) would hide all history; reset it.
        if (
            isinstance(self.last_consolidated, bool)
            or not isinstance(self.last_consolidated, int)
            or not 0 <= self.last_consolidated <= len(self.messages)
        ):
            self.last_consolidated = 0

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(
        self,
        max_messages: int = FILE_MAX_MESSAGES,
        *,
        max_tokens: int = 0,
        extend_to_user: bool = False,
        include_runtime_context: bool = True,
    ) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input.

        History is sliced by message count first (``max_messages``), then by
        token budget from the tail (``max_tokens``) when provided.
        """
        unconsolidated = self.messages[self.last_consolidated:]
        max_messages = max_messages if max_messages > 0 else FILE_MAX_MESSAGES
        start_idx = recent_message_start_index(
            unconsolidated,
            max_messages,
            extend_to_user=extend_to_user,
        )
        sliced = unconsolidated[start_idx:]

        # Avoid starting mid-turn when possible, except for proactive
        # assistant deliveries that the user may be replying to.
        for i, message in enumerate(sliced):
            if message.get("role") == "user":
                start = i
                if i > 0 and sliced[i - 1].get("_channel_delivery"):
                    start = i - 1
                sliced = sliced[start:]
                break

        # Drop orphan tool results at the front.
        start = find_legal_message_start(sliced)
        if start:
            sliced = sliced[start:]

        out: list[dict[str, Any]] = []
        for message in sliced:
            if message.get("_command"):
                continue
            has_persisted_runtime_context = isinstance(
                message.get(RUNTIME_CONTEXT_HISTORY_META),
                dict,
            )
            if not include_runtime_context:
                message = public_history_message(message)
            content = message.get("content", "")
            role = message.get("role")
            if role == "assistant" and isinstance(content, str):
                content = _sanitize_assistant_replay_text(content)
            # Synthesize an ``[image: path]`` breadcrumb from the persisted
            # ``media`` kwarg so LLM replay still sees *something* where the
            # image used to be. Without this, an image-only user turn
            # replays as an empty user message — the assistant's reply then
            # looks like it's responding to nothing.
            media = message.get("media")
            if role == "user" and isinstance(media, list) and media and isinstance(content, str):
                breadcrumbs = "\n".join(
                    image_placeholder_text(p) for p in media if isinstance(p, str) and p
                )
                content = f"{content}\n{breadcrumbs}" if content else breadcrumbs
            cli_apps = message.get("cli_apps")
            if (
                include_runtime_context
                and not has_persisted_runtime_context
                and role == "user"
                and isinstance(cli_apps, list)
                and cli_apps
                and isinstance(content, str)
            ):
                cli_lines: list[str] = []
                for item in cli_apps[:8]:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip().lower()
                    if not name:
                        continue
                    entry = str(item.get("entry_point") or "unknown").strip() or "unknown"
                    cli_lines.append(
                        f"[CLI App Attachment: @{name}; tool=run_cli_app; entry_point={entry}; "
                        f"skill=skills/cli-app-{name}/SKILL.md]"
                    )
                if cli_lines:
                    breadcrumbs = "\n".join(cli_lines)
                    content = f"{content}\n{breadcrumbs}" if content else breadcrumbs
            if role == "assistant" and isinstance(content, str) and not content.strip():
                if not any(key in message for key in ("tool_calls", "reasoning_content", "thinking_blocks")):
                    continue
            entry: dict[str, Any] = {"role": message["role"], "content": content}
            for key in ("tool_calls", "tool_call_id", "name", "reasoning_content", "thinking_blocks"):
                if key in message:
                    entry[key] = message[key]
            out.append(entry)

        if max_tokens > 0 and out:
            kept: list[dict[str, Any]] = []
            used = 0
            for message in reversed(out):
                tokens = estimate_message_tokens(message)
                if kept and used + tokens > max_tokens:
                    break
                kept.append(message)
                used += tokens
            kept.reverse()

            # Keep history aligned to the first visible user turn.
            first_user = next((i for i, m in enumerate(kept) if m.get("role") == "user"), None)
            if first_user is not None:
                kept = kept[first_user:]
            else:
                # Tight token budgets can otherwise leave assistant-only tails.
                # If a user turn exists in the unsliced output, recover the
                # nearest one even if it slightly exceeds the token budget.
                recovered_user = next(
                    (i for i in range(len(out) - 1, -1, -1) if out[i].get("role") == "user"),
                    None,
                )
                if recovered_user is not None:
                    kept = out[recovered_user:]

            # And keep a legal tool-call boundary at the front.
            start = find_legal_message_start(kept)
            if start:
                kept = kept[start:]
            out = kept
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()
        self.metadata.pop("_last_summary", None)

    def retain_recent_legal_suffix(
        self,
        max_messages: int,
        *,
        extend_to_user: bool = False,
    ) -> RetentionResult:
        """Keep a legal recent suffix, optionally extending it back to a user turn.

        Returns a RetentionResult with dropped messages and how many of those
        were in the already-consolidated prefix. This method mutates
        self.messages and self.last_consolidated in place.
        """
        if max_messages <= 0:
            dropped = list(self.messages)
            lc = self.last_consolidated
            self.clear()
            return RetentionResult(
                dropped=dropped,
                already_consolidated_count=min(lc, len(dropped)),
            )
        if len(self.messages) <= max_messages:
            return RetentionResult(
                dropped=[],
                already_consolidated_count=0,
            )

        original = list(self.messages)
        before_lc = self.last_consolidated

        start_idx = max(0, len(self.messages) - max_messages)
        if extend_to_user:
            start_idx = next(
                (i for i in range(start_idx, -1, -1) if self.messages[i].get("role") == "user"),
                start_idx,
            )

        retained = self.messages[start_idx:]

        # Prefer starting at a user turn when one exists within the retained window.
        first_user = next((i for i, m in enumerate(retained) if m.get("role") == "user"), None)
        if first_user is not None:
            retained = retained[first_user:]
        elif not extend_to_user:
            # If the hard-capped tail is assistant/tool-only, anchor to the
            # latest user in the full session and take a capped forward window.
            latest_user = next(
                (i for i in range(len(self.messages) - 1, -1, -1)
                 if self.messages[i].get("role") == "user"),
                None,
            )
            if latest_user is not None:
                retained = self.messages[latest_user: latest_user + max_messages]

        # Mirror get_history(): avoid persisting orphan tool results at the front.
        start = find_legal_message_start(retained)
        if start:
            retained = retained[start:]

        # Hard-cap guarantee unless the caller requested user-turn extension.
        if not extend_to_user and len(retained) > max_messages:
            retained = retained[-max_messages:]
            start = find_legal_message_start(retained)
            if start:
                retained = retained[start:]

        # Compute actually-dropped messages using identity comparison so that
        # even when retained is a non-contiguous slice of original (the else
        # branch above), we never duplicate or lose messages.
        retained_ids = set(id(m) for m in retained)
        dropped = [m for m in original if id(m) not in retained_ids]

        # Count how many dropped messages were in the already-consolidated
        # prefix of the original list.  This cannot be a simple min() because
        # dropped may include messages from *after* the consolidated prefix
        # (e.g. in the else branch).
        already_consolidated = sum(
            1 for i, m in enumerate(original)
            if i < before_lc and id(m) not in retained_ids
        )

        # New last_consolidated = count of retained messages that were inside
        # the old consolidated prefix.
        new_lc = sum(
            1 for i, m in enumerate(original)
            if i < before_lc and id(m) in retained_ids
        )

        self.messages = retained
        self.last_consolidated = new_lc
        self.updated_at = datetime.now()
        return RetentionResult(
            dropped=dropped,
            already_consolidated_count=already_consolidated,
        )

    def enforce_file_cap(
        self,
        on_archive: Any = None,
        limit: int = FILE_MAX_MESSAGES,
    ) -> None:
        """Bound session message growth by archiving and trimming old prefixes."""
        if limit <= 0 or len(self.messages) <= limit:
            return

        result = self.retain_recent_legal_suffix(limit)
        if not result.dropped:
            return

        archive_chunk = result.dropped[result.already_consolidated_count:]
        if archive_chunk and on_archive:
            on_archive(archive_chunk)
        logger.info(
            "Session file cap hit for {}: dropped {}, raw-archived {}, kept {}",
            self.key,
            len(result.dropped),
            len(archive_chunk),
            len(self.messages),
        )


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: OrderedDict[str, Session] = OrderedDict()
        # Preserve identity for sessions held by active callers without retaining idle ones.
        self._overflow_cache: WeakValueDictionary[str, Session] = WeakValueDictionary()
        self._max_cached_sessions = SESSION_CACHE_MAX_SIZE

    def _remember(self, session: Session) -> None:
        """Keep recent sessions strongly cached without duplicating live objects."""
        self._overflow_cache.pop(session.key, None)
        self._cache[session.key] = session
        self._cache.move_to_end(session.key)
        while len(self._cache) > self._max_cached_sessions:
            key, evicted = self._cache.popitem(last=False)
            self._overflow_cache[key] = evicted

    def _cached(self, key: str) -> Session | None:
        session = self._cache.get(key)
        if session is not None:
            self._cache.move_to_end(key)
            return session

        session = self._overflow_cache.get(key)
        if session is not None:
            self._remember(session)
        return session

    @staticmethod
    def safe_key(key: str) -> str:
        """Public helper used by HTTP handlers to map an arbitrary key to a stable filename stem."""
        return safe_filename(key.replace(":", "_"))

    @staticmethod
    def _storage_key(key: str) -> str:
        """Collision-resistant encoding for internal session storage filenames."""
        return base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")

    @staticmethod
    def _decode_storage_key(stem: str) -> str | None:
        """Reverse _storage_key(): decode a base64url (no-padding) stem back to the original key."""
        try:
            # Restore padding stripped by rstrip("=")
            padding = 4 - len(stem) % 4
            if padding != 4:
                stem += "=" * padding
            return base64.urlsafe_b64decode(stem).decode("utf-8")
        except Exception:
            return None

    def _get_session_path(self, key: str) -> Path:
        """Get the collision-resistant workspace path for a session."""
        return self.sessions_dir / f"{self._storage_key(key)}.jsonl"

    def _get_legacy_lossy_path(self, key: str) -> Path:
        """Previous workspace session path using lossy ':' to '_' replacement."""
        return self.sessions_dir / f"{safe_filename(key.replace(':', '_'))}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.nanobot/sessions/)."""
        return self.legacy_sessions_dir / f"{self.safe_key(key)}.jsonl"

    @staticmethod
    def _stored_key_for_path(path: Path) -> str | None:
        """Read the stored session key from a JSONL metadata row, if present."""
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        stored_key = data.get("key")
                        return stored_key if isinstance(stored_key, str) else None
                    return None
        except Exception:
            return None
        return None

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        session = self._cached(key)
        if session is not None:
            return session

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._remember(session)
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)
        if not path.exists():
            fallback_paths = [
                (self._get_legacy_lossy_path(key), "legacy lossy path"),
                (self._get_legacy_session_path(key), "legacy path"),
            ]
            for fallback_path, description in fallback_paths:
                if not fallback_path.exists():
                    continue
                stored_key = self._stored_key_for_path(fallback_path)
                if stored_key and stored_key != key:
                    logger.info(
                        "Skipping migration for {} from {} because it belongs to {}",
                        key,
                        description,
                        stored_key,
                    )
                    continue
                try:
                    shutil.move(str(fallback_path), str(path))
                    logger.info("Migrated session {} from {}", key, description)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)
                break

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            updated_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        updated_at = datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            repaired = self._repair(key)
            if repaired is not None:
                logger.info("Recovered session {} from corrupt file ({} messages)", key, len(repaired.messages))
            return repaired

    def _repair(self, key: str, *, path: Path | None = None) -> Session | None:
        """Attempt to recover a session from a corrupt JSONL file."""
        if path is None:
            path = self._get_session_path(key)
        if not path.exists():
            return None

        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: datetime | None = None
            updated_at: datetime | None = None
            last_consolidated = 0
            skipped = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        skipped += 1
                        continue

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        if data.get("created_at"):
                            with suppress(ValueError, TypeError):
                                created_at = datetime.fromisoformat(data["created_at"])
                        if data.get("updated_at"):
                            with suppress(ValueError, TypeError):
                                updated_at = datetime.fromisoformat(data["updated_at"])
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            if skipped:
                logger.warning("Skipped {} corrupt lines in session {}", skipped, key)

            if not messages and not metadata:
                return None

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Repair failed for session {}: {}", key, e)
            return None

    @staticmethod
    def _session_payload(session: Session) -> dict[str, Any]:
        return {
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
            "messages": session.messages,
        }

    def save(self, session: Session, *, fsync: bool = False) -> None:
        """Save a session to disk atomically.

        When *fsync* is ``True`` the final file and its parent directory are
        explicitly flushed to durable storage.  This is intentionally off by
        default (the OS page-cache is sufficient for normal operation) but
        should be enabled during graceful shutdown so that filesystems with
        write-back caching (e.g. rclone VFS, NFS, FUSE mounts) do not lose
        the most recent writes.
        """
        path = self._get_session_path(session.key)
        tmp_path = path.with_suffix(".jsonl.tmp")

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                metadata_line = {
                    "_type": "metadata",
                    "key": session.key,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "metadata": session.metadata,
                    "last_consolidated": session.last_consolidated
                }
                f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
                for msg in session.messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                if fsync:
                    f.flush()
                    os.fsync(f.fileno())

            os.replace(tmp_path, path)

            if fsync:
                # fsync the directory so the rename is durable.
                # On Windows, opening a directory with O_RDONLY raises
                # PermissionError; some shared filesystems allow the open but
                # reject directory fsync with EINVAL.
                with suppress(PermissionError):
                    fd = os.open(str(path.parent), os.O_RDONLY)
                    try:
                        try:
                            os.fsync(fd)
                        except OSError as exc:
                            if exc.errno != errno.EINVAL:
                                raise
                    finally:
                        os.close(fd)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

        self._remember(session)

    def flush_all(self) -> int:
        """Re-save every cached session with fsync for durable shutdown.

        Returns the number of sessions flushed.  Errors on individual
        sessions are logged but do not prevent other sessions from being
        flushed.
        """
        flushed = 0
        cached = dict(self._overflow_cache.items())
        cached.update(self._cache)
        for key, session in cached.items():
            try:
                self.save(session, fsync=True)
                flushed += 1
            except Exception:
                logger.warning("Failed to flush session {}", key, exc_info=True)
        return flushed

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)
        self._overflow_cache.pop(key, None)

    def delete_session(self, key: str) -> bool:
        """Remove a session from disk (both workspace and legacy locations) and cache.

        Returns True if at least one JSONL file was found and unlinked.
        """
        paths = [
            self._get_session_path(key),
            self._get_legacy_lossy_path(key),
            self._get_legacy_session_path(key),
        ]
        self.invalidate(key)
        deleted = False
        for path in paths:
            if not path.exists():
                continue
            try:
                path.unlink()
                deleted = True
            except OSError as e:
                logger.warning("Failed to delete session file {}: {}", path, e)
        return deleted

    def fork_session_before_user_index(
        self,
        source_key: str,
        target_key: str,
        before_user_index: int,
    ) -> Session | None:
        """Create *target_key* from *source_key* before a global user-message index.

        ``before_user_index`` is zero-based over user messages in the full session:
        ``0`` means "before the first user message", ``1`` means "before the
        second user message", and so on. A value equal to the total user-message
        count copies the full session prefix. WebUI assistant-reply forks pass
        the next user index so the selected completed assistant turn is included.
        """
        if before_user_index < 0:
            return None
        source = self._cached(source_key) or self._load(source_key)
        if source is None:
            return None

        copied: list[dict[str, Any]] = []
        user_index = 0
        found_target = False
        for message in source.messages:
            if message.get("role") == "user":
                if user_index == before_user_index:
                    found_target = True
                    break
                user_index += 1
            copied.append(public_history_message(message))
        if user_index == before_user_index:
            found_target = True
        if not found_target:
            return None

        metadata = deepcopy(source.metadata)
        for key in _FORK_VOLATILE_METADATA_KEYS:
            metadata.pop(key, None)

        last_consolidated = min(source.last_consolidated, len(copied))
        if source.last_consolidated > len(copied):
            metadata.pop("_last_summary", None)
            last_consolidated = 0

        now = datetime.now()
        target = Session(
            key=target_key,
            messages=copied,
            created_at=now,
            updated_at=now,
            metadata=metadata,
            last_consolidated=last_consolidated,
        )
        self.save(target, fsync=True)
        return target

    def read_session_file(self, key: str) -> dict[str, Any] | None:
        """Load a session from disk without caching; intended for read-only HTTP endpoints.

        Returns ``{"key", "created_at", "updated_at", "metadata", "messages"}`` or
        ``None`` when the session file does not exist or fails to parse.
        """
        path = self._get_session_path(key)
        if not path.exists():
            return None
        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: str | None = None
            updated_at: str | None = None
            stored_key: str | None = None
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = data.get("created_at")
                        updated_at = data.get("updated_at")
                        stored_key = data.get("key")
                    else:
                        messages.append(data)
            return {
                "key": stored_key or key,
                "created_at": created_at,
                "updated_at": updated_at,
                "metadata": metadata,
                "messages": messages,
            }
        except Exception as e:
            logger.warning("Failed to read session {}: {}", key, e)
            repaired = self._repair(key)
            if repaired is not None:
                logger.info("Recovered read-only session view {} from corrupt file", key)
                return self._session_payload(repaired)
            return None

    def read_session_metadata(self, key: str) -> dict[str, Any] | None:
        """Load only the metadata record from a session file.

        This is used by WebUI routes that need session-level metadata but not the
        full conversation transcript.
        """
        path = self._get_session_path(key)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") != "metadata":
                        return None
                    metadata = data.get("metadata", {})
                    return {
                        "key": data.get("key") or key,
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                        "metadata": metadata if isinstance(metadata, dict) else {},
                    }
            return None
        except Exception as e:
            logger.warning("Failed to read session metadata {}: {}", key, e)
            repaired = self._repair(key)
            if repaired is not None:
                logger.info("Recovered read-only session metadata {} from corrupt file", key)
                return {
                    "key": repaired.key,
                    "created_at": repaired.created_at.isoformat(),
                    "updated_at": repaired.updated_at.isoformat(),
                    "metadata": repaired.metadata,
                }
            return None

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.

        Returns:
            List of session info dicts.
        """
        sessions = []

        for path in self.sessions_dir.glob("*.jsonl"):
            decoded = self._decode_storage_key(path.stem)
            fallback_key = decoded or path.stem.replace("_", ":", 1)
            try:
                # Read the metadata line and a small preview for session lists.
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            key = data.get("key") or fallback_key
                            metadata = data.get("metadata", {})
                            title = _metadata_title(metadata)
                            preview = ""
                            fallback_preview = ""
                            scanned_records = 0
                            scanned_chars = 0
                            for line in f:
                                if not line.strip():
                                    continue
                                scanned_records += 1
                                scanned_chars += len(line)
                                if (
                                    scanned_records > _SESSION_LIST_PREVIEW_MAX_RECORDS
                                    or scanned_chars > _SESSION_LIST_PREVIEW_MAX_CHARS
                                ):
                                    break
                                item = json.loads(line)
                                if item.get("_type") == "metadata":
                                    continue
                                text = _message_preview_text(item)
                                if not text:
                                    continue
                                if item.get("role") == "user":
                                    preview = text
                                    break
                                if not fallback_preview and item.get("role") == "assistant":
                                    fallback_preview = text
                            preview = preview or fallback_preview
                            fallback_time = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
                            sessions.append(
                                {
                                    "key": key,
                                    "created_at": data.get("created_at") or fallback_time,
                                    "updated_at": data.get("updated_at") or fallback_time,
                                    "title": title,
                                    "preview": preview,
                                    "path": str(path),
                                }
                            )
            except Exception:
                repaired = self._repair(fallback_key, path=path)
                if repaired is not None:
                    sessions.append(
                        {
                            "key": repaired.key,
                            "created_at": repaired.created_at.isoformat(),
                            "updated_at": repaired.updated_at.isoformat(),
                            "title": _metadata_title(repaired.metadata),
                            "preview": next(
                                (
                                    text
                                    for msg in repaired.messages
                                    if (text := _message_preview_text(msg))
                                ),
                                "",
                            ),
                            "path": str(path),
                        }
                    )
                continue
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
