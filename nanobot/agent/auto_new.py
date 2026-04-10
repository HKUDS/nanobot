"""Auto session new: proactive archival of idle sessions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Callable, Coroutine

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator
    from nanobot.session.manager import Session, SessionManager


class AutoSessionNew:
    def __init__(self, sessions: SessionManager, consolidator: Consolidator,
                 session_ttl_minutes: int = 0):
        self.sessions = sessions
        self.consolidator = consolidator
        self._ttl = session_ttl_minutes
        self._archiving: set[str] = set()
        self._summaries: dict[str, str] = {}

    def _is_expired(self, ts: datetime | str | None) -> bool:
        if self._ttl <= 0 or not ts:
            return False
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return (datetime.now() - ts).total_seconds() >= self._ttl * 60

    def check_expired(self, schedule_background: Callable[[Coroutine], None]) -> None:
        for info in self.sessions.list_sessions():
            key = info.get("key", "")
            if key and key not in self._archiving and self._is_expired(info.get("updated_at")):
                self._archiving.add(key)
                logger.info("Auto-new: scheduling archival for {} (idle > {} min)", key, self._ttl)
                schedule_background(self._archive(key))

    async def _archive(self, key: str) -> None:
        try:
            self.sessions.invalidate(key)
            session = self.sessions.get_or_create(key)
            msgs = session.messages[session.last_consolidated:]
            if not msgs:
                logger.debug("Auto-new: skipping {}, no un-consolidated messages", key)
                session.updated_at = datetime.now()
                self.sessions.save(session)
                return
            n = len(msgs)
            idle_min = int((datetime.now() - session.updated_at).total_seconds() / 60)
            await self.consolidator.archive(msgs)
            entry = self.consolidator.store._read_last_entry()
            summary = (entry or {}).get("content", "")
            if summary and summary != "(nothing)":
                self._summaries[key] = (
                    f"Inactive for {idle_min} minutes.\n"
                    f"Previous conversation summary: {summary}"
                )
            session.clear()
            self.sessions.save(session)
            logger.info("Auto-new: archived {} ({} messages, summary={})", key, n, bool(summary))
        except Exception:
            logger.exception("Auto-new: failed for {}", key)
        finally:
            self._archiving.discard(key)

    def prepare_session(self, session: Session, key: str) -> tuple[Session, str | None]:
        if key in self._archiving or self._is_expired(session.updated_at):
            logger.info("Auto-new: reloading session {} (archiving={})", key, key in self._archiving)
            session = self.sessions.get_or_create(key)
        return session, self._summaries.pop(key, None)
