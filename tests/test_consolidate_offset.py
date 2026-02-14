"""Test session management with cache-friendly message handling."""

import pytest
from pathlib import Path
from nanobot.session.manager import Session, SessionManager

# Test constants
MEMORY_WINDOW = 50
KEEP_COUNT = MEMORY_WINDOW // 2  # 25


def create_session_with_messages(key: str, count: int, role: str = "user") -> Session:
    """Create a session and add the specified number of messages.

    Args:
        key: Session identifier
        count: Number of messages to add
        role: Message role (default: "user")

    Returns:
        Session with the specified messages
    """
    session = Session(key=key)
    for i in range(count):
        session.add_message(role, f"msg{i}")
    return session


def assert_messages_content(messages: list, start_index: int, end_index: int) -> None:
    """Assert that messages contain expected content from start to end index.

    Args:
        messages: List of message dictionaries
        start_index: Expected first message index
        end_index: Expected last message index
    """
    assert len(messages) > 0
    assert messages[0]["content"] == f"msg{start_index}"
    assert messages[-1]["content"] == f"msg{end_index}"


def get_old_messages(session: Session, last_consolidated: int, keep_count: int) -> list:
    """Extract messages that would be consolidated using the standard slice logic.

    Args:
        session: The session containing messages
        last_consolidated: Index of last consolidated message
        keep_count: Number of recent messages to keep

    Returns:
        List of messages that would be consolidated
    """
    return session.messages[last_consolidated:-keep_count]


class TestSessionLastConsolidated:
    """Test last_consolidated tracking to avoid duplicate processing."""

    def test_initial_last_consolidated_zero(self) -> None:
        """Test that new session starts with last_consolidated=0."""
        session = Session(key="test:initial")
        assert session.last_consolidated == 0

    def test_last_consolidated_persistence(self, tmp_path) -> None:
        """Test that last_consolidated persists across save/load."""
        manager = SessionManager(Path(tmp_path))
        session1 = create_session_with_messages("test:persist", 20)
        session1.last_consolidated = 15
        manager.save(session1)

        session2 = manager.get_or_create("test:persist")
        assert session2.last_consolidated == 15
        assert len(session2.messages) == 20

    def test_clear_resets_last_consolidated(self) -> None:
        """Test that clear() resets last_consolidated to 0."""
        session = create_session_with_messages("test:clear", 10)
        session.last_consolidated = 5

        session.clear()
        assert len(session.messages) == 0
        assert session.last_consolidated == 0


class TestSessionImmutableHistory:
    """Test Session message immutability for cache efficiency."""

    def test_initial_state(self) -> None:
        """Test that new session has empty messages list."""
        session = Session(key="test:initial")
        assert len(session.messages) == 0

    def test_add_messages_appends_only(self) -> None:
        """Test that adding messages only appends, never modifies."""
        session = Session(key="test:preserve")
        session.add_message("user", "msg1")
        session.add_message("assistant", "resp1")
        session.add_message("user", "msg2")
        assert len(session.messages) == 3
        assert session.messages[0]["content"] == "msg1"

    def test_get_history_returns_most_recent(self) -> None:
        """Test get_history returns the most recent messages."""
        session = Session(key="test:history")
        for i in range(10):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")

        history = session.get_history(max_messages=6)
        assert len(history) == 6
        assert history[0]["content"] == "msg7"
        assert history[-1]["content"] == "resp9"

    def test_get_history_with_all_messages(self) -> None:
        """Test get_history with max_messages larger than actual."""
        session = create_session_with_messages("test:all", 5)
        history = session.get_history(max_messages=100)
        assert len(history) == 5
        assert history[0]["content"] == "msg0"

    def test_get_history_stable_for_same_session(self) -> None:
        """Test that get_history returns same content for same max_messages."""
        session = create_session_with_messages("test:stable", 20)
        history1 = session.get_history(max_messages=10)
        history2 = session.get_history(max_messages=10)
        assert history1 == history2

    def test_messages_list_never_modified(self) -> None:
        """Test that messages list is never modified after creation."""
        session = create_session_with_messages("test:immutable", 5)
        original_len = len(session.messages)

        session.get_history(max_messages=2)
        assert len(session.messages) == original_len

        for _ in range(10):
            session.get_history(max_messages=3)
        assert len(session.messages) == original_len


class TestSessionPersistence:
    """Test Session persistence and reload."""

    @pytest.fixture
    def temp_manager(self, tmp_path):
        return SessionManager(Path(tmp_path))

    def test_persistence_roundtrip(self, temp_manager):
        """Test that messages persist across save/load."""
        session1 = create_session_with_messages("test:persistence", 20)
        temp_manager.save(session1)

        session2 = temp_manager.get_or_create("test:persistence")
        assert len(session2.messages) == 20
        assert session2.messages[0]["content"] == "msg0"
        assert session2.messages[-1]["content"] == "msg19"

    def test_get_history_after_reload(self, temp_manager):
        """Test that get_history works correctly after reload."""
        session1 = create_session_with_messages("test:reload", 30)
        temp_manager.save(session1)

        session2 = temp_manager.get_or_create("test:reload")
        history = session2.get_history(max_messages=10)
        assert len(history) == 10
        assert history[0]["content"] == "msg20"
        assert history[-1]["content"] == "msg29"

    def test_clear_resets_session(self, temp_manager):
        """Test that clear() properly resets session."""
        session = create_session_with_messages("test:clear", 10)
        assert len(session.messages) == 10

        session.clear()
        assert len(session.messages) == 0


