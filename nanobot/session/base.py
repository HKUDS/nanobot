"""Abstract base class for session manager plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.session.manager import Session


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
    def get_or_create(self, key: str) -> Session:
        """Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The existing session if found, otherwise a newly created Session.
        """

    @abstractmethod
    def save(self, session: Session) -> None:
        """Persist the session to storage. Implementations should be idempotent."""

    @abstractmethod
    def invalidate(self, key: str) -> None:
        """Remove a session from cache and storage. Silent if key does not exist."""

    @abstractmethod
    def list_sessions(self) -> list[dict[str, Any]]:
        """Return a list of session info dicts.

        Each dict must contain at least: ``key`` (str), ``created_at`` (ISO str),
        ``updated_at`` (ISO str).
        """
