"""Types for the memory system."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MemoryItem:
    """A single memory entry."""

    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def memory_type(self) -> str:
        """Memory type: preference, fact, task, note, etc."""
        return self.metadata.get("type", "note")

    @property
    def source(self) -> str:
        """Source of this memory: conversation, import, tool, etc."""
        return self.metadata.get("source", "conversation")

    @property
    def user_id(self) -> str | None:
        """User ID associated with this memory."""
        return self.metadata.get("user_id")


@dataclass
class MemorySearchResult:
    """Result of a memory search operation."""

    memories: list[MemoryItem]
    query: str
    total_found: int = 0

    def to_context_string(self, max_items: int = 8) -> str:
        """
        Format memories for injection into the LLM prompt.

        Args:
            max_items: Maximum number of items to include.

        Returns:
            Formatted string for prompt injection.
        """
        if not self.memories:
            return ""

        lines = []
        for mem in self.memories[:max_items]:
            score_str = f" (relevance: {mem.score:.2f})" if mem.score > 0 else ""
            lines.append(f"- {mem.text}{score_str}")

        return "\n".join(lines)
