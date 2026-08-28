"""Auto compact: proactive compression of idle sessions to reduce token cost and latency."""

from __future__ import annotations

from collections.abc import Awaitable, Collection
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

from nanobot.session.async_compat import call_session_manager
from nanobot.session.manager import MIN_COMPACTED_REPLAY_MESSAGES, Session, SessionManager
from nanobot.session.summary import SessionSummary, session_summary_from_metadata

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator
    from nanobot.utils.llm_runtime import LLMRuntime


class AutoCompact:
    _RECENT_SUFFIX_MESSAGES = MIN_COMPACTED_REPLAY_MESSAGES
    _INTERNAL_SESSION_PREFIXES = ("dream:",)

    def __init__(self, sessions: SessionManager, consolidator: Consolidator,
                 session_ttl_minutes: int = 0):
        self.sessions = sessions
        self.consolidator = consolidator
        self._ttl = session_ttl_minutes
        self._archiving: set[str] = set()
        self._summaries: dict[str, SessionSummary] = {}

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

    def _has_unarchived_messages(self, key: str) -> bool:
        return self._session_has_unarchived_messages(self.sessions.get_or_create(key))

    @staticmethod
    def _session_has_unarchived_messages(session: Session) -> bool:
        return session.last_archived < len(session.messages)

    async def _get_or_create_nonblocking(self, key: str) -> Session:
        return await call_session_manager(
            self.sessions,
            "get_or_create_async",
            self.sessions.get_or_create,
            key,
        )

    async def _list_sessions_nonblocking(self) -> list[dict[str, Any]]:
        return await call_session_manager(
            self.sessions,
            "list_sessions_async",
            self.sessions.list_sessions,
        )

    @classmethod
    def _is_internal_session(cls, key: str) -> bool:
        return key.startswith(cls._INTERNAL_SESSION_PREFIXES)

    def check_expired(
        self,
        schedule_background: Callable[[Coroutine[Any, Any, None]], None],
        resolve_runtime: Callable[[Session], LLMRuntime],
        active_session_keys: Collection[str] = (),
    ) -> None:
        """Schedule archival for idle sessions, skipping those with in-flight agent tasks."""
        now = datetime.now()
        for info in self.sessions.list_sessions():
            key = info.get("key", "")
            if not key or self._is_internal_session(key) or key in self._archiving:
                continue
            if key in active_session_keys:
                continue
            updated_at = info.get("updated_at")
            if self._is_expired(updated_at, now) and self._has_unarchived_messages(key):
                session = self.sessions.get_or_create(key)
                try:
                    runtime = resolve_runtime(session)
                except (KeyError, ValueError):
                    # Invalid session selections remain recoverable through /model.
                    continue
                self._archiving.add(key)
                schedule_background(self._archive(key, runtime=runtime))

    async def check_expired_async(
        self,
        schedule_background: Callable[[Coroutine[Any, Any, None]], None],
        resolve_runtime: Callable[[Session], Awaitable[LLMRuntime]],
        active_session_keys: Collection[str] = (),
    ) -> None:
        """Schedule idle archival without blocking the event loop."""
        now = datetime.now()
        active_keys = set(active_session_keys)
        for info in await self._list_sessions_nonblocking():
            key = info.get("key", "")
            if not key or self._is_internal_session(key) or key in self._archiving:
                continue
            if key in active_keys or not self._is_expired(info.get("updated_at"), now):
                continue
            session = await self._get_or_create_nonblocking(key)
            if not self._session_has_unarchived_messages(session):
                continue
            try:
                runtime = await resolve_runtime(session)
            except (KeyError, ValueError):
                continue
            self._archiving.add(key)
            schedule_background(self._archive_async(key, runtime=runtime))

    async def _archive(self, key: str, *, runtime: LLMRuntime) -> None:
        if self._is_internal_session(key):
            self._archiving.discard(key)
            return
        try:
            summary = await self.consolidator.compact_idle_session(
                key,
                runtime=runtime,
                max_suffix=self._RECENT_SUFFIX_MESSAGES,
            )
            if summary and summary != "(nothing)":
                self._record_stored_summary(key, self.sessions.get_or_create(key))
        except Exception:
            logger.exception("Auto-compact: failed for {}", key)
        finally:
            self._archiving.discard(key)

    async def _archive_async(self, key: str, *, runtime: LLMRuntime) -> None:
        if self._is_internal_session(key):
            self._archiving.discard(key)
            return
        try:
            summary = await self.consolidator.compact_idle_session(
                key,
                runtime=runtime,
                max_suffix=self._RECENT_SUFFIX_MESSAGES,
            )
            if summary and summary != "(nothing)":
                session = await self._get_or_create_nonblocking(key)
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

    def prepare_session(self, session: Session, key: str) -> tuple[Session, SessionSummary | None]:
        if self._is_internal_session(key):
            self._archiving.discard(key)
            self._summaries.pop(key, None)
            return session, None
        if key in self._archiving or self._is_expired(session.updated_at):
            logger.info("Auto-compact: reloading session {} (archiving={})", key, key in self._archiving)
            session = self.sessions.get_or_create(key)
        return self._prepared_summary(session, key)

    async def prepare_session_async(
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
            session = await self._get_or_create_nonblocking(key)
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
