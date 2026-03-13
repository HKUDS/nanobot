"""In-memory memory provider for testing and development.

This provider stores all memory in RAM. It's useful for:
- Testing and development
- Ephemeral sessions where persistence is not needed
- Scenarios where disk I/O should be minimized

WARNING: All data is lost when the process exits!
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nanobot.memory.base import BaseMemoryProvider, MemoryEntry
from nanobot.memory.registry import MemoryProviderRegistry


class InMemoryProvider(BaseMemoryProvider):
    """In-memory memory provider.
    
    Stores memory in Python data structures. All data is lost on process exit.
    
    Configuration:
        max_history_entries: Maximum number of history entries to keep (default: 1000)
        
    Example:
        provider = InMemoryProvider({"max_history_entries": 500})
        provider.write_long_term("# User Preferences\n\nLikes Python.")
        provider.append_history("[2024-01-15 10:30] Started session")
        
        # Later...
        print(provider.read_long_term())  # Returns the stored content
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize in-memory provider.
        
        Args:
            config: Configuration with optional 'max_history_entries'
        """
        super().__init__(config)
        self._long_term: str = ""
        self._history: list[MemoryEntry] = []
        self._max_entries: int = self.config.get("max_history_entries", 1000)

    @property
    def name(self) -> str:
        """Return provider name."""
        return "in_memory"

    def read_long_term(self) -> str:
        """Read long-term memory content.
        
        Returns:
            The stored long-term memory content.
        """
        return self._long_term

    def write_long_term(self, content: str) -> None:
        """Write long-term memory content.
        
        Args:
            content: Complete long-term memory content.
        """
        self._long_term = content

    def append_history(self, entry: str) -> None:
        """Append entry to history.
        
        Args:
            entry: History entry text.
        """
        # Try to parse timestamp from entry
        timestamp = datetime.now()
        if entry.startswith("[") and "]" in entry:
            time_str = entry[1:entry.find("]")]
            try:
                timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
            except ValueError:
                pass

        memory_entry = MemoryEntry(
            content=entry,
            timestamp=timestamp,
            entry_type="history",
        )
        self._history.append(memory_entry)

        # Trim if exceeding max entries
        if len(self._history) > self._max_entries:
            self._history = self._history[-self._max_entries:]

    def search_history(
        self,
        query: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[MemoryEntry]:
        """Search history entries.
        
        Args:
            query: Optional text to search for
            start_time: Optional start time filter
            end_time: Optional end time filter
            limit: Maximum entries to return
            
        Returns:
            List of matching entries, newest first.
        """
        results = []
        for entry in self._history:
            # Apply filters
            if start_time and entry.timestamp < start_time:
                continue
            if end_time and entry.timestamp > end_time:
                continue
            if query and query.lower() not in entry.content.lower():
                continue
            results.append(entry)

        # Sort by timestamp (newest first) and limit
        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:limit]

    def get_memory_context(self) -> str:
        """Get formatted memory context.
        
        Returns:
            Long-term memory with header, or empty string if no memory.
        """
        return f"## Long-term Memory\n{self._long_term}" if self._long_term else ""

    def clear(self) -> None:
        """Clear all memory. Useful for testing."""
        self._long_term = ""
        self._history = []

    @property
    def history_count(self) -> int:
        """Return number of history entries."""
        return len(self._history)

    @property
    def is_available(self) -> bool:
        """Always available."""
        return True


# Register the provider
MemoryProviderRegistry.register("in_memory", InMemoryProvider)
