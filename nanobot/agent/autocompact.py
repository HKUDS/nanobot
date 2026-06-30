"""Auto compact: proactive compression of idle sessions to reduce token cost and latency."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Coroutine

from loguru import logger

from nanobot.agent.memory import LAST_COMPACTED_AT_META
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

    @staticmethod
    def _timestamp(ts: datetime | str | None) -> float | None:
        if not ts:
            return None
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                return None
        return ts.timestamp()

    def _is_expired(self, ts: datetime | str | None,
                    now: datetime | None = None) -> bool:
        ts_epoch = self._timestamp(ts)
        if self._ttl <= 0 or ts_epoch is None:
            return False
        now_epoch = self._timestamp(now or datetime.now())
        return now_epoch is not None and now_epoch - ts_epoch >= self._ttl * 60

    def _compacted_after_activity(self, key: str, last_active: datetime | str | None) -> bool:
        metadata_row = self.sessions.read_session_metadata(key)
        metadata = metadata_row.get("metadata") if isinstance(metadata_row, dict) else None
        if not isinstance(metadata, dict):
            return False
        compacted_at = metadata.get(LAST_COMPACTED_AT_META)
        if not isinstance(compacted_at, str):
            return False
        compacted_epoch = self._timestamp(compacted_at)
        active_epoch = self._timestamp(last_active)
        return compacted_epoch is not None and active_epoch is not None and compacted_epoch >= active_epoch

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
            if self._is_expired(updated_at, now) and not self._compacted_after_activity(key, updated_at):
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
