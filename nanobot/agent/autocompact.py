"""Auto compact: proactive compression of idle sessions to reduce token cost and latency."""

from __future__ import annotations

from collections.abc import Awaitable, Collection
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

from nanobot.bus.outbound_events import ContextCompactionCallback
from nanobot.session.manager import MIN_COMPACTED_REPLAY_MESSAGES, Session, SessionManager
from nanobot.session.summary import SessionSummary, session_summary_from_metadata

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator
    from nanobot.utils.llm_runtime import LLMRuntime

IdleCompactionCallback = Callable[[str], ContextCompactionCallback | None]


class AutoCompact:
    _RECENT_SUFFIX_MESSAGES = MIN_COMPACTED_REPLAY_MESSAGES
    _INTERNAL_SESSION_PREFIXES = ("dream:",)

    def __init__(
        self,
        sessions: SessionManager,
        consolidator: Consolidator,
        session_ttl_minutes: int = 0,
        bind_compaction: IdleCompactionCallback | None = None,
    ):
        self.sessions = sessions
        self.consolidator = consolidator
        self._ttl = session_ttl_minutes
        self._archiving: set[str] = set()
        self._summaries: dict[str, SessionSummary] = {}
        self._bind_compaction = bind_compaction

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

    @staticmethod
    def _session_has_unarchived_messages(session: Session) -> bool:
        return any(
            not message.get("_command")
            for message in session.messages[session.last_archived:]
        )

    @classmethod
    def _is_internal_session(cls, key: str) -> bool:
        return key.startswith(cls._INTERNAL_SESSION_PREFIXES)

    async def check_expired(
        self,
        schedule_background: Callable[[Coroutine[Any, Any, None]], None],
        resolve_runtime: Callable[[Session], Awaitable[LLMRuntime]],
        active_session_keys: Collection[str] = (),
    ) -> None:
        """Schedule idle archival without blocking the event loop."""
        now = datetime.now()
        active_keys = set(active_session_keys)
        for info in await self.sessions.list_sessions_async():
            key = info.get("key", "")
            if not key or self._is_internal_session(key) or key in self._archiving:
                continue
            if key in active_keys or not self._is_expired(info.get("updated_at"), now):
                continue
            session = await self.sessions.get_or_create_async(key)
            if not self._session_has_unarchived_messages(session):
                continue
            try:
                runtime = await resolve_runtime(session)
            except (KeyError, ValueError):
                continue
            self._archiving.add(key)
            schedule_background(self._archive(key, runtime=runtime))

    async def _archive(self, key: str, *, runtime: LLMRuntime) -> None:
        if self._is_internal_session(key):
            self._archiving.discard(key)
            return
        try:
            # Keep the session live while the synchronous callback binds its route.
            session = await self.sessions.get_or_create_async(key)
            summary = await self.consolidator.compact_idle_session(
                key,
                runtime=runtime,
                max_suffix=self._RECENT_SUFFIX_MESSAGES,
                on_compaction=self._bind_compaction(key) if self._bind_compaction else None,
            )
            if summary and summary != "(nothing)":
                session = await self.sessions.get_or_create_async(key)
                self._record_stored_summary(key, session)
        except Exception:
            logger.exception("Auto-compact: failed for {}", key)
        finally:
            self._archiving.discard(key)

    def _record_stored_summary(self, key: str, session: Session) -> None:
        stored = session_summary_from_metadata(
            session.metadata,
            fallback_last_active=session.updated_at,
        )
        if stored is not None:
            self._summaries[key] = stored

    async def prepare_session(
        self,
        session: Session,
        key: str,
    ) -> tuple[Session, SessionSummary | None]:
        """Prepare a session without blocking on a reload."""
        if self._is_internal_session(key):
            self._archiving.discard(key)
            self._summaries.pop(key, None)
            return session, None
        if key in self._archiving or self._is_expired(session.updated_at):
            logger.info("Auto-compact: reloading session {} (archiving={})", key, key in self._archiving)
            session = await self.sessions.get_or_create_async(key)
        return self._prepared_summary(session, key)

    def _prepared_summary(
        self,
        session: Session,
        key: str,
    ) -> tuple[Session, SessionSummary | None]:
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
