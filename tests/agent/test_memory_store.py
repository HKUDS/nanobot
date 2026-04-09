"""Tests for the restructured MemoryStore — pure file I/O layer."""

from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.memory import MemoryStore


def _make_isolation_config(enabled=True, channels=None):
    """Build a lightweight stand-in for IsolationConfig."""
    return SimpleNamespace(enbaled=enabled, channels=channels or [])


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


@pytest.fixture
def isolated_store(tmp_path):
    """MemoryStore with isolation enabled for the 'dingtalk' channel."""
    config = _make_isolation_config(enabled=True, channels=["dingtalk"])
    return MemoryStore(tmp_path, isolation_config=config)

class TestMemoryStoreBasicIO:
    def test_read_memory_returns_empty_when_missing(self, store):
        assert store.read_memory() == ""

    def test_write_and_read_memory(self, store):
        store.write_memory("hello")
        assert store.read_memory() == "hello"

    def test_read_soul_returns_empty_when_missing(self, store):
        assert store.read_soul() == ""

    def test_write_and_read_soul(self, store):
        store.write_soul("soul content")
        assert store.read_soul() == "soul content"

    def test_read_user_returns_empty_when_missing(self, store):
        assert store.read_user() == ""

    def test_write_and_read_user(self, store):
        store.write_user("user content")
        assert store.read_user() == "user content"

    def test_get_memory_context_returns_empty_when_missing(self, store):
        assert store.get_memory_context() == ""

    def test_get_memory_context_returns_formatted_content(self, store):
        store.write_memory("important fact")
        ctx = store.get_memory_context()
        assert "Long-term Memory" in ctx
        assert "important fact" in ctx


class TestHistoryWithCursor:
    def test_append_history_returns_cursor(self, store):
        cursor = store.append_history("event 1")
        assert cursor == 1
        cursor2 = store.append_history("event 2")
        assert cursor2 == 2

    def test_append_history_includes_cursor_in_file(self, store):
        store.append_history("event 1")
        content = store.read_file(store.history_file)
        data = json.loads(content)
        assert data["cursor"] == 1

    def test_cursor_persists_across_appends(self, store):
        store.append_history("event 1")
        store.append_history("event 2")
        cursor = store.append_history("event 3")
        assert cursor == 3

    def test_read_unprocessed_history(self, store):
        store.append_history("event 1")
        store.append_history("event 2")
        store.append_history("event 3")
        entries = store.read_unprocessed_history(since_cursor=1)
        assert len(entries) == 2
        assert entries[0]["cursor"] == 2

    def test_read_unprocessed_history_returns_all_when_cursor_zero(self, store):
        store.append_history("event 1")
        store.append_history("event 2")
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 2

    def test_compact_history_drops_oldest(self, tmp_path):
        store = MemoryStore(tmp_path, max_history_entries=2)
        store.append_history("event 1")
        store.append_history("event 2")
        store.append_history("event 3")
        store.append_history("event 4")
        store.append_history("event 5")
        store.compact_history()
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 2
        assert entries[0]["cursor"] in {4, 5}


class TestDreamCursor:
    def test_initial_cursor_is_zero(self, store):
        assert store.get_last_dream_cursor() == 0

    def test_set_and_get_cursor(self, store):
        store.set_last_dream_cursor(5)
        assert store.get_last_dream_cursor() == 5

    def test_cursor_persists(self, store):
        store.set_last_dream_cursor(3)
        store2 = MemoryStore(store.workspace)
        assert store2.get_last_dream_cursor() == 3