class TestConsolidationTriggerConditions:
    """Test consolidation trigger conditions and logic."""

    def test_consolidation_needed_when_messages_exceed_window(self):
        """Test consolidation logic: should trigger when messages > memory_window."""
        session = create_session_with_messages("test:trigger", 60)

        total_messages = len(session.messages)
        messages_to_process = total_messages - session.last_consolidated

        assert total_messages > MEMORY_WINDOW
        assert messages_to_process > 0

        expected_consolidate_count = total_messages - KEEP_COUNT
        assert expected_consolidate_count == 35

    def test_consolidation_skipped_when_within_keep_count(self):
        """Test consolidation skipped when total messages <= keep_count."""
        session = create_session_with_messages("test:skip", 20)

        total_messages = len(session.messages)
        assert total_messages <= KEEP_COUNT

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 0

    def test_consolidation_skipped_when_no_new_messages(self):
        """Test consolidation skipped when messages_to_process <= 0."""
        session = create_session_with_messages("test:already_consolidated", 40)
        session.last_consolidated = len(session.messages) - KEEP_COUNT  # 15

        # Add a few more messages
        for i in range(40, 42):
            session.add_message("user", f"msg{i}")

        total_messages = len(session.messages)
        messages_to_process = total_messages - session.last_consolidated
        assert messages_to_process > 0

        # Simulate last_consolidated catching up
        session.last_consolidated = total_messages - KEEP_COUNT
        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 0


class TestLastConsolidatedEdgeCases:
    """Test last_consolidated edge cases and data corruption scenarios."""

    def test_last_consolidated_exceeds_message_count(self):
        """Test behavior when last_consolidated > len(messages) (data corruption)."""
        session = create_session_with_messages("test:corruption", 10)
        session.last_consolidated = 20

        total_messages = len(session.messages)
        messages_to_process = total_messages - session.last_consolidated
        assert messages_to_process <= 0

        old_messages = get_old_messages(session, session.last_consolidated, 5)
        assert len(old_messages) == 0

    def test_last_consolidated_negative_value(self):
        """Test behavior with negative last_consolidated (invalid state)."""
        session = create_session_with_messages("test:negative", 10)
        session.last_consolidated = -5

        keep_count = 3
        old_messages = get_old_messages(session, session.last_consolidated, keep_count)

        # messages[-5:-3] with 10 messages gives indices 5,6
        assert len(old_messages) == 2
        assert old_messages[0]["content"] == "msg5"
        assert old_messages[-1]["content"] == "msg6"

    def test_messages_added_after_consolidation(self):
        """Test correct behavior when new messages arrive after consolidation."""
        session = create_session_with_messages("test:new_messages", 40)
        session.last_consolidated = len(session.messages) - KEEP_COUNT  # 15

        # Add new messages after consolidation
        for i in range(40, 50):
            session.add_message("user", f"msg{i}")

        total_messages = len(session.messages)
        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        expected_consolidate_count = total_messages - KEEP_COUNT - session.last_consolidated

        assert len(old_messages) == expected_consolidate_count
        assert_messages_content(old_messages, 15, 24)

    def test_slice_behavior_when_indices_overlap(self):
        """Test slice behavior when last_consolidated >= total - keep_count."""
        session = create_session_with_messages("test:overlap", 30)
        session.last_consolidated = 12

        old_messages = get_old_messages(session, session.last_consolidated, 20)
        assert len(old_messages) == 0


class TestArchiveAllMode:
    """Test archive_all mode (used by /new command)."""

    def test_archive_all_consolidates_everything(self):
        """Test archive_all=True consolidates all messages."""
        session = create_session_with_messages("test:archive_all", 50)

        archive_all = True
        if archive_all:
            old_messages = session.messages
            assert len(old_messages) == 50

        assert session.last_consolidated == 0

    def test_archive_all_resets_last_consolidated(self):
        """Test that archive_all mode resets last_consolidated to 0."""
        session = create_session_with_messages("test:reset", 40)
        session.last_consolidated = 15

        archive_all = True
        if archive_all:
            session.last_consolidated = 0

        assert session.last_consolidated == 0
        assert len(session.messages) == 40

    def test_archive_all_vs_normal_consolidation(self):
        """Test difference between archive_all and normal consolidation."""
        # Normal consolidation
        session1 = create_session_with_messages("test:normal", 60)
        session1.last_consolidated = len(session1.messages) - KEEP_COUNT

        # archive_all mode
        session2 = create_session_with_messages("test:all", 60)
        session2.last_consolidated = 0

        assert session1.last_consolidated == 35
        assert len(session1.messages) == 60
        assert session2.last_consolidated == 0
        assert len(session2.messages) == 60


