"""Base class for memory providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class MemoryEntry:
    """A single memory entry.
    
    Attributes:
        content: The memory content (markdown format for long-term, plain text for history)
        timestamp: When this memory was created/updated
        metadata: Optional metadata (e.g., source, tags, importance)
        entry_type: Type of entry - "long_term" or "history"
    """
    content: str
    timestamp: datetime
    metadata: dict[str, Any] | None = None
    entry_type: str = "long_term"  # "long_term" or "history"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata or {},
            "entry_type": self.entry_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        """Create from dictionary."""
        return cls(
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata", {}),
            entry_type=data.get("entry_type", "long_term"),
        )


class BaseMemoryProvider(ABC):
    """Abstract base class for memory providers.
    
    Memory providers implement the storage backend for nanobot's two-layer
    memory system: long-term memory (facts/preferences) and history (event log).
    
    To create a custom memory provider:
    1. Subclass BaseMemoryProvider
    2. Implement all abstract methods
    3. Register your provider with MemoryProviderRegistry
    
    Example:
        class RedisMemoryProvider(BaseMemoryProvider):
            def __init__(self, config: dict):
                import redis
                self.client = redis.Redis(**config)
            
            def read_long_term(self) -> str:
                return self.client.get("nanobot:memory:long_term") or ""
            
            def write_long_term(self, content: str) -> None:
                self.client.set("nanobot:memory:long_term", content)
            
            def append_history(self, entry: str) -> None:
                self.client.lpush("nanobot:memory:history", entry)
            
            def search_history(self, query: str, limit: int = 10) -> list[MemoryEntry]:
                # Implementation...
                pass
            
            def close(self) -> None:
                self.client.close()
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the memory provider.
        
        Args:
            config: Provider-specific configuration dictionary
        """
        self.config = config or {}

    @abstractmethod
    def read_long_term(self) -> str:
        """Read the full long-term memory content.
        
        Returns:
            The complete long-term memory as markdown text.
            Return empty string if no memory exists.
        """
        pass

    @abstractmethod
    def write_long_term(self, content: str) -> None:
        """Write the full long-term memory content.
        
        Args:
            content: The complete long-term memory as markdown text.
                     This replaces any existing long-term memory.
        """
        pass

    @abstractmethod
    def append_history(self, entry: str) -> None:
        """Append an entry to the history log.
        
        Args:
            entry: A history entry (typically with [YYYY-MM-DD HH:MM] prefix).
                   This is appended to the existing history.
        """
        pass

    @abstractmethod
    def search_history(
        self, 
        query: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[MemoryEntry]:
        """Search history entries.
        
        Args:
            query: Optional text query to search for
            start_time: Optional start time filter
            end_time: Optional end time filter
            limit: Maximum number of entries to return
            
        Returns:
            List of matching memory entries, sorted by timestamp (newest first)
        """
        pass

    def get_memory_context(self) -> str:
        """Get formatted memory context for LLM prompts.
        
        Returns:
            Formatted memory context string. By default returns long-term memory
            with a header. Override for custom formatting.
        """
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    def close(self) -> None:
        """Clean up any resources (connections, file handles, etc.).
        
        Called when the memory provider is no longer needed.
        Override if your provider needs cleanup.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name identifier."""
        pass

    @property
    def is_available(self) -> bool:
        """Check if the provider is properly configured and available.
        
        Returns:
            True if the provider can be used, False otherwise.
            Override to add custom availability checks.
        """
        return True
