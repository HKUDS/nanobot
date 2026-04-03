"""Abstract base class for session manager plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSessionManager(ABC):
    """
    Abstract interface for session storage backends.

    Implement this class and register via entry_points to provide a custom
    session backend::

        [project.entry-points."nanobot.sessions"]
        mybackend = "my_pkg.session:MySessionManager"

    Then set ``sessionBackend: "mybackend"`` in config.json agents.defaults.
    """

    @abstractmethod
    def get_or_create(self, key: str) -> Any:
        """Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            A Session instance.
        """

    @abstractmethod
    def save(self, session: Any) -> None:
        """Persist the session to storage."""

    @abstractmethod
    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""

    @abstractmethod
    def list_sessions(self) -> list[dict[str, Any]]:
        """Return a list of session info dicts."""
