"""Async adapters for the synchronous session manager."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from nanobot.session.manager import Session, SessionManager
from nanobot.utils.cancellation import shield_and_drain

_P = ParamSpec("_P")
_T = TypeVar("_T")


async def call(operation: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
    """Run one synchronous session transaction to settlement in a worker."""
    return await shield_and_drain(asyncio.to_thread(operation, *args, **kwargs))


async def get_or_create(sessions: SessionManager, key: str) -> Session:
    """Load a session without blocking the caller's event loop."""
    return await call(sessions.get_or_create, key)


async def save(
    sessions: SessionManager,
    session: Session,
    *,
    fsync: bool = False,
) -> None:
    """Finish an accepted save before propagating caller cancellation."""
    if fsync:
        await call(sessions.save, session, fsync=True)
    else:
        await call(sessions.save, session)


async def save_runtime_checkpoint(sessions: SessionManager, session: Session) -> None:
    """Finish an accepted checkpoint before propagating caller cancellation."""
    await call(sessions.save_runtime_checkpoint, session)


async def read_session_metadata(
    sessions: SessionManager,
    key: str,
) -> dict[str, Any] | None:
    """Read session metadata without blocking the event loop."""
    return await asyncio.to_thread(sessions.read_session_metadata, key)


async def list_sessions(sessions: SessionManager) -> list[dict[str, Any]]:
    """List sessions without blocking the event loop."""
    return await asyncio.to_thread(sessions.list_sessions)
