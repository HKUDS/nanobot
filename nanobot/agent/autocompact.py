"""Auto compact: proactive compression of idle sessions to reduce token cost and latency."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Collection
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

from nanobot.events import NO_EVENTS, EventSink
from nanobot.session.keys import is_dream_session
from nanobot.session.manager import Session, SessionManager
from nanobot.session.summary import (
    SessionSummary,
    session_summary_from_metadata,
)

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator
    from nanobot.utils.llm_runtime import LLMRuntime

SessionEventFactory = Callable[[str], EventSink]


class AutoCompact:
    def __init__(
        self,
        sessions: SessionManager,
        consolidator: Consolidator,
        session_ttl_minutes: int = 0,
        bind_events: SessionEventFactory | None = None,
        *,
        session_lock: Callable[[str], asyncio.Lock],
    ):
        self.sessions = sessions
        self.consolidator = consolidator
        self._ttl = session_ttl_minutes
        self._archiving: set[str] = set()
        self._summaries: dict[str, SessionSummary] = {}
        self._bind_events = bind_events
        self._session_lock = session_lock

    def _is_expired(self, ts: datetime | str | None,
                    now: datetime | None = None) -> bool:
        if self._ttl <= 0 or not ts:
            return False
        try:
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            current = now or datetime.now()
            if getattr(ts, "tzinfo", None) is not None or current.tzinfo is not None:
                idle_seconds = current.timestamp() - ts.timestamp()
            else:
                idle_seconds = (current - ts).total_seconds()
        except (OSError, OverflowError, TypeError, ValueError):
            # list_sessions() forwards raw persisted metadata; an unusable value
            # must not escape the idle scan and stop the agent loop.
            return False
        return idle_seconds >= self._ttl * 60

    async def check_expired(
        self,
        schedule_background: Callable[[Coroutine[Any, Any, None]], None],
        resolve_runtime: Callable[[Session], Awaitable[LLMRuntime]],
        active_session_keys: Collection[str] = (),
    ) -> None:
        """Schedule idle archival without blocking the event loop."""
        now = datetime.now()
        active_keys = set(active_session_keys)
        for info in await self.sessions.state.list_sessions():
            key = info.get("key", "")
            if not key or is_dream_session(key) or key in self._archiving:
                continue
            if key in active_keys or not self._is_expired(info.get("updated_at"), now):
                continue
            if not await self.sessions.state.has_unarchived_messages(key):
                continue
            session = await self.sessions.state.get(key)
            try:
                runtime = await resolve_runtime(session)
            except (KeyError, ValueError):
                continue
            self._archiving.add(key)
            schedule_background(self._archive(key, runtime=runtime))

    async def _archive(self, key: str, *, runtime: LLMRuntime) -> None:
        if is_dream_session(key):
            self._archiving.discard(key)
            return
        try:
            async with self._session_lock(key):
                # Idle compaction and turns share one transcript boundary.
                summary = await self.consolidator.compact_idle_session(
                    key,
                    runtime=runtime,
                    events=self._bind_events(key) if self._bind_events else NO_EVENTS,
                )
                if summary:
                    session = await self.sessions.state.get(key)
                    stored = session_summary_from_metadata(
                        session.metadata,
                        fallback_last_active=session.updated_at,
                    )
                    if stored is not None:
                        self._summaries[key] = stored
        except Exception:
            logger.exception("Auto-compact: failed for {}", key)
        finally:
            self._archiving.discard(key)

    async def prepare_session(
        self,
        session: Session,
        key: str,
    ) -> tuple[Session, SessionSummary | None]:
        """Resolve a summary while preserving the turn's owner-issued draft."""
        if is_dream_session(key):
            self._archiving.discard(key)
            self._summaries.pop(key, None)
            return session, None
        # Hot path: summary from in-memory dict (process hasn't restarted).
        entry = self._summaries.pop(key, None)
        if entry:
            return session, entry
        # Cold path: summary persisted in session metadata (process restarted).
        # Persisted metadata may outlive schema changes; a malformed summary must
        # not abort turn preparation.
        return session, session_summary_from_metadata(
            session.metadata,
            fallback_last_active=session.updated_at,
        )