class TestLegacyHistoryMigration:
    def test_read_unprocessed_history_handles_entries_without_cursor(self, store):
        """JSONL entries with cursor=1 are correctly parsed and returned."""
        store.history_file.write_text(
            '{"cursor": 1, "timestamp": "2026-03-30 14:30", "content": "Old event"}\n',
            encoding="utf-8")
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["cursor"] == 1

    def test_migrates_legacy_history_md_preserving_partial_entries(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        legacy_file = memory_dir / "HISTORY.md"
        legacy_content = (
            "[2026-04-01 10:00] User prefers dark mode.\n\n"
            "[2026-04-01 10:05] [RAW] 2 messages\n"
            "[2026-04-01 10:04] USER: hello\n"
            "[2026-04-01 10:04] ASSISTANT: hi\n\n"
            "Legacy chunk without timestamp.\n"
            "Keep whatever content we can recover.\n"
        )
        legacy_file.write_text(legacy_content, encoding="utf-8")

        store = MemoryStore(tmp_path)
        fallback_timestamp = datetime.fromtimestamp(
            (memory_dir / "HISTORY.md.bak").stat().st_mtime,
        ).strftime("%Y-%m-%d %H:%M")

        entries = store.read_unprocessed_history(since_cursor=0)
        assert [entry["cursor"] for entry in entries] == [1, 2, 3]
        assert entries[0]["timestamp"] == "2026-04-01 10:00"
        assert entries[0]["content"] == "User prefers dark mode."
        assert entries[1]["timestamp"] == "2026-04-01 10:05"
        assert entries[1]["content"].startswith("[RAW] 2 messages")
        assert "USER: hello" in entries[1]["content"]
        assert entries[2]["timestamp"] == fallback_timestamp
        assert entries[2]["content"].startswith("Legacy chunk without timestamp.")
        assert store.read_file(store._cursor_file).strip() == "3"
        assert store.read_file(store._dream_cursor_file).strip() == "3"
        assert not legacy_file.exists()
        assert (memory_dir / "HISTORY.md.bak").read_text(encoding="utf-8") == legacy_content

    def test_migrates_consecutive_entries_without_blank_lines(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        legacy_file = memory_dir / "HISTORY.md"
        legacy_content = (
            "[2026-04-01 10:00] First event.\n"
            "[2026-04-01 10:01] Second event.\n"
            "[2026-04-01 10:02] Third event.\n"
        )
        legacy_file.write_text(legacy_content, encoding="utf-8")

        store = MemoryStore(tmp_path)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 3
        assert [entry["content"] for entry in entries] == [
            "First event.",
            "Second event.",
            "Third event.",
        ]

    def test_raw_archive_stays_single_entry_while_following_events_split(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        legacy_file = memory_dir / "HISTORY.md"
        legacy_content = (
            "[2026-04-01 10:05] [RAW] 2 messages\n"
            "[2026-04-01 10:04] USER: hello\n"
            "[2026-04-01 10:04] ASSISTANT: hi\n"
            "[2026-04-01 10:06] Normal event after raw block.\n"
        )
        legacy_file.write_text(legacy_content, encoding="utf-8")

        store = MemoryStore(tmp_path)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 2
        assert entries[0]["content"].startswith("[RAW] 2 messages")
        assert "USER: hello" in entries[0]["content"]
        assert entries[1]["content"] == "Normal event after raw block."

    def test_nonstandard_date_headers_still_start_new_entries(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        legacy_file = memory_dir / "HISTORY.md"
        legacy_content = (
            "[2026-03-25–2026-04-02] Multi-day summary.\n"
            "[2026-03-26/27] Cross-day summary.\n"
        )
        legacy_file.write_text(legacy_content, encoding="utf-8")

        store = MemoryStore(tmp_path)
        fallback_timestamp = datetime.fromtimestamp(
            (memory_dir / "HISTORY.md.bak").stat().st_mtime,
        ).strftime("%Y-%m-%d %H:%M")

        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 2
        assert entries[0]["timestamp"] == fallback_timestamp
        assert entries[0]["content"] == "[2026-03-25–2026-04-02] Multi-day summary."
        assert entries[1]["timestamp"] == fallback_timestamp
        assert entries[1]["content"] == "[2026-03-26/27] Cross-day summary."

    def test_existing_history_jsonl_skips_legacy_migration(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        history_file = memory_dir / "history.jsonl"
        history_file.write_text(
            '{"cursor": 7, "timestamp": "2026-04-01 12:00", "content": "existing"}\n',
            encoding="utf-8",
        )
        legacy_file = memory_dir / "HISTORY.md"
        legacy_file.write_text("[2026-04-01 10:00] legacy\n\n", encoding="utf-8")

        store = MemoryStore(tmp_path)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["cursor"] == 7
        assert entries[0]["content"] == "existing"
        assert legacy_file.exists()
        assert not (memory_dir / "HISTORY.md.bak").exists()

    def test_empty_history_jsonl_still_allows_legacy_migration(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        history_file = memory_dir / "history.jsonl"
        history_file.write_text("", encoding="utf-8")
        legacy_file = memory_dir / "HISTORY.md"
        legacy_file.write_text("[2026-04-01 10:00] legacy\n\n", encoding="utf-8")

        store = MemoryStore(tmp_path)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["cursor"] == 1
        assert entries[0]["timestamp"] == "2026-04-01 10:00"
        assert entries[0]["content"] == "legacy"
        assert not legacy_file.exists()
        assert (memory_dir / "HISTORY.md.bak").exists()

    def test_migrates_legacy_history_with_invalid_utf8_bytes(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        legacy_file = memory_dir / "HISTORY.md"
        legacy_file.write_bytes(
            b"[2026-04-01 10:00] Broken \xff data still needs migration.\n\n"
        )

        store = MemoryStore(tmp_path)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["timestamp"] == "2026-04-01 10:00"
        assert "Broken" in entries[0]["content"]
        assert "migration." in entries[0]["content"]


class TestIsolationSlotReadWrite:
    """Tests for _isolation_slots — per-channel isolated read/write operations."""

    def test_read_memory_without_isolation_returns_root(self, store):
        store.write_memory("root memory")
        assert store.read_memory(channel="dingtalk", session_key="dingtalk_123") == "root memory"

    def test_read_memory_with_isolation_returns_slot_content(self, isolated_store):
        isolated_store.write_memory("root memory")
        slot = isolated_store.get_isolation_slot("dingtalk_123")
        slot.write_memory("slot memory")
        result = isolated_store.read_memory(channel="dingtalk", session_key="dingtalk_123")
        assert result == "slot memory"

    def test_read_memory_isolated_returns_empty_when_slot_has_no_file(self, isolated_store):
        isolated_store.write_memory("root memory")
        result = isolated_store.read_memory(channel="dingtalk", session_key="dingtalk_999")
        assert result == ""

    def test_read_soul_without_isolation_returns_root(self, store):
        store.write_soul("root soul")
        assert store.read_soul(channel="dingtalk", session_key="dingtalk_123") == "root soul"

    def test_read_soul_with_isolation_returns_slot_content(self, isolated_store):
        isolated_store.write_soul("root soul")
        slot = isolated_store.get_isolation_slot("dingtalk_123")
        slot.write_soul("slot soul")
        result = isolated_store.read_soul(channel="dingtalk", session_key="dingtalk_123")
        assert result == "slot soul"

    def test_read_user_without_isolation_returns_root(self, store):
        store.write_user("root user")
        assert store.read_user(channel="dingtalk", session_key="dingtalk_123") == "root user"

    def test_read_user_with_isolation_returns_slot_content(self, isolated_store):
        isolated_store.write_user("root user")
        slot = isolated_store.get_isolation_slot("dingtalk_123")
        slot.write_user("slot user")
        result = isolated_store.read_user(channel="dingtalk", session_key="dingtalk_123")
        assert result == "slot user"

    def test_get_memory_context_with_isolation(self, isolated_store):
        slot = isolated_store.get_isolation_slot("dingtalk_123")
        slot.write_memory("isolated fact")
        ctx = isolated_store.get_memory_context(channel="dingtalk", session_key="dingtalk_123")
        assert "Long-term Memory" in ctx
        assert "isolated fact" in ctx

    def test_get_memory_context_isolated_returns_empty_when_slot_empty(self, isolated_store):
        isolated_store.write_memory("root fact")
        ctx = isolated_store.get_memory_context(channel="dingtalk", session_key="dingtalk_new")
        assert ctx == ""

    def test_append_history_with_isolation(self, isolated_store):
        cursor = isolated_store.append_history("event A", channel="dingtalk", session_key="dingtalk_123")
        assert cursor == 1
        root_entries = isolated_store.read_unprocessed_history(since_cursor=0)
        assert len(root_entries) == 0
        slot_entries = isolated_store.read_unprocessed_history(
            since_cursor=0, channel="dingtalk", session_key="dingtalk_123",
        )
        assert len(slot_entries) == 1
        assert slot_entries[0]["content"] == "event A"

    def test_append_history_without_isolation_goes_to_root(self, store):
        cursor = store.append_history("root event", channel="dingtalk", session_key="dingtalk_123")
        assert cursor == 1
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["content"] == "root event"

    def test_read_unprocessed_history_with_isolation(self, isolated_store):
        isolated_store.append_history("e1", channel="dingtalk", session_key="dingtalk_123")
        isolated_store.append_history("e2", channel="dingtalk", session_key="dingtalk_123")
        isolated_store.append_history("e3", channel="dingtalk", session_key="dingtalk_123")
        entries = isolated_store.read_unprocessed_history(
            since_cursor=1, channel="dingtalk", session_key="dingtalk_123",
        )
        assert len(entries) == 2
        assert entries[0]["cursor"] == 2

    def test_get_last_dream_cursor_with_isolation(self, isolated_store):
        cursor = isolated_store.get_last_dream_cursor(channel="dingtalk", session_key="dingtalk_123")
        assert cursor == 0

    def test_non_isolated_channel_falls_back_to_root(self, isolated_store):
        """A channel not listed in isolation_config.channels reads from root."""
        isolated_store.write_memory("root memory")
        result = isolated_store.read_memory(channel="telegram", session_key="telegram_456")
        assert result == "root memory"

    def test_disabled_isolation_config_falls_back_to_root(self, tmp_path):
        config = _make_isolation_config(enabled=False, channels=["dingtalk"])
        store = MemoryStore(tmp_path, isolation_config=config)
        store.write_memory("root memory")
        result = store.read_memory(channel="dingtalk", session_key="dingtalk_123")
        assert result == "root memory"

    def test_none_channel_falls_back_to_root(self, isolated_store):
        isolated_store.write_memory("root memory")
        result = isolated_store.read_memory(channel=None, session_key="dingtalk_123")
        assert result == "root memory"


class TestIsolationSlotManagement:
    """Tests for slot creation, retrieval, and scanning."""

    def test_get_isolation_slot_creates_new_slot(self, isolated_store):
        slot = isolated_store.get_isolation_slot("dingtalk_123")
        assert isinstance(slot, MemoryStore)
        assert slot.workspace.name == "dingtalk_123"

    def test_get_isolation_slot_returns_same_instance(self, isolated_store):
        slot_a = isolated_store.get_isolation_slot("dingtalk_123")
        slot_b = isolated_store.get_isolation_slot("dingtalk_123")
        assert slot_a is slot_b

    def test_get_isolation_slots_returns_all(self, isolated_store):
        isolated_store.get_isolation_slot("dingtalk_111")
        isolated_store.get_isolation_slot("dingtalk_222")
        slots = isolated_store.get_isolation_slots()
        assert len(slots) == 2

    def test_scan_isolation_slots_picks_up_existing_dirs(self, tmp_path):
        slot_dir = tmp_path / "dingtalk_123"
        slot_dir.mkdir()
        (slot_dir / "memory").mkdir()
        config = _make_isolation_config(enabled=True, channels=["dingtalk"])
        store = MemoryStore(tmp_path, isolation_config=config)
        assert "dingtalk:123" in store._isolation_slots

    def test_scan_ignores_non_matching_dirs(self, tmp_path):
        (tmp_path / "random_dir").mkdir()
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "no-underscore").mkdir()
        config = _make_isolation_config(enabled=True, channels=["dingtalk"])
        store = MemoryStore(tmp_path, isolation_config=config)
        assert len(store._isolation_slots) == 0

    def test_scan_ignores_memory_dir(self, tmp_path):
        (tmp_path / "memory").mkdir(exist_ok=True)
        config = _make_isolation_config(enabled=True, channels=["dingtalk"])
        store = MemoryStore(tmp_path, isolation_config=config)
        assert "memory" not in store._isolation_slots

    def test_multiple_channels_isolate_independently(self, tmp_path):
        config = _make_isolation_config(enabled=True, channels=["dingtalk", "telegram"])
        store = MemoryStore(tmp_path, isolation_config=config)
        slot_dt = store.get_isolation_slot("dingtalk_100")
        slot_tg = store.get_isolation_slot("telegram_200")
        slot_dt.write_memory("dt memory")
        slot_tg.write_memory("tg memory")
        assert store.read_memory(channel="dingtalk", session_key="dingtalk_100") == "dt memory"
        assert store.read_memory(channel="telegram", session_key="telegram_200") == "tg memory"

    def test_isolated_history_cursors_are_independent(self, tmp_path):
        config = _make_isolation_config(enabled=True, channels=["dingtalk", "telegram"])
        store = MemoryStore(tmp_path, isolation_config=config)
        cursor_dt = store.append_history("dt event", channel="dingtalk", session_key="dingtalk_100")
        cursor_tg = store.append_history("tg event", channel="telegram", session_key="telegram_200")
        assert cursor_dt == 1
        assert cursor_tg == 1

    def test_scan_parses_session_keys_correctly_from_valid_dirs(self, tmp_path):
        """Valid slot directories produce correctly formatted session keys (channel:id)."""
        valid_dirs = ["dingtalk_123", "telegram_456", "slack_789", "wechat_001"]
        for name in valid_dirs:
            slot_dir = tmp_path / name
            slot_dir.mkdir()
            (slot_dir / "memory").mkdir()

        config = _make_isolation_config(enabled=True, channels=["dingtalk", "telegram", "slack", "wechat"])
        store = MemoryStore(tmp_path, isolation_config=config)

        assert len(store._isolation_slots) == 4
        assert "dingtalk:123" in store._isolation_slots
        assert "telegram:456" in store._isolation_slots
        assert "slack:789" in store._isolation_slots
        assert "wechat:001" in store._isolation_slots

    def test_scan_ignores_invalid_dirs_and_picks_valid_ones(self, tmp_path):
        """Invalid directories are skipped; only valid ones produce session keys."""
        # Valid directories
        (tmp_path / "dingtalk_100").mkdir()
        (tmp_path / "dingtalk_100" / "memory").mkdir()
        (tmp_path / "telegram_200").mkdir()
        (tmp_path / "telegram_200" / "memory").mkdir()

        # Invalid directories — should all be ignored
        (tmp_path / "memory").mkdir(exist_ok=True)          # reserved name
        (tmp_path / "random_dir").mkdir()                    # no digits after underscore
        (tmp_path / ".hidden_123").mkdir()                   # starts with dot
        (tmp_path / "no-underscore").mkdir()                 # no underscore separator
        (tmp_path / "123_abc").mkdir()                       # channel part is digits, not letters
        (tmp_path / "dingtalk_").mkdir()                     # missing chat_id digits
        (tmp_path / "_123").mkdir()                          # missing channel letters
        (tmp_path / "dingtalk_abc").mkdir()                  # chat_id is letters, not digits
        (tmp_path / "UPPER_999").mkdir()                     # uppercase channel is valid per regex

        config = _make_isolation_config(enabled=True, channels=["dingtalk", "telegram", "UPPER"])
        store = MemoryStore(tmp_path, isolation_config=config)

        expected_keys = {"dingtalk:100", "telegram:200", "UPPER:999"}
        assert set(store._isolation_slots.keys()) == expected_keys

    def test_scan_skips_files_not_directories(self, tmp_path):
        """Regular files matching the naming pattern are not treated as slots."""
        (tmp_path / "dingtalk_123").write_text("not a directory", encoding="utf-8")
        (tmp_path / "telegram_456").mkdir()
        (tmp_path / "telegram_456" / "memory").mkdir()

        config = _make_isolation_config(enabled=True, channels=["dingtalk", "telegram"])
        store = MemoryStore(tmp_path, isolation_config=config)

        assert "dingtalk:123" not in store._isolation_slots
        assert "telegram:456" in store._isolation_slots
