"""Memory system for persistent agent memory."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


_CONSOLIDATION_SYSTEM = """\
You are a memory consolidation agent. Output EXACTLY the following format with no other text:

## HISTORY_ENTRY
A paragraph (2-5 sentences) summarizing key events/decisions/topics from the conversation. \
Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.

## MEMORY_UPDATE
Full updated long-term memory as markdown. Include all existing facts plus new ones. \
Return the existing memory unchanged if nothing new."""

_SECTION_RE = re.compile(
    r"##\s*HISTORY_ENTRY\s*\n(.*?)\n##\s*MEMORY_UPDATE\s*\n(.*)",
    re.DOTALL,
)


class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
        temperature: float = 0.0,
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

        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and produce your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            response = await provider.chat_with_retry(
                messages=[
                    {"role": "system", "content": _CONSOLIDATION_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                model=model,
                temperature=temperature,
            )

            if not response.content:
                logger.warning("Memory consolidation: empty response from LLM, skipping")
                return False

            match = _SECTION_RE.search(response.content)
            if not match:
                logger.warning("Memory consolidation: could not parse response, skipping")
                return False

            entry = match.group(1).strip()
            update = match.group(2).strip()

            if entry:
                self.append_history(entry)
            if update and update != current_memory:
                self.write_long_term(update)

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info("Memory consolidation done: {} messages, last_consolidated={}", len(session.messages), session.last_consolidated)
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
