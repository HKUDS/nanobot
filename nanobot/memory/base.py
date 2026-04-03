"""Abstract base class for memory store plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseMemoryStore(ABC):
    """
    Abstract interface for memory storage backends.

    Implement this class and register via entry_points to provide a custom
    memory backend::

        [project.entry-points."nanobot.memory"]
        mybackend = "my_pkg.memory:MyMemoryStore"

    Then set ``memoryBackend: "mybackend"`` in config.json agents.defaults.
    """

    @abstractmethod
    def read_long_term(self) -> str:
        """Return the full long-term memory content (MEMORY.md equivalent).

        Returns empty string if no memory exists yet.
        """

    @abstractmethod
    def write_long_term(self, content: str) -> None:
        """Overwrite the long-term memory with *content*. Implementations must be idempotent."""

    @abstractmethod
    def append_history(self, entry: str) -> None:
        """Append a single history entry (HISTORY.md equivalent)."""

    def get_memory_context(self) -> str:
        """Return formatted memory context for inclusion in the system prompt.

        Default implementation wraps ``read_long_term()``. Override to
        customise the format or add extra context sections.
        """
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""
