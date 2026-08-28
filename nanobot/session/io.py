"""Event-loop-safe scheduling for synchronous session I/O."""

from __future__ import annotations

import asyncio
from typing import Any
from weakref import WeakValueDictionary

from nanobot.session.manager import Session, SessionManager
from nanobot.utils.cancellation import shield_and_drain


class SessionIO:
    """Schedule ``SessionManager`` transactions without blocking the event loop.

    ``SessionManager`` remains the sole owner of persistence and cache semantics.
    This boundary owns only async scheduling, per-session admission, and
    cancellation settlement.
    """

    def __init__(self, sessions: SessionManager) -> None:
        self.sessions = sessions
        self._session_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def _session_lock(self, key: str) -> asyncio.Lock:
        lock = self._session_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[key] = lock
        return lock

    async def get_or_create(self, key: str) -> Session:
        """Load once per key while preserving the manager's cache identity."""
        async with self._session_lock(key):
            return await shield_and_drain(
                asyncio.to_thread(self.sessions.get_or_create, key)
            )

    async def save(self, session: Session, *, fsync: bool = False) -> None:
        """Finish an accepted save before propagating caller cancellation."""
        async with self._session_lock(session.key):
            operation = (
                asyncio.to_thread(self.sessions.save, session, fsync=True)
                if fsync
                else asyncio.to_thread(self.sessions.save, session)
            )
            await shield_and_drain(operation)

    async def save_runtime_checkpoint(self, session: Session) -> None:
        """Finish an accepted checkpoint before propagating caller cancellation."""
        async with self._session_lock(session.key):
            await shield_and_drain(
                asyncio.to_thread(self.sessions.save_runtime_checkpoint, session)
            )

    async def read_session_metadata(self, key: str) -> dict[str, Any] | None:
        """Read session metadata without blocking the event loop."""
        return await asyncio.to_thread(self.sessions.read_session_metadata, key)

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List sessions without blocking the event loop."""
        return await asyncio.to_thread(self.sessions.list_sessions)