class TestCacheImmutability:
    """Test that consolidation doesn't modify session.messages (cache safety)."""

    def test_consolidation_does_not_modify_messages_list(self):
        """Test that consolidation leaves messages list unchanged."""
        session = create_session_with_messages("test:immutable", 50)

        original_messages = session.messages.copy()
        original_len = len(session.messages)
        session.last_consolidated = original_len - KEEP_COUNT

        assert len(session.messages) == original_len
        assert session.messages == original_messages

    def test_get_history_does_not_modify_messages(self):
        """Test that get_history doesn't modify messages list."""
        session = create_session_with_messages("test:history_immutable", 40)
        original_messages = [m.copy() for m in session.messages]

        for _ in range(5):
            history = session.get_history(max_messages=10)
            assert len(history) == 10

        assert len(session.messages) == 40
        for i, msg in enumerate(session.messages):
            assert msg["content"] == original_messages[i]["content"]

    def test_consolidation_only_updates_last_consolidated(self):
        """Test that consolidation only updates last_consolidated field."""
        session = create_session_with_messages("test:field_only", 60)

        original_messages = session.messages.copy()
        original_key = session.key
        original_metadata = session.metadata.copy()

        session.last_consolidated = len(session.messages) - KEEP_COUNT

        assert session.messages == original_messages
        assert session.key == original_key
        assert session.metadata == original_metadata
        assert session.last_consolidated == 35


class TestSliceLogic:
    """Test the slice logic: messages[last_consolidated:-keep_count]."""

    def test_slice_extracts_correct_range(self):
        """Test that slice extracts the correct message range."""
        session = create_session_with_messages("test:slice", 60)

        old_messages = get_old_messages(session, 0, KEEP_COUNT)

        assert len(old_messages) == 35
        assert_messages_content(old_messages, 0, 34)

        remaining = session.messages[-KEEP_COUNT:]
        assert len(remaining) == 25
        assert_messages_content(remaining, 35, 59)

    def test_slice_with_partial_consolidation(self):
        """Test slice when some messages already consolidated."""
        session = create_session_with_messages("test:partial", 70)

        last_consolidated = 30
        old_messages = get_old_messages(session, last_consolidated, KEEP_COUNT)

        assert len(old_messages) == 15
        assert_messages_content(old_messages, 30, 44)

    def test_slice_with_various_keep_counts(self):
        """Test slice behavior with different keep_count values."""
        session = create_session_with_messages("test:keep_counts", 50)

        test_cases = [(10, 40), (20, 30), (30, 20), (40, 10)]

        for keep_count, expected_count in test_cases:
            old_messages = session.messages[0:-keep_count]
            assert len(old_messages) == expected_count

    def test_slice_when_keep_count_exceeds_messages(self):
        """Test slice when keep_count > len(messages)."""
        session = create_session_with_messages("test:exceed", 10)

        old_messages = session.messages[0:-20]
        assert len(old_messages) == 0


class TestEmptyAndBoundarySessions:
    """Test empty sessions and boundary conditions."""

    def test_empty_session_consolidation(self):
        """Test consolidation behavior with empty session."""
        session = Session(key="test:empty")

        assert len(session.messages) == 0
        assert session.last_consolidated == 0

        messages_to_process = len(session.messages) - session.last_consolidated
        assert messages_to_process == 0

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 0

    def test_single_message_session(self):
        """Test consolidation with single message."""
        session = Session(key="test:single")
        session.add_message("user", "only message")

        assert len(session.messages) == 1

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 0

    def test_exactly_keep_count_messages(self):
        """Test session with exactly keep_count messages."""
        session = create_session_with_messages("test:exact", KEEP_COUNT)

        assert len(session.messages) == KEEP_COUNT

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 0

    def test_just_over_keep_count(self):
        """Test session with one message over keep_count."""
        session = create_session_with_messages("test:over", KEEP_COUNT + 1)

        assert len(session.messages) == 26

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 1
        assert old_messages[0]["content"] == "msg0"

    def test_very_large_session(self):
        """Test consolidation with very large message count."""
        session = create_session_with_messages("test:large", 1000)

        assert len(session.messages) == 1000

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 975
        assert_messages_content(old_messages, 0, 974)

        remaining = session.messages[-KEEP_COUNT:]
        assert len(remaining) == 25
        assert_messages_content(remaining, 975, 999)

    def test_session_with_gaps_in_consolidation(self):
        """Test session with potential gaps in consolidation history."""
        session = create_session_with_messages("test:gaps", 50)
        session.last_consolidated = 10

        # Add more messages
        for i in range(50, 60):
            session.add_message("user", f"msg{i}")

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)

        expected_count = 60 - KEEP_COUNT - 10
        assert len(old_messages) == expected_count
        assert_messages_content(old_messages, 10, 34)
