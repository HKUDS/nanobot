"""Abstract base class for memory stores."""

from abc import ABC, abstractmethod
from pathlib import Path

from nanobot.memory.types import MemoryItem, MemorySearchResult


class BaseMemoryStore(ABC):
    """
    Abstract base for all memory store implementations.

    Provides a consistent interface whether backed by files, ChromaDB/Mem0,
    or any future backend.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace

    @abstractmethod
    def search(self, query: str, user_id: str | None = None, limit: int = 8) -> MemorySearchResult:
        """
        Search memories relevant to a query.

        Args:
            query: The search query (typically the user's message + context).
            user_id: Optional user ID for filtering (e.g., session_key).
            limit: Maximum number of results.

        Returns:
            MemorySearchResult with matching memories.
        """
        ...

    @abstractmethod
    def add(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> list[MemoryItem]:
        """
        Extract and store memories from a conversation turn.

        Args:
            messages: Conversation messages [{"role": "user", "content": "..."}, ...].
            user_id: Optional user ID for namespacing.
            metadata: Optional extra metadata to attach.

        Returns:
            List of newly created/updated MemoryItems.
        """
        ...

    @abstractmethod
    def get_all(self, user_id: str | None = None, limit: int = 100) -> list[MemoryItem]:
        """
        Get all memories, optionally filtered by user.

        Args:
            user_id: Optional user ID filter.
            limit: Maximum number of results.

        Returns:
            List of MemoryItems.
        """
        ...

    @abstractmethod
    def delete(self, memory_id: str) -> bool:
        """
        Delete a specific memory.

        Args:
            memory_id: The ID of the memory to delete.

        Returns:
            True if deleted, False if not found.
        """
        ...

    def get_memory_context(self, query: str | None = None, user_id: str | None = None) -> str:
        """
        Get formatted memory context for prompt injection.

        This is the main entry point used by ContextBuilder.

        Args:
            query: The current query for relevance-based retrieval.
                   If None, falls back to returning recent/all memories.
            user_id: Optional user ID for filtering.

        Returns:
            Formatted string ready for system prompt injection.
        """
        if query:
            result = self.search(query, user_id=user_id, limit=8)
            context = result.to_context_string()
            if context:
                return f"## Relevant Memories (top-k retrieval)\n{context}"

        # Fallback: return recent memories
        all_mems = self.get_all(user_id=user_id, limit=10)
        if not all_mems:
            return ""

        lines = [f"- {m.text}" for m in all_mems[:10]]
        return "## Recent Memories\n" + "\n".join(lines)
