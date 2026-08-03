"""Auto compact: proactive compression of idle sessions to reduce token cost and latency."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Coroutine, cast

from loguru import logger

from nanobot.agent.memory import DREAM_TAIL_SESSION_KEY_PREFIX, Consolidator
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.utils.llm_runtime import LLMRuntime


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

    def _has_compactable_idle_tail(self, key: str) -> bool:
        session = self.sessions.get_or_create(key)
        # Must use Consolidator.archive_start, or a session whose only unarchived
        # content is already dream-tail-archived would silently skip both paths.
        start = Consolidator.archive_start(session)
        tail = list(session.messages[start:])
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
        result = probe.retain_recent_legal_suffix(
            self._RECENT_SUFFIX_MESSAGES,
            extend_to_user=True,
        )
        messages_to_remove = result.dropped[result.already_consolidated_count:]
        return bool(messages_to_remove)

    # -- Dream-only tail archive for short idle sessions (#3973) --------------------
    # Sessions that never exceed the retained recent-suffix window never reach the
    # real archive path below, so history.jsonl stays empty and Dream has nothing
    # to process. This path writes a raw copy for Dream without touching the live
    # prompt. Every real archive boundary (Consolidator.archive_start, used across
    # this file and memory.py, plus Session.enforce_file_cap's trim path) starts
    # from `max(last_consolidated, dream_tail_marker)`, so none of them ever
    # re-cover a range this path already archived.

    def _needs_dream_tail_archive(self, key: str) -> bool:
        session = self.sessions.get_or_create(key)
        if not session.messages:
            return False
        # Gate on last_consolidated == 0: without it, any session that already
        # compacted once would have its whole protected recent suffix raw-dumped
        # into Dream on the next idle tick, even with no new messages — far
        # wider than this fix's actual scope.
        if session.last_consolidated != 0:
            return False
        # Must match _dream_tail_archive's own boundary below.
        start = Consolidator.archive_start(session)
        return start < len(session.messages)

    async def _dream_tail_archive(self, key: str) -> None:
        if self._is_internal_session(key):
            self._archiving.discard(key)
            return
        try:
            lock = self.consolidator.get_lock(key)
            async with lock:
                session = self.sessions.get_or_create(key)
                if session.last_consolidated != 0:
                    # Re-check under the lock: the scan and this task aren't
                    # atomic, so a real archive could have advanced
                    # last_consolidated in between. No mutation happened, so
                    # don't save().
                    return
                start = Consolidator.archive_start(session)
                new_messages = session.messages[start:]
                if (
                    len(new_messages) > self._RECENT_SUFFIX_MESSAGES
                    and self._has_compactable_idle_tail(key)
                ):
                    # Defer to the real archive path only if it's actually viable
                    # now — a raw message count alone isn't reliable proof (see
                    # TestDreamTailArchiveUnanswerableTailDoesNotStarve).
                    return
                if not new_messages:
                    # Nothing changed — avoid an unnecessary sessions.save().
                    return
                # raw_archive() already strips runtime-context suffixes and caps at
                # 16k, same as every other raw-dump path; a batch exceeding that
                # cap still advances the marker, permanently losing the excess
                # (see TestDreamTailArchiveTruncationStillAdvancesMarker).
                #
                # session_key uses a distinct prefix so this entry doesn't also
                # surface via "# Recent History" on a resumed turn. Dream itself
                # reads history.jsonl by cursor, not session_key, so it's unaffected.
                self.consolidator.store.raw_archive(
                    new_messages,
                    session_key=f"{DREAM_TAIL_SESSION_KEY_PREFIX}{key}",
                    degraded=False,
                )
                # Records the range just archived, not len(session.messages) at
                # write time — session.messages isn't lock-protected against
                # concurrent turn processing, so a message appended mid-write
                # would otherwise be silently treated as already archived.
                session.metadata[Consolidator.DREAM_TAIL_MARKER_KEY] = start + len(new_messages)
                self.sessions.save(session)
        except Exception:
            logger.exception("Dream tail archive: failed for {}", key)
        finally:
            self._archiving.discard(key)

    @staticmethod
    def _format_summary(text: str, last_active: datetime) -> str:
        return f"Previous conversation summary (last active {last_active.isoformat()}):\n{text}"

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
            if not self._is_expired(updated_at, now):
                continue
            if self._has_compactable_idle_tail(key):
                session = self.sessions.get_or_create(key)
                try:
                    runtime = resolve_runtime(session)
                except (KeyError, ValueError):
                    # Invalid session selections remain recoverable through /model.
                    # Deliberately does NOT fall back to the dream-tail path here:
                    # this session already qualified for real (LLM-summarized)
                    # archiving, and letting the raw-dump tail path claim it first
                    # would advance its marker past all its messages, permanently
                    # downgrading it to a raw dump — even after the model config
                    # is fixed and it would otherwise get a proper summary.
                    continue
                self._archiving.add(key)
                schedule_background(self._archive(key, runtime=runtime))
            elif self._needs_dream_tail_archive(key):
                self._archiving.add(key)
                schedule_background(self._dream_tail_archive(key))

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
                session = self.sessions.get_or_create(key)
                meta = session.metadata.get("_last_summary")
                if isinstance(meta, dict):
                    self._summaries[key] = (
                        cast(str, meta["text"]),
                        datetime.fromisoformat(cast(str, meta["last_active"])),
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
        # Persisted metadata may outlive schema changes; a malformed summary must
        # not abort turn preparation.
        meta = session.metadata.get("_last_summary")
        if isinstance(meta, dict):
            summary_meta = cast(dict[str, object], meta)
            text = summary_meta.get("text")
            if isinstance(text, str) and text:
                raw_last_active = summary_meta.get("last_active")
                try:
                    last_active = (
                        datetime.fromisoformat(raw_last_active)
                        if isinstance(raw_last_active, str)
                        else session.updated_at
                    )
                except ValueError:
                    last_active = session.updated_at
                return session, self._format_summary(text, last_active)
        return session, None
