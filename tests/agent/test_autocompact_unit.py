"""Direct unit tests for AutoCompact class methods in isolation."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.autocompact import AutoCompact
from nanobot.session.manager import Session, SessionManager


def _make_session(
    key: str = "cli:test",
    messages: list | None = None,
    last_consolidated: int = 0,
    updated_at: datetime | None = None,
    metadata: dict | None = None,
) -> Session:
    """Create a Session with sensible defaults for testing."""
    session = Session(
        key=key,
        messages=messages or [],
        metadata=metadata or {},
        last_consolidated=last_consolidated,
    )
    if updated_at is not None:
        session.updated_at = updated_at
    return session


def _make_autocompact(
    ttl: int = 15,
    sessions: SessionManager | None = None,
    consolidator: MagicMock | None = None,
) -> AutoCompact:
    """Create an AutoCompact with mock dependencies."""
    if sessions is None:
        sessions = MagicMock(spec=SessionManager)
    if consolidator is None:
        consolidator = MagicMock()
        consolidator.compact_idle_session = AsyncMock(return_value="Summary.")
    return AutoCompact(
        sessions=sessions,
        consolidator=consolidator,
        session_ttl_minutes=ttl,
    )


def _add_turns(session: Session, turns: int, *, prefix: str = "msg") -> None:
    """Append simple user/assistant turns to a session."""
    for i in range(turns):
        session.add_message("user", f"{prefix} user {i}")
        session.add_message("assistant", f"{prefix} assistant {i}")


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    """Test AutoCompact.__init__ stores constructor arguments correctly."""

    def test_stores_ttl(self):
        """_ttl should match session_ttl_minutes argument."""
        ac = _make_autocompact(ttl=30)
        assert ac._ttl == 30

    def test_default_ttl_is_zero(self):
        """Default TTL should be 0."""
        ac = _make_autocompact(ttl=0)
        assert ac._ttl == 0

    def test_archiving_set_is_empty(self):
        """_archiving should start as an empty set."""
        ac = _make_autocompact()
        assert ac._archiving == set()

    def test_summaries_dict_is_empty(self):
        """_summaries should start as an empty dict."""
        ac = _make_autocompact()
        assert ac._summaries == {}

    def test_stores_sessions_reference(self):
        """sessions attribute should reference the passed SessionManager."""
        mock_sm = MagicMock(spec=SessionManager)
        ac = _make_autocompact(sessions=mock_sm)
        assert ac.sessions is mock_sm

    def test_stores_consolidator_reference(self):
        """consolidator attribute should reference the passed Consolidator."""
        mock_c = MagicMock()
        ac = _make_autocompact(consolidator=mock_c)
        assert ac.consolidator is mock_c


# ---------------------------------------------------------------------------
# _is_expired
# ---------------------------------------------------------------------------


class TestIsExpired:
    """Test AutoCompact._is_expired edge cases."""

    def test_ttl_zero_always_false(self):
        """TTL=0 means auto-compact is disabled; always returns False."""
        ac = _make_autocompact(ttl=0)
        old = datetime.now() - timedelta(days=365)
        assert ac._is_expired(old) is False

    def test_none_timestamp_returns_false(self):
        """None timestamp should return False."""
        ac = _make_autocompact(ttl=15)
        assert ac._is_expired(None) is False

    def test_empty_string_timestamp_returns_false(self):
        """Empty string timestamp should return False (falsy)."""
        ac = _make_autocompact(ttl=15)
        assert ac._is_expired("") is False

    def test_exactly_at_boundary_is_expired(self):
        """Timestamp exactly at TTL boundary should be expired (>=)."""
        ac = _make_autocompact(ttl=15)
        now = datetime(2026, 1, 1, 12, 0, 0)
        ts = now - timedelta(minutes=15)
        assert ac._is_expired(ts, now=now) is True

    def test_just_under_boundary_not_expired(self):
        """Timestamp just under TTL boundary should NOT be expired."""
        ac = _make_autocompact(ttl=15)
        now = datetime(2026, 1, 1, 12, 0, 0)
        ts = now - timedelta(minutes=14, seconds=59)
        assert ac._is_expired(ts, now=now) is False

    def test_iso_string_parses_correctly(self):
        """ISO format string timestamp should be parsed and evaluated."""
        ac = _make_autocompact(ttl=15)
        now = datetime(2026, 1, 1, 12, 0, 0)
        ts = (now - timedelta(minutes=20)).isoformat()
        assert ac._is_expired(ts, now=now) is True

    def test_custom_now_parameter(self):
        """Custom 'now' parameter should override datetime.now()."""
        ac = _make_autocompact(ttl=10)
        ts = datetime(2026, 1, 1, 10, 0, 0)
        # 9 minutes later → not expired
        now_under = datetime(2026, 1, 1, 10, 9, 0)
        assert ac._is_expired(ts, now=now_under) is False
        # 10 minutes later → expired
        now_over = datetime(2026, 1, 1, 10, 10, 0)
        assert ac._is_expired(ts, now=now_over) is True


# ---------------------------------------------------------------------------
# session_summary_text (was _format_summary)
# ---------------------------------------------------------------------------


class TestSessionSummaryText:
    """Test session_summary_text for legacy _last_summary format compatibility."""

    def test_legacy_dict_format_contains_timestamp(self):
        """session_summary_text with legacy _last_summary dict should include isoformat."""
        from nanobot.agent.memory import session_summary_text

        session = _make_session(metadata={
            "_last_summary": {
                "text": "Some text",
                "last_active": "2026-05-13T14:30:00",
            },
        })
        result = session_summary_text(session)
        assert result is not None
        assert "2026-05-13T14:30:00" in result

    def test_legacy_dict_format_contains_summary_text(self):
        """session_summary_text should contain the provided text verbatim."""
        from nanobot.agent.memory import session_summary_text

        session = _make_session(metadata={
            "_last_summary": {
                "text": "User discussed Python.",
                "last_active": "2026-01-01T00:00:00",
            },
        })
        result = session_summary_text(session)
        assert result is not None
        assert "User discussed Python." in result

    def test_legacy_dict_format_starts_with_label(self):
        """session_summary_text with legacy _last_summary dict should start with prefix."""
        from nanobot.agent.memory import session_summary_text

        session = _make_session(metadata={
            "_last_summary": {"text": "text", "last_active": "2026-01-01T00:00:00"},
        })
        result = session_summary_text(session)
        assert result is not None
        assert result.startswith("Previous conversation summary (last active ")


# ---------------------------------------------------------------------------
# check_expired
# ---------------------------------------------------------------------------


class TestCheckExpired:
    """Test AutoCompact.check_expired scheduling logic."""

    def test_empty_sessions_list(self):
        """No sessions → schedule_background should never be called."""
        ac = _make_autocompact(ttl=15)
        mock_sm = MagicMock(spec=SessionManager)
        mock_sm.list_sessions.return_value = []
        ac.sessions = mock_sm
        scheduler = MagicMock()
        ac.check_expired(scheduler)
        scheduler.assert_not_called()

    def test_expired_session_schedules_background(self):
        """Expired session should trigger schedule_background."""
        ac = _make_autocompact(ttl=15)
        mock_sm = MagicMock(spec=SessionManager)
        old_ts = (datetime.now() - timedelta(minutes=20)).isoformat()
        mock_sm.list_sessions.return_value = [{"key": "cli:old", "updated_at": old_ts}]
        ac.sessions = mock_sm

        scheduled = []

        def scheduler(coro):
            scheduled.append(coro)
            coro.close()

        ac.check_expired(scheduler)
        assert len(scheduled) == 1
        assert "cli:old" in ac._archiving

    def test_active_session_key_skips(self):
        """Session in active_session_keys should be skipped."""
        ac = _make_autocompact(ttl=15)
        mock_sm = MagicMock(spec=SessionManager)
        old_ts = (datetime.now() - timedelta(minutes=20)).isoformat()
        mock_sm.list_sessions.return_value = [{"key": "cli:busy", "updated_at": old_ts}]
        ac.sessions = mock_sm
        scheduler = MagicMock()
        ac.check_expired(scheduler, active_session_keys={"cli:busy"})
        scheduler.assert_not_called()

    def test_session_already_in_archiving_skips(self):
        """Session already in _archiving set should be skipped."""
        ac = _make_autocompact(ttl=15)
        mock_sm = MagicMock(spec=SessionManager)
        old_ts = (datetime.now() - timedelta(minutes=20)).isoformat()
        mock_sm.list_sessions.return_value = [{"key": "cli:dup", "updated_at": old_ts}]
        ac.sessions = mock_sm
        ac._archiving.add("cli:dup")
        scheduler = MagicMock()
        ac.check_expired(scheduler)
        scheduler.assert_not_called()

    def test_session_with_no_key_skips(self):
        """Session info with empty/missing key should be skipped."""
        ac = _make_autocompact(ttl=15)
        mock_sm = MagicMock(spec=SessionManager)
        mock_sm.list_sessions.return_value = [{"key": "", "updated_at": "old"}]
        ac.sessions = mock_sm
        scheduler = MagicMock()
        ac.check_expired(scheduler)
        scheduler.assert_not_called()

    def test_session_with_missing_key_field_skips(self):
        """Session info dict without 'key' field should be skipped."""
        ac = _make_autocompact(ttl=15)
        mock_sm = MagicMock(spec=SessionManager)
        mock_sm.list_sessions.return_value = [{"updated_at": "old"}]
        ac.sessions = mock_sm
        scheduler = MagicMock()
        ac.check_expired(scheduler)
        scheduler.assert_not_called()

    def test_dream_key_is_now_archived_normally(self):
        """Dream sessions are no longer internal; they should be scheduled like any session."""
        ac = _make_autocompact(ttl=15)
        mock_sm = MagicMock(spec=SessionManager)
        old_ts = (datetime.now() - timedelta(minutes=20)).isoformat()
        mock_sm.list_sessions.return_value = [
            {"key": "dream:20260602-155256", "updated_at": old_ts},
        ]
        ac.sessions = mock_sm
        scheduler = MagicMock()

        ac.check_expired(scheduler)

        scheduler.assert_called_once()


# ---------------------------------------------------------------------------
# _archive
# ---------------------------------------------------------------------------


class TestArchiveDelegates:
    """_archive should delegate all session mutation to Consolidator."""

    @pytest.mark.asyncio
    async def test_calls_compact_idle_session(self):
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        ac.sessions = mock_sm
        ac.consolidator.compact_idle_session = AsyncMock(return_value="Summary.")

        await ac._archive("cli:test")

        ac.consolidator.compact_idle_session.assert_awaited_once_with(
            "cli:test", ac._RECENT_SUFFIX_MESSAGES,
        )

    @pytest.mark.asyncio
    async def test_dream_key_is_archived_normally(self):
        """Dream sessions are no longer special-cased; they archive like any session."""
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        session = _make_session()
        mock_sm.get_or_create.return_value = session
        ac.sessions = mock_sm
        ac.consolidator.compact_idle_session = AsyncMock(return_value="Summary.")
        ac._archiving.add("dream:20260602-155256")

        await ac._archive("dream:20260602-155256")

        ac.consolidator.compact_idle_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_populates_summaries_from_metadata(self):
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        session = _make_session(
            metadata={"_last_summary": {"text": "Hello.", "last_active": "2026-05-13T10:00:00"}}
        )
        mock_sm.get_or_create.return_value = session
        ac.sessions = mock_sm
        ac.consolidator.compact_idle_session = AsyncMock(return_value="Hello.")

        await ac._archive("cli:test")

        entry = ac._summaries.get("cli:test")
        assert entry is not None
        assert "Hello." in entry

    @pytest.mark.asyncio
    async def test_no_summary_when_compact_returns_empty(self):
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        ac.sessions = mock_sm
        ac.consolidator.compact_idle_session = AsyncMock(return_value="")

        await ac._archive("cli:test")

        assert "cli:test" not in ac._summaries

    @pytest.mark.asyncio
    async def test_no_summary_when_compact_returns_nothing(self):
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        ac.sessions = mock_sm
        ac.consolidator.compact_idle_session = AsyncMock(return_value="(nothing)")

        await ac._archive("cli:test")

        assert "cli:test" not in ac._summaries

    @pytest.mark.asyncio
    async def test_exception_still_removes_from_archiving(self):
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        ac.sessions = mock_sm
        ac.consolidator.compact_idle_session = AsyncMock(side_effect=RuntimeError("fail"))

        ac._archiving.add("cli:test")
        await ac._archive("cli:test")

        assert "cli:test" not in ac._archiving


# ---------------------------------------------------------------------------
# prepare_session
# ---------------------------------------------------------------------------


class TestPrepareSession:
    """Test AutoCompact.prepare_session logic."""

    def test_key_in_archiving_reloads_session(self):
        """If key is in _archiving, session should be reloaded via get_or_create."""
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        reloaded = _make_session(key="cli:test")
        mock_sm.get_or_create.return_value = reloaded
        ac.sessions = mock_sm
        ac._archiving.add("cli:test")

        original_session = _make_session()
        result_session, summary = ac.prepare_session(original_session, "cli:test")

        mock_sm.get_or_create.assert_called_once_with("cli:test")
        assert result_session is reloaded

    def test_expired_session_reloads(self):
        """If session is expired, it should be reloaded via get_or_create."""
        ac = _make_autocompact(ttl=15)
        mock_sm = MagicMock(spec=SessionManager)
        reloaded = _make_session(key="cli:test", updated_at=datetime.now())
        mock_sm.get_or_create.return_value = reloaded
        ac.sessions = mock_sm

        old_session = _make_session(updated_at=datetime.now() - timedelta(minutes=20))
        result_session, summary = ac.prepare_session(old_session, "cli:test")

        mock_sm.get_or_create.assert_called_once_with("cli:test")
        assert result_session is reloaded

    def test_hot_path_summary_from_summaries(self):
        """Summary from _summaries dict should be returned (hot path)."""
        ac = _make_autocompact()
        session = _make_session()
        ac._summaries["cli:test"] = "Hot summary (pre-rendered)."

        result_session, summary = ac.prepare_session(session, "cli:test")

        assert result_session is session
        assert summary is not None
        assert "Hot summary" in summary

    def test_hot_path_pops_summary_one_shot(self):
        """Hot path should pop the summary (one-shot; second call returns None)."""
        ac = _make_autocompact()
        session = _make_session()
        last_active = datetime(2026, 1, 1)
        ac._summaries["cli:test"] = ("One-shot.", last_active)

        _, summary1 = ac.prepare_session(session, "cli:test")
        assert summary1 is not None
        # Second call: hot path entry was popped
        _, summary2 = ac.prepare_session(session, "cli:test")
        assert summary2 is None

    def test_cold_path_summary_from_metadata(self):
        """When _summaries is empty, summary should come from metadata (cold path)."""
        ac = _make_autocompact()
        last_active = datetime(2026, 5, 13, 14, 0, 0)
        session = _make_session(metadata={
            "_last_summary": {
                "text": "Cold summary.",
                "last_active": last_active.isoformat(),
            },
        })

        result_session, summary = ac.prepare_session(session, "cli:test")

        assert result_session is session
        assert summary is not None
        assert "Cold summary." in summary

    def test_no_summary_available_returns_none(self):
        """When no summary is available, should return (session, None)."""
        ac = _make_autocompact()
        session = _make_session()

        result_session, summary = ac.prepare_session(session, "cli:test")

        assert result_session is session
        assert summary is None

    def test_dream_key_is_not_special_in_prepare(self):
        """Dream sessions are no longer internal; prepare_session treats them normally."""
        ac = _make_autocompact(ttl=15)
        mock_sm = MagicMock(spec=SessionManager)
        ac.sessions = mock_sm
        key = "dream:20260602-155256"
        ac._archiving.add(key)
        ac._summaries[key] = "Hot summary."
        session = _make_session(
            key=key,
            updated_at=datetime.now() - timedelta(minutes=20),
            metadata={
                "_last_summary": {
                    "text": "Cold summary.",
                    "last_active": "2026-06-02T15:52:56",
                },
            },
        )

        result_session, summary = ac.prepare_session(session, key)

        # Dream sessions now reload when expired, just like any other session
        mock_sm.get_or_create.assert_called_once_with(key)

    def test_cold_path_legacy_string_metadata(self):
        """If metadata _last_summary is a plain string, session_summary_text returns it as-is."""
        ac = _make_autocompact()
        session = _make_session(metadata={"_last_summary": "legacy plain string summary"})

        result_session, summary = ac.prepare_session(session, "cli:test")

        assert result_session is session
        assert "legacy plain string summary" in summary

    def test_hot_path_takes_priority_over_metadata(self):
        """Hot path (_summaries) should take priority over metadata."""
        ac = _make_autocompact()
        session = _make_session(metadata={
            "_last_summary": {
                "text": "Cold summary.",
                "last_active": datetime(2026, 1, 1).isoformat(),
            },
        })
        ac._summaries["cli:test"] = "Hot summary."

        _, summary = ac.prepare_session(session, "cli:test")
        assert "Hot summary." in summary
        # After hot path pops, cold path would kick in on next call
