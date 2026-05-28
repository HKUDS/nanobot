"""Memory system for persistent agent memory."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


_DAILY_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


class MemoryStore:
    """Three-layer memory:
    - MEMORY.md   — long-term durable facts (LLM-curated, may compress)
    - HISTORY.md  — paragraph-per-consolidation log (LLM-summarised, FIFO-capped)
    - memory/YYYY-MM-DD.md — daily notes (raw consolidated message windows, append-only)

    Daily notes back up the lossy summariser: if MEMORY.md / HISTORY.md lose a
    specific, the verbatim text is still on disk and queryable via the
    memory_search / memory_get tools.
    """

    _MAX_MEMORY_LINES = 200
    _MAX_HISTORY_LINES = 500

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def _daily_file(self, when: datetime | None = None) -> Path:
        when = when or datetime.now()
        return self.memory_dir / f"{when.strftime('%Y-%m-%d')}.md"

    def write_daily(self, entry: str, when: datetime | None = None) -> Path:
        """Append a heading-tagged entry to today's daily notes file. Returns the file path."""
        when = when or datetime.now()
        path = self._daily_file(when)
        header = f"## {when.strftime('%Y-%m-%d %H:%M')} — consolidation"
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{header}\n\n{entry.rstrip()}\n\n")
        return path

    def list_daily_files(self, days: int = 30) -> list[Path]:
        """Return daily-note paths within the last `days` calendar days, newest first."""
        cutoff = datetime.now().date().toordinal() - max(0, days - 1)
        out: list[Path] = []
        for p in self.memory_dir.iterdir():
            if not (p.is_file() and _DAILY_FILE_RE.match(p.name)):
                continue
            try:
                d = datetime.strptime(p.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if d.toordinal() >= cutoff:
                out.append(p)
        out.sort(key=lambda p: p.stem, reverse=True)
        return out

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        """Persist MEMORY.md to disk in full. The injected copy is capped
        separately by `get_memory_context`; the on-disk file is the source of
        truth and never silently truncated.
        """
        self.memory_file.write_text(content, encoding="utf-8")

    # ---- M4: section-aware operations ---------------------------------------
    # MEMORY.md sections are marked by ## headings. The heading text (after
    # stripping any "(annotation)" suffix) is the section name. A section runs
    # from its heading to the next ## heading or EOF. Section names are
    # case-insensitive but preserved on round-trip.

    PINNED_SECTION = "Pinned"

    def _parse_sections(self, content: str) -> list[tuple[str, str, str]]:
        """Split content into (heading_line, name_lower, body) tuples.

        The first chunk (before any ##) is returned with heading_line="" and
        name_lower="" so callers can re-emit pre-section content verbatim.
        """
        if not content:
            return []
        heading_re = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
        positions = [(m.start(), m.group(0), m.group(1)) for m in heading_re.finditer(content)]
        if not positions:
            return [("", "", content)]
        out: list[tuple[str, str, str]] = []
        first_start = positions[0][0]
        if first_start > 0:
            out.append(("", "", content[:first_start]))
        for i, (start, heading_line, raw_name) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(content)
            # body excludes the heading line itself
            heading_end = content.find("\n", start)
            body_start = heading_end + 1 if heading_end != -1 else end
            body = content[body_start:end]
            # Strip "(annotation)" suffix when matching: "Pinned (do not compress)" → "pinned"
            normalised = re.sub(r"\s*\(.*\)\s*$", "", raw_name).strip().lower()
            out.append((heading_line, normalised, body))
        return out

    def get_section(self, name: str) -> str | None:
        """Return the body of a section by name (case-insensitive). None if absent."""
        target = name.strip().lower()
        for _heading, sec_name, body in self._parse_sections(self.read_long_term()):
            if sec_name == target:
                return body
        return None

    def list_sections(self) -> list[str]:
        """Return section names (in document order, normalised lowercase). Skips the pre-section preamble."""
        return [
            name for _h, name, _body in self._parse_sections(self.read_long_term())
            if name
        ]

    def upsert_section(self, name: str, body: str, heading_line: str | None = None) -> None:
        """Replace section `name` (case-insensitive) in place, or append it if absent.
        `heading_line` is the literal heading line written to disk (default: '## <name>').
        Preserves all other sections verbatim.
        """
        target = name.strip().lower()
        heading_line = heading_line or f"## {name.strip()}"
        # Normalise body so it begins with one blank line and ends with one.
        body_norm = "\n" + body.strip("\n") + "\n" if body.strip("\n") else "\n"

        parsed = self._parse_sections(self.read_long_term())
        if not parsed:
            self.write_long_term(f"{heading_line}\n{body_norm}".rstrip() + "\n")
            return

        out_parts: list[str] = []
        found = False
        for heading, sec_name, sec_body in parsed:
            if sec_name == target:
                out_parts.append(f"{heading_line}\n{body_norm}")
                found = True
            elif heading == "":  # preamble (pre-section content)
                out_parts.append(sec_body)
            else:
                out_parts.append(f"{heading}\n{sec_body}")
        if not found:
            # Append the new section to the end
            tail = out_parts[-1] if out_parts else ""
            if tail and not tail.endswith("\n"):
                out_parts.append("\n")
            out_parts.append(f"{heading_line}\n{body_norm}")

        self.write_long_term("".join(out_parts).rstrip() + "\n")

    def append_to_section(self, name: str, line: str, heading_line: str | None = None) -> None:
        """Append a line to a section (creating it if needed)."""
        existing = self.get_section(name) or ""
        body = (existing.rstrip() + "\n" + line.rstrip()).lstrip("\n")
        self.upsert_section(name, body, heading_line=heading_line)

    def get_pinned(self) -> str:
        """Return the verbatim body of the Pinned section, or empty string."""
        return self.get_section(self.PINNED_SECTION) or ""

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")
        # Trim oldest entries if history exceeds limit
        if self.history_file.exists():
            lines = self.history_file.read_text(encoding="utf-8").splitlines()
            if len(lines) > self._MAX_HISTORY_LINES:
                logger.warning(
                    "History trimmed: {} lines exceeds limit of {}", len(lines), self._MAX_HISTORY_LINES
                )
                trimmed = "\n".join(lines[-self._MAX_HISTORY_LINES :])
                self.history_file.write_text(trimmed + "\n", encoding="utf-8")

    def get_memory_context(self) -> str:
        """Return MEMORY.md formatted for system-prompt injection. The on-disk
        file is the source of truth; if it exceeds the injection cap, return a
        truncated copy with a marker pointing the agent at the full file."""
        long_term = self.read_long_term()
        if not long_term:
            return ""
        lines = long_term.splitlines()
        if len(lines) > self._MAX_MEMORY_LINES:
            kept = "\n".join(lines[: self._MAX_MEMORY_LINES])
            dropped = len(lines) - self._MAX_MEMORY_LINES
            marker = (
                f"\n\n[Context-truncated — showing first {self._MAX_MEMORY_LINES} of "
                f"{len(lines)} lines. {dropped} lines remain on disk in "
                f"`memory/MEMORY.md` (read with read_file if needed).]"
            )
            return f"## Long-term Memory\n{kept}{marker}"
        return f"## Long-term Memory\n{long_term}"

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

        Returns True on success (including no-op), False on failure.
        """
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated:-keep_count]
            if not old_messages:
                return True
            logger.info("Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count)

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")

        # Append raw consolidated window to today's daily note BEFORE the LLM call.
        # If the LLM consolidation fails (it has — see vault/typed-memory-port-from-openclaw.md)
        # the verbatim text is still on disk, queryable via memory_search / memory_get.
        if lines:
            try:
                self.write_daily(f"session={session.key}\n\n" + "\n".join(lines))
            except Exception:
                logger.exception("Failed to write daily note (continuing with consolidation)")

        current_memory = self.read_long_term()
        # M4: capture the Pinned section verbatim so it survives the LLM rewrite
        # byte-identically, regardless of what the LLM does. Safety/critical
        # facts live here precisely so consolidation can't silently smooth them.
        pinned_before = self.get_pinned()
        pinned_heading_line = None
        for heading, sec_name, _body in self._parse_sections(current_memory):
            if sec_name == self.PINNED_SECTION.lower():
                pinned_heading_line = heading
                break

        system_prompt = (
            "You are a memory consolidation agent. Call the save_memory tool "
            "with your consolidation of the conversation.\n\n"
            "RULES:\n"
            "- The `## Pinned` section (if present) holds facts that MUST NOT "
            "be modified, summarised, deleted, or paraphrased. Carry it "
            "through unchanged — same heading, same body, byte-for-byte. The "
            "system will verify and restore it after your call, so any "
            "modifications you make are wasted work.\n"
            "- For everything else: preserve specifics relating to safety, "
            "health, crises, triggers, coping strategies, clinical guidance, "
            "and named people/dates verbatim where possible. Compress "
            "casual/transient context only."
        )
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.tool_calls[0].arguments
            # Some providers return arguments as a JSON string instead of dict
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                return False

            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)
            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    self.write_long_term(update)
                    # M4: force-restore the Pinned section byte-for-byte if it
                    # existed before. This is the guarantee — the LLM's
                    # cooperation is hopeful; the post-write restore is firm.
                    if pinned_before:
                        self.upsert_section(
                            self.PINNED_SECTION,
                            pinned_before,
                            heading_line=pinned_heading_line,
                        )

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info("Memory consolidation done: {} messages, last_consolidated={}", len(session.messages), session.last_consolidated)
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
