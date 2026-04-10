"""Auto compact: proactive compression of idle sessions to reduce token cost and latency."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Callable, Coroutine

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator
    from nanobot.session.manager import Session, SessionManager


class AutoCompact:
    def __init__(self, sessions: SessionManager, consolidator: Consolidator,
                 session_ttl_minutes: int = 0):
        self.sessions = sessions
        self.consolidator = consolidator
        self._ttl = session_ttl_minutes
        self._archiving: set[str] = set()
        self._summaries: dict[str, tuple[str, datetime]] = {}

    def _is_expired(self, ts: datetime | str | None) -> bool:
        if self._ttl <= 0 or not ts:
            return False
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return (datetime.now() - ts).total_seconds() >= self._ttl * 60

    @staticmethod
    def _format_summary(text: str, last_active: datetime) -> str:
        idle_min = int((datetime.now() - last_active).total_seconds() / 60)
        return f"Inactive for {idle_min} minutes.\nPrevious conversation summary: {text}"

    def check_expired(self, schedule_background: Callable[[Coroutine], None]) -> None:
        for info in self.sessions.list_sessions():
            key = info.get("key", "")
            if key and key not in self._archiving and self._is_expired(info.get("updated_at")):
                self._archiving.add(key)
                logger.debug("Auto-compact: scheduling archival for {} (idle > {} min)", key, self._ttl)
                schedule_background(self._archive(key))

    async def _archive(self, key: str) -> None:
        try:
            self.sessions.invalidate(key)
            session = self.sessions.get_or_create(key)
            msgs = session.messages[session.last_consolidated:]
            if not msgs:
                logger.debug("Auto-compact: skipping {}, no un-consolidated messages", key)
                session.updated_at = datetime.now()
                self.sessions.save(session)
                return
            n = len(msgs)
            last_active = session.updated_at
            await self.consolidator.archive(msgs)
            entry = self.consolidator.get_last_history_entry()
            summary = (entry or {}).get("content", "")
            if summary and summary != "(nothing)":
                self._summaries[key] = (summary, last_active)
                session.metadata["_last_summary"] = {"text": summary, "last_active": last_active.isoformat()}
            session.clear()
            self.sessions.save(session)
            logger.info("Auto-compact: archived {} ({} messages, summary={})", key, n, bool(summary))
        except Exception:
            logger.exception("Auto-compact: failed for {}", key)
        finally:
            self._archiving.discard(key)

    def prepare_session(self, session: Session, key: str) -> tuple[Session, str | None]:
        if key in self._archiving or self._is_expired(session.updated_at):
            logger.info("Auto-compact: reloading session {} (archiving={})", key, key in self._archiving)
            session = self.sessions.get_or_create(key)
        entry = self._summaries.pop(key, None)
        if entry:
            session.metadata.pop("_last_summary", None)
            return session, self._format_summary(entry[0], entry[1])
        if not session.messages and "_last_summary" in session.metadata:
            meta = session.metadata.pop("_last_summary")
            self.sessions.save(session)
            return session, self._format_summary(meta["text"], datetime.fromisoformat(meta["last_active"]))
        return session, None
