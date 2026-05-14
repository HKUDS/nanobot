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
        consolidator.archive = AsyncMock(return_value="Summary.")
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
# _format_summary
# ---------------------------------------------------------------------------


class TestFormatSummary:
    """Test AutoCompact._format_summary static method."""

    def test_contains_isoformat_timestamp(self):
        """Output should contain last_active as isoformat."""
        last_active = datetime(2026, 5, 13, 14, 30, 0)
        result = AutoCompact._format_summary("Some text", last_active)
        assert "2026-05-13T14:30:00" in result

    def test_contains_summary_text(self):
        """Output should contain the provided text verbatim."""
        last_active = datetime(2026, 1, 1)
        result = AutoCompact._format_summary("User discussed Python.", last_active)
        assert "User discussed Python." in result

    def test_output_starts_with_label(self):
        """Output should start with the standard prefix."""
        last_active = datetime(2026, 1, 1)
        result = AutoCompact._format_summary("text", last_active)
        assert result.startswith("Previous conversation summary (last active ")


# ---------------------------------------------------------------------------
# _split_unconsolidated
# ---------------------------------------------------------------------------


class TestSplitUnconsolidated:
    """Test AutoCompact._split_unconsolidated splitting logic."""

    def test_empty_session_returns_both_empty(self):
        """Empty session should return ([], [])."""
        ac = _make_autocompact()
        session = _make_session(messages=[])
        archive, kept = ac._split_unconsolidated(session)
        assert archive == []
        assert kept == []

    def test_all_messages_archivable_when_more_than_suffix(self):
        """Session with many messages should archive a prefix and keep suffix."""
        ac = _make_autocompact()
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(20)]
        session = _make_session(messages=msgs)
        archive, kept = ac._split_unconsolidated(session)
        assert len(archive) > 0
        assert len(kept) <= AutoCompact._RECENT_SUFFIX_MESSAGES

    def test_fewer_messages_than_suffix_returns_empty_archive(self):
        """Session with fewer messages than suffix should have empty archive."""
        ac = _make_autocompact()
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(3)]
        session = _make_session(messages=msgs)
        archive, kept = ac._split_unconsolidated(session)
        assert archive == []
        assert len(kept) == len(msgs)

    def test_respects_last_consolidated_offset(self):
        """Only messages after last_consolidated should be considered."""
        ac = _make_autocompact()
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(20)]
        # First 10 are already consolidated
        session = _make_session(messages=msgs, last_consolidated=10)
        archive, kept = ac._split_unconsolidated(session)
        # Only the tail of 10 messages is considered for splitting
        assert all(m["content"] in [f"u{i}" for i in range(10, 20)] for m in kept)
        assert all(m["content"] in [f"u{i}" for i in range(10, 20)] for m in archive)

    def test_retain_recent_legal_suffix_keeps_last_n(self):
        """The kept suffix should be at most _RECENT_SUFFIX_MESSAGES long."""
        ac = _make_autocompact()
        # 20 user messages = 20 messages total, all after last_consolidated=0
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(20)]
        session = _make_session(messages=msgs)
        archive, kept = ac._split_unconsolidated(session)
        assert len(kept) <= AutoCompact._RECENT_SUFFIX_MESSAGES
        assert len(archive) == len(msgs) - len(kept)


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
        scheduler = MagicMock()
        ac.check_expired(scheduler)
        scheduler.assert_called_once()
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


# ---------------------------------------------------------------------------
# _archive
# ---------------------------------------------------------------------------


