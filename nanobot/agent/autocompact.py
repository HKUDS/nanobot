"""Auto compact: proactive compression of idle sessions to reduce token cost and latency."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Coroutine

from loguru import logger

from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator


class AutoCompact:
    _RECENT_SUFFIX_MESSAGES = 8
    _INTERNAL_SESSION_PREFIXES = ("dream:",)

    def __init__(self, sessions: SessionManager, consolidator: Consolidator,
                 session_ttl_minutes: int = 0):
        self.sessions = sessions
        self.consolidator = consolidator
        self._ttl = session_ttl_minutes
        self._archiving: set[str] = set()
        self._summaries: dict[str, tuple[str, datetime]] = {}

    def _is_expired(self, ts: datetime | str | None,
                    now: datetime | None = None) -> bool:
        if self._ttl <= 0 or not ts:
            return False
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return ((now or datetime.now()) - ts).total_seconds() >= self._ttl * 60

    def _has_compactable_idle_tail(self, key: str) -> bool:
        session = self.sessions.get_or_create(key)
        tail = list(session.messages[session.last_consolidated:])
        if not tail:
            return False
        probe = Session(
            key=session.key,
            messages=tail,
            created_at=session.created_at,
            updated_at=session.updated_at,
            metadata={},
            last_consolidated=0,
        )
        result = probe.plan_recent_legal_suffix(
            self._RECENT_SUFFIX_MESSAGES,
            extend_to_user=True,
        )
        messages_to_remove = result.dropped[result.already_consolidated_count:]
        return bool(messages_to_remove)

    @staticmethod
    def _format_summary(text: str, last_active: datetime) -> str:
        return f"Previous conversation summary (last active {last_active.isoformat()}):\n{text}"

    @classmethod
    def _is_internal_session(cls, key: str) -> bool:
        return key.startswith(cls._INTERNAL_SESSION_PREFIXES)

    def check_expired(self, schedule_background: Callable[[Coroutine], None],
                      active_session_keys: Collection[str] = ()) -> None:
        """Schedule archival for idle sessions, skipping those with in-flight agent tasks."""
        now = datetime.now()
        for info in self.sessions.list_sessions():
            key = info.get("key", "")
            if not key or self._is_internal_session(key) or key in self._archiving:
                continue
            if key in active_session_keys:
                continue
            updated_at = info.get("updated_at")
            if self._is_expired(updated_at, now) and self._has_compactable_idle_tail(key):
                self._archiving.add(key)
                schedule_background(self._archive(key))

    async def _archive(self, key: str) -> None:
        if self._is_internal_session(key):
            self._archiving.discard(key)
            return
        try:
            summary = await self.consolidator.compact_idle_session(
                key, self._RECENT_SUFFIX_MESSAGES,
            )
            if summary and summary != "(nothing)":
                session = self.sessions.get_or_create(key)
                meta = session.metadata.get("_last_summary")
                if isinstance(meta, dict):
                    self._summaries[key] = (
                        meta["text"],
                        datetime.fromisoformat(meta["last_active"]),
                    )
        except Exception:
            logger.exception("Auto-compact: failed for {}", key)
        finally:
            self._archiving.discard(key)

    def prepare_session(self, session: Session, key: str) -> tuple[Session, str | None]:
        if self._is_internal_session(key):
            self._archiving.discard(key)
            self._summaries.pop(key, None)
            return session, None
        if key in self._archiving or self._is_expired(session.updated_at):
            logger.info("Auto-compact: reloading session {} (archiving={})", key, key in self._archiving)
            session = self.sessions.get_or_create(key)
        # Hot path: summary from in-memory dict (process hasn't restarted).
        entry = self._summaries.pop(key, None)
        if entry:
            return session, self._format_summary(entry[0], entry[1])
        # Cold path: summary persisted in session metadata (process restarted).
        meta = session.metadata.get("_last_summary")
        if isinstance(meta, dict):
            return session, self._format_summary(meta["text"], datetime.fromisoformat(meta["last_active"]))
        return session, None
