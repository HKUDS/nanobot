"""Auto compact: proactive compression of idle sessions to reduce token cost and latency."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator


class AutoCompact:
    _RECENT_SUFFIX_MESSAGES = 8
    _LAST_SUMMARY_KEY = "_last_summary"
    _RESUME_SUMMARY_KEY = "_resume_summary"

    def __init__(self, sessions: SessionManager, consolidator: Consolidator,
                 session_ttl_minutes: int = 0):
        self.sessions = sessions
        self.consolidator = consolidator
        self._ttl = session_ttl_minutes
        self._archiving: set[str] = set()
        self._summaries: dict[str, tuple[str, datetime]] = {}
        self._resume_summaries: dict[str, str] = {}

    def _is_expired(self, ts: datetime | str | None,
                    now: datetime | None = None) -> bool:
        if self._ttl <= 0 or not ts:
            return False
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return ((now or datetime.now()) - ts).total_seconds() >= self._ttl * 60

    @staticmethod
    def _format_summary(text: str, last_active: datetime) -> str:
        idle_min = int((datetime.now() - last_active).total_seconds() / 60)
        return f"Inactive for {idle_min} minutes.\nPrevious conversation summary: {text}"

    @staticmethod
    def _format_resume_summary(text: str) -> str:
        return f"Previous task was stopped before completion.\nInterrupted task summary: {text}"

    def _split_unconsolidated(
        self, session: Session,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split live session tail into archiveable prefix and retained recent suffix."""
        tail = list(session.messages[session.last_consolidated:])
        if not tail:
            return [], []

        probe = Session(
            key=session.key,
            messages=tail.copy(),
            created_at=session.created_at,
            updated_at=session.updated_at,
            metadata={},
            last_consolidated=0,
        )
        probe.retain_recent_legal_suffix(self._RECENT_SUFFIX_MESSAGES)
        kept = probe.messages
        cut = len(tail) - len(kept)
        return tail[:cut], kept

    def check_expired(self, schedule_background: Callable[[Coroutine], None],
                      active_session_keys: Collection[str] = ()) -> None:
        """Schedule archival for idle sessions, skipping those with in-flight agent tasks."""
        now = datetime.now()
        for info in self.sessions.list_sessions():
            key = info.get("key", "")
            if not key or key in self._archiving:
                continue
            if key in active_session_keys:
                continue
            if self._is_expired(info.get("updated_at"), now):
                self._archiving.add(key)
                schedule_background(self._archive(key))

    async def _archive(self, key: str) -> None:
        try:
            self.sessions.invalidate(key)
            session = self.sessions.get_or_create(key)
            archive_msgs, kept_msgs = self._split_unconsolidated(session)
            if not archive_msgs and not kept_msgs:
                session.updated_at = datetime.now()
                self.sessions.save(session)
                return

            last_active = session.updated_at
            summary = ""
            if archive_msgs:
                summary = await self.consolidator.archive(archive_msgs) or ""
            if summary and summary != "(nothing)":
                self._summaries[key] = (summary, last_active)
                session.metadata[self._LAST_SUMMARY_KEY] = {
                    "text": summary,
                    "last_active": last_active.isoformat(),
                }
            session.messages = kept_msgs
            session.last_consolidated = 0
            session.updated_at = datetime.now()
            self.sessions.save(session)
            if archive_msgs:
                logger.info(
                    "Auto-compact: archived {} (archived={}, kept={}, summary={})",
                    key,
                    len(archive_msgs),
                    len(kept_msgs),
                    bool(summary),
                )
        except Exception:
            logger.exception("Auto-compact: failed for {}", key)
        finally:
            self._archiving.discard(key)

    def stash_resume_summary(self, session: Session, key: str, summary: str) -> None:
        """Persist a one-shot interrupted-task summary for the next turn."""
        text = summary.strip()
        if not text or text == "(nothing)":
            return
        self._resume_summaries[key] = text
        session.metadata[self._RESUME_SUMMARY_KEY] = {"text": text}

    def _consume_resume_summary(self, session: Session, key: str) -> str | None:
        text = self._resume_summaries.pop(key, None)
        if text:
            session.metadata.pop(self._RESUME_SUMMARY_KEY, None)
            return self._format_resume_summary(text)
        if self._RESUME_SUMMARY_KEY not in session.metadata:
            return None
        meta = session.metadata.pop(self._RESUME_SUMMARY_KEY)
        self.sessions.save(session)
        return self._format_resume_summary(meta["text"])

    def _consume_idle_summary(self, session: Session, key: str) -> str | None:
        # Hot path: summary from in-memory dict (process hasn't restarted).
        # Also clean metadata copy so stale summary never leaks to disk.
        entry = self._summaries.pop(key, None)
        if entry:
            session.metadata.pop(self._LAST_SUMMARY_KEY, None)
            return self._format_summary(entry[0], entry[1])
        if self._LAST_SUMMARY_KEY not in session.metadata:
            return None
        meta = session.metadata.pop(self._LAST_SUMMARY_KEY)
        self.sessions.save(session)
        return self._format_summary(meta["text"], datetime.fromisoformat(meta["last_active"]))

    def prepare_session(self, session: Session, key: str) -> tuple[Session, str | None]:
        if key in self._archiving or self._is_expired(session.updated_at):
            logger.info("Auto-compact: reloading session {} (archiving={})", key, key in self._archiving)
            session = self.sessions.get_or_create(key)
        summaries = [
            text
            for text in (
                self._consume_resume_summary(session, key),
                self._consume_idle_summary(session, key),
            )
            if text
        ]
        return session, "\n\n".join(summaries) if summaries else None