class TestArchive:
    """Test AutoCompact._archive async method."""

    @pytest.mark.asyncio
    async def test_empty_session_updates_timestamp_no_archive_call(self):
        """Empty session should refresh updated_at and not call consolidator.archive."""
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        empty_session = _make_session(messages=[])
        mock_sm.get_or_create.return_value = empty_session
        ac.sessions = mock_sm
        ac.consolidator.archive = AsyncMock(return_value="Summary.")

        await ac._archive("cli:test")

        ac.consolidator.archive.assert_not_called()
        mock_sm.save.assert_called_once_with(empty_session)
        # updated_at was refreshed
        assert empty_session.updated_at > datetime.now() - timedelta(seconds=5)

    @pytest.mark.asyncio
    async def test_archive_returns_empty_string_no_summary_stored(self):
        """If archive returns empty string, no summary should be stored."""
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(20)]
        session = _make_session(messages=msgs)
        mock_sm.get_or_create.return_value = session
        ac.sessions = mock_sm
        ac.consolidator.archive = AsyncMock(return_value="")

        await ac._archive("cli:test")

        assert "cli:test" not in ac._summaries

    @pytest.mark.asyncio
    async def test_archive_returns_nothing_no_summary_stored(self):
        """If archive returns '(nothing)', no summary should be stored."""
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(20)]
        session = _make_session(messages=msgs)
        mock_sm.get_or_create.return_value = session
        ac.sessions = mock_sm
        ac.consolidator.archive = AsyncMock(return_value="(nothing)")

        await ac._archive("cli:test")

        assert "cli:test" not in ac._summaries

    @pytest.mark.asyncio
    async def test_archive_exception_caught_key_removed_from_archiving(self):
        """If archive raises, exception is caught and key removed from _archiving."""
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(20)]
        session = _make_session(messages=msgs)
        mock_sm.get_or_create.return_value = session
        ac.sessions = mock_sm
        ac.consolidator.archive = AsyncMock(side_effect=RuntimeError("LLM down"))

        # Should not raise
        await ac._archive("cli:test")

        assert "cli:test" not in ac._archiving

    @pytest.mark.asyncio
    async def test_successful_archive_stores_summary_in_summaries_and_metadata(self):
        """Successful archive should store summary in _summaries dict and metadata."""
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(20)]
        last_active = datetime(2026, 5, 13, 10, 0, 0)
        session = _make_session(messages=msgs, updated_at=last_active)
        mock_sm.get_or_create.return_value = session
        ac.sessions = mock_sm
        ac.consolidator.archive = AsyncMock(return_value="User discussed AI.")

        await ac._archive("cli:test")

        # _summaries
        entry = ac._summaries.get("cli:test")
        assert entry is not None
        assert entry[0] == "User discussed AI."
        assert entry[1] == last_active
        # metadata
        meta = session.metadata.get("_last_summary")
        assert meta is not None
        assert meta["text"] == "User discussed AI."
        assert "last_active" in meta

    @pytest.mark.asyncio
    async def test_finally_block_always_removes_from_archiving(self):
        """Finally block should always remove key from _archiving, even on error."""
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(20)]
        session = _make_session(messages=msgs)
        mock_sm.get_or_create.return_value = session
        ac.sessions = mock_sm
        ac.consolidator.archive = AsyncMock(side_effect=RuntimeError("fail"))

        # Pre-add key to archiving to verify it gets removed
        ac._archiving.add("cli:test")
        await ac._archive("cli:test")
        assert "cli:test" not in ac._archiving

    @pytest.mark.asyncio
    async def test_finally_removes_from_archiving_on_success(self):
        """Finally block should remove key from _archiving on success too."""
        ac = _make_autocompact()
        mock_sm = MagicMock(spec=SessionManager)
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(20)]
        session = _make_session(messages=msgs)
        mock_sm.get_or_create.return_value = session
        ac.sessions = mock_sm
        ac.consolidator.archive = AsyncMock(return_value="Summary.")

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
        last_active = datetime(2026, 5, 13, 14, 0, 0)
        ac._summaries["cli:test"] = ("Hot summary.", last_active)

        result_session, summary = ac.prepare_session(session, "cli:test")

        assert result_session is session
        assert summary is not None
        assert "Hot summary." in summary
        assert "Previous conversation summary" in summary

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

    def test_cold_path_metadata_not_dict_returns_none(self):
        """If metadata _last_summary is not a dict, should return None summary."""
        ac = _make_autocompact()
        session = _make_session(metadata={"_last_summary": "not a dict"})

        result_session, summary = ac.prepare_session(session, "cli:test")

        assert result_session is session
        assert summary is None

    def test_hot_path_takes_priority_over_metadata(self):
        """Hot path (_summaries) should take priority over metadata."""
        ac = _make_autocompact()
        session = _make_session(metadata={
            "_last_summary": {
                "text": "Cold summary.",
                "last_active": datetime(2026, 1, 1).isoformat(),
            },
        })
        last_active = datetime(2026, 5, 13, 14, 0, 0)
        ac._summaries["cli:test"] = ("Hot summary.", last_active)

        _, summary = ac.prepare_session(session, "cli:test")
        assert "Hot summary." in summary
        # After hot path pops, cold path would kick in on next call
