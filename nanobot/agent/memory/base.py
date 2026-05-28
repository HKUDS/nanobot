"""Abstract base class for memory store implementations.

All memory backends (file-based, Mem0, LightMem, A-MEM, SimpleMem, etc.)
should inherit from BaseMemoryStore and implement the abstract methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


class BaseMemoryStore(ABC):
    """Abstract base class for all memory store implementations.

    Defines the standard interface that every memory backend must provide.
    Implementations range from simple file-based storage to sophisticated
    vector-database-backed frameworks like Mem0, LightMem, A-MEM, and SimpleMem.

    Subclasses MUST implement:
        - add, search, get_all, update, delete  (CRUD)
        - get_memory_context                      (agent prompt integration)
        - consolidate                             (backward compat with MemoryConsolidator)

    Subclasses MAY override:
        - read_long_term, write_long_term, append_history  (file-based helpers)
    """

    _MAX_FAILURES_BEFORE_RAW_ARCHIVE = 3

    def __init__(self, workspace: Path, **kwargs: Any):
        self.workspace = workspace
        self._consecutive_failures = 0

    # ── Core CRUD ────────────────────────────────────────────────────────

    @abstractmethod
    async def add(
        self,
        messages: list[dict[str, Any]],
        user_id: str = "default",
        **kwargs: Any,
    ) -> Any:
        """Add new memories extracted from conversation messages.

        Args:
            messages: Conversation messages to process and memorize.
            user_id:  Identifier for the user or session scope.

        Returns:
            Implementation-specific result (e.g., list of memory IDs, status dict).
        """

    @abstractmethod
    async def search(
        self,
        query: str,
        user_id: str = "default",
        limit: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search for memories semantically relevant to *query*.

        Args:
            query:   Natural-language search query.
            user_id: Scope the search to this user/session.
            limit:   Maximum number of results to return.

        Returns:
            List of memory dicts.  Each dict should contain at least
            ``{"id": ..., "memory": ...}``.
        """

    @abstractmethod
    async def get_all(
        self,
        user_id: str = "default",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Retrieve every stored memory for *user_id*.

        Returns:
            List of all memory entries.
        """

    @abstractmethod
    async def update(
        self,
        memory_id: str,
        content: str,
        **kwargs: Any,
    ) -> bool:
        """Update an existing memory entry.

        Args:
            memory_id: Unique identifier of the memory.
            content:   New content to replace the old memory.

        Returns:
            ``True`` if the update succeeded.
        """

    @abstractmethod
    async def delete(self, memory_id: str, **kwargs: Any) -> bool:
        """Delete a single memory entry.

        Returns:
            ``True`` if deletion succeeded.
        """

    # ── Agent prompt integration ─────────────────────────────────────────

    @abstractmethod
    def get_memory_context(self, **kwargs: Any) -> str:
        """Build a formatted context string for injection into the agent prompt.

        Returns:
            A markdown-formatted string summarizing relevant memories,
            or an empty string when no memories exist.
        """

    # ── Consolidation (used by MemoryConsolidator) ───────────────────────

    @abstractmethod
    async def consolidate(
        self,
        messages: list[dict[str, Any]],
        provider: LLMProvider,
        model: str,
        user_id: str = "default",
    ) -> bool:
        """Consolidate a batch of conversation messages into persistent memory.

        Called by ``MemoryConsolidator`` to archive old messages and keep the
        active context window within limits.

        Args:
            messages: The message chunk to consolidate.
            provider: LLM provider used for summarization.
            model:    Model identifier.
            user_id:  Identifier for the user/session scope.

        Returns:
            ``True`` when consolidation (or fallback archival) succeeded.
        """

    # ── File-based helpers (no-op defaults; override in file-based impls) ─

    def read_long_term(self) -> str:
        """Read long-term memory content.  Override for file-based stores."""
        return ""

    def write_long_term(self, content: str) -> None:
        """Write long-term memory content.  Override for file-based stores."""

    def append_history(self, entry: str) -> None:
        """Append an entry to the history log.  Override for file-based stores."""

    # ── Shared failure handling ──────────────────────────────────────────

    def _fail_or_raw_archive(self, messages: list[dict[str, Any]]) -> bool:
        """Increment failure counter; after threshold, dump raw messages and reset."""
        self._consecutive_failures += 1
        if self._consecutive_failures < self._MAX_FAILURES_BEFORE_RAW_ARCHIVE:
            return False
        self._raw_archive(messages)
        self._consecutive_failures = 0
        return True

    def _raw_archive(self, messages: list[dict[str, Any]]) -> None:
        """Fallback: dump raw messages to history without LLM summarization."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        formatted = self._format_messages(messages)
        self.append_history(f"[{ts}] [RAW] {len(messages)} messages\n{formatted}")
        logger.warning(
            "Memory consolidation degraded: raw-archived {} messages",
            len(messages),
        )

    @staticmethod
    def _format_messages(messages: list[dict[str, Any]]) -> str:
        """Format messages into a human-readable log string."""
        lines: list[str] = []
        for msg in messages:
            if not msg.get("content"):
                continue
            tools = (
                f" [tools: {', '.join(msg['tools_used'])}]"
                if msg.get("tools_used")
                else ""
            )
            lines.append(
                f"[{msg.get('timestamp', '?')[:16]}] "
                f"{msg['role'].upper()}{tools}: {msg['content']}"
            )
        return "\n".join(lines)
