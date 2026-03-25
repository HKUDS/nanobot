"""Original file-based memory store: MEMORY.md (long-term facts) + HISTORY.md (event log).

This is the default nanobot memory implementation that persists memories as
markdown files in the workspace.  It uses an LLM to consolidate conversations
into structured long-term facts and a grep-searchable history log.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.memory.base import BaseMemoryStore
from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


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
                        "description": (
                            "A paragraph summarizing key events/decisions/topics. "
                            "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search."
                        ),
                    },
                    "memory_update": {
                        "type": "string",
                        "description": (
                            "Full updated long-term memory as markdown. Include all existing "
                            "facts plus new ones. Return unchanged if nothing new."
                        ),
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


def _ensure_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _normalize_save_memory_args(args: Any) -> dict[str, Any] | None:
    if isinstance(args, str):
        args = json.loads(args)
    if isinstance(args, list):
        return args[0] if args and isinstance(args[0], dict) else None
    return args if isinstance(args, dict) else None


_TOOL_CHOICE_ERROR_MARKERS = (
    "tool_choice",
    "toolchoice",
    "does not support",
    'should be ["none", "auto"]',
)


def _is_tool_choice_unsupported(content: str | None) -> bool:
    text = (content or "").lower()
    return any(m in text for m in _TOOL_CHOICE_ERROR_MARKERS)


class LongTermMemoryStore(BaseMemoryStore):
    """Two-layer file-based memory: MEMORY.md + HISTORY.md.

    - ``MEMORY.md`` holds curated long-term facts (always loaded into context).
    - ``HISTORY.md`` is an append-only event log searchable via grep.

    Consolidation uses an LLM to summarize conversations and extract facts.
    """

    def __init__(self, workspace: Path, **kwargs: Any):
        super().__init__(workspace, **kwargs)
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    # ── File I/O ─────────────────────────────────────────────────────────

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    # ── Context integration ──────────────────────────────────────────────

    def get_memory_context(self, **kwargs: Any) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    # ── CRUD operations ──────────────────────────────────────────────────

    async def add(
        self,
        messages: list[dict[str, Any]],
        user_id: str = "default",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """For file-based memory, ``add`` appends raw messages to the history log."""
        formatted = self._format_messages(messages)
        if formatted:
            self.append_history(formatted)
        return {"status": "ok", "count": len(messages)}

    async def search(
        self,
        query: str,
        user_id: str = "default",
        limit: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Simple substring search over MEMORY.md and HISTORY.md."""
        results: list[dict[str, Any]] = []
        query_lower = query.lower()

        long_term = self.read_long_term()
        if long_term and query_lower in long_term.lower():
            results.append({"id": "long_term", "memory": long_term, "source": "MEMORY.md"})

        if self.history_file.exists():
            text = self.history_file.read_text(encoding="utf-8")
            for block in text.split("\n\n"):
                block = block.strip()
                if block and query_lower in block.lower():
                    results.append({"id": f"history_{hash(block)}", "memory": block, "source": "HISTORY.md"})
                    if len(results) >= limit:
                        break

        return results[:limit]

    async def get_all(
        self,
        user_id: str = "default",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Return long-term memory and all history blocks."""
        entries: list[dict[str, Any]] = []

        long_term = self.read_long_term()
        if long_term:
            entries.append({"id": "long_term", "memory": long_term, "source": "MEMORY.md"})

        if self.history_file.exists():
            text = self.history_file.read_text(encoding="utf-8")
            for i, block in enumerate(text.split("\n\n")):
                block = block.strip()
                if block:
                    entries.append({"id": f"history_{i}", "memory": block, "source": "HISTORY.md"})

        return entries

    async def update(self, memory_id: str, content: str, **kwargs: Any) -> bool:
        """Update long-term memory content (history is append-only)."""
        if memory_id == "long_term":
            self.write_long_term(content)
            return True
        logger.warning("File-based memory only supports updating 'long_term'; got {}", memory_id)
        return False

    async def delete(self, memory_id: str, **kwargs: Any) -> bool:
        """Delete is only supported for the long-term memory file."""
        if memory_id == "long_term":
            self.write_long_term("")
            return True
        logger.warning("File-based memory does not support deleting history entries")
        return False

    # ── Consolidation ────────────────────────────────────────────────────

    async def consolidate(
        self,
        messages: list[dict[str, Any]],
        provider: LLMProvider,
        model: str,
    ) -> bool:
        if not messages:
            return True

        current_memory = self.read_long_term()
        prompt = (
            "Process this conversation and call the save_memory tool with your consolidation.\n\n"
            f"## Current Long-term Memory\n{current_memory or '(empty)'}\n\n"
            f"## Conversation to Process\n{self._format_messages(messages)}"
        )
        chat_messages = [
            {
                "role": "system",
                "content": (
                    "You are a memory consolidation agent. "
                    "Call the save_memory tool with your consolidation of the conversation."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        try:
            forced = {"type": "function", "function": {"name": "save_memory"}}
            response = await provider.chat_with_retry(
                messages=chat_messages,
                tools=_SAVE_MEMORY_TOOL,
                model=model,
                tool_choice=forced,
            )

            if response.finish_reason == "error" and _is_tool_choice_unsupported(response.content):
                logger.warning("Forced tool_choice unsupported, retrying with auto")
                response = await provider.chat_with_retry(
                    messages=chat_messages,
                    tools=_SAVE_MEMORY_TOOL,
                    model=model,
                    tool_choice="auto",
                )

            if not response.has_tool_calls:
                logger.warning(
                    "Memory consolidation: LLM did not call save_memory "
                    "(finish_reason={}, content_len={}, content_preview={})",
                    response.finish_reason,
                    len(response.content or ""),
                    (response.content or "")[:200],
                )
                return self._fail_or_raw_archive(messages)

            args = _normalize_save_memory_args(response.tool_calls[0].arguments)
            if args is None:
                logger.warning("Memory consolidation: unexpected save_memory arguments")
                return self._fail_or_raw_archive(messages)

            if "history_entry" not in args or "memory_update" not in args:
                logger.warning("Memory consolidation: save_memory payload missing required fields")
                return self._fail_or_raw_archive(messages)

            entry = args["history_entry"]
            update = args["memory_update"]

            if entry is None or update is None:
                logger.warning("Memory consolidation: save_memory payload contains null required fields")
                return self._fail_or_raw_archive(messages)

            entry = _ensure_text(entry).strip()
            if not entry:
                logger.warning("Memory consolidation: history_entry is empty after normalization")
                return self._fail_or_raw_archive(messages)

            self.append_history(entry)
            update = _ensure_text(update)
            if update != current_memory:
                self.write_long_term(update)

            self._consecutive_failures = 0
            logger.info("Memory consolidation done for {} messages", len(messages))
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return self._fail_or_raw_archive(messages)
