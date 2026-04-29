"""Tests for the restructured MemoryStore — pure file I/O layer."""

import json
from datetime import datetime

import pytest

from nanobot.agent.memory import MemoryStore, _HISTORY_ENTRY_HARD_CAP


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


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

    def test_append_history_strips_thinking_content(self, store):
        """`strip_think` must run before persistence — well-formed thinking
        blocks shouldn't land in history."""
        cursor = store.append_history("<think>reasoning</think>final answer")
        content = store.read_file(store.history_file)
        data = json.loads(content)
        assert data["cursor"] == cursor
        assert data["content"] == "final answer"

    def test_append_history_drops_pure_leak_content(self, store):
        """Regression: entries that strip down to empty (pure template-token
        leak) must NOT fall back to the raw leak. Persisting the raw text
        would re-pollute context via consolidation / replay, undoing the
        protection `strip_think` provides."""
        cursor = store.append_history("<think>nothing user-facing</think>")
        content = store.read_file(store.history_file)
        data = json.loads(content)
        assert data["cursor"] == cursor
        assert data["content"] == ""

    def test_append_history_drops_malformed_leak_prefix(self, store):
        """Channel-marker / malformed opening leaks should not survive."""
        cursor = store.append_history("<channel|>")
        content = store.read_file(store.history_file)
        data = json.loads(content)
        assert data["cursor"] == cursor
        assert data["content"] == ""

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

    def test_read_unprocessed_skips_entries_without_cursor(self, store):
        """Regression: entries missing the cursor key should be silently skipped."""
        store.history_file.write_text(
            '{"timestamp": "2026-04-01 10:00", "content": "no cursor"}\n'
            '{"cursor": 2, "timestamp": "2026-04-01 10:01", "content": "valid"}\n'
            '{"cursor": 3, "timestamp": "2026-04-01 10:02", "content": "also valid"}\n',
            encoding="utf-8",
        )
        entries = store.read_unprocessed_history(since_cursor=0)
        assert [e["cursor"] for e in entries] == [2, 3]

    def test_next_cursor_falls_back_when_last_entry_has_no_cursor(self, store):
        """Regression: _next_cursor should not KeyError on entries without cursor."""
        store.history_file.write_text(
            '{"timestamp": "2026-04-01 10:01", "content": "no cursor"}\n',
            encoding="utf-8",
        )
        # Delete .cursor file so _next_cursor falls back to reading JSONL
        store._cursor_file.unlink(missing_ok=True)
        # Last entry has no cursor — should safely return 1, not KeyError
        cursor = store.append_history("new event")
        assert cursor == 1

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


class TestAppendHistoryHardCap:
    """append_history has a defensive cap that catches new callers who forgot
    to set their own tighter cap. The default is intentionally larger than
    any current caller's per-call cap, so normal operation never trips it."""

    def test_oversized_entry_is_truncated(self, store):
        """An entry above _HISTORY_ENTRY_HARD_CAP is truncated before being persisted."""
        huge = "x" * (_HISTORY_ENTRY_HARD_CAP + 10_000)
        store.append_history(huge)
        entry = store.read_unprocessed_history(since_cursor=0)[0]
        assert len(entry["content"]) <= _HISTORY_ENTRY_HARD_CAP + 50

    def test_oversize_warning_is_emitted_once(self, store, caplog):
        """Repeated oversized writes should warn only on the first occurrence."""
        from loguru import logger as loguru_logger

        records: list[str] = []
        handler_id = loguru_logger.add(lambda m: records.append(m), level="WARNING")
        try:
            huge = "x" * (_HISTORY_ENTRY_HARD_CAP + 1)
            store.append_history(huge)
            store.append_history(huge)
            store.append_history(huge)
        finally:
            loguru_logger.remove(handler_id)

        oversize_warnings = [r for r in records if "exceeds" in r and "chars" in r]
        assert len(oversize_warnings) == 1

    def test_custom_max_chars_overrides_default(self, store):
        """Callers that pass max_chars should get their tighter cap applied."""
        store.append_history("a" * 500, max_chars=100)
        entry = store.read_unprocessed_history(since_cursor=0)[0]
        assert len(entry["content"]) <= 150  # 100 + "\n... (truncated)"

    def test_normal_sized_entries_unaffected(self, store):
        """The hard cap must not alter entries that fit within it."""
        msg = "normal short entry"
        store.append_history(msg)
        entry = store.read_unprocessed_history(since_cursor=0)[0]
        assert entry["content"] == msg


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
            encoding="utf-8",
        )
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
            "[2026-03-25–2026-04-02] Multi-day summary.\n[2026-03-26/27] Cross-day summary.\n"
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
        legacy_file.write_bytes(b"[2026-04-01 10:00] Broken \xff data still needs migration.\n\n")

        store = MemoryStore(tmp_path)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["timestamp"] == "2026-04-01 10:00"
        assert "Broken" in entries[0]["content"]
        assert "migration." in entries[0]["content"]


class TestSessionScopedHistory:
    """Tests for session-scoped history files (dual-write mode)."""

    def test_disabled_by_default(self, tmp_path):
        """When session_scoped_history=False (default), only global file is written."""
        store = MemoryStore(tmp_path, session_scoped_history=False)
        cursor = store.append_history("test entry", session_key="wecom:123")

        # Global file exists
        assert store.history_file.exists()
        # Session file does NOT exist
        session_file = store._session_history_file("wecom:123")
        assert not session_file.exists()

    def test_dual_write_when_enabled(self, tmp_path):
        """When session_scoped_history=True, both files are written."""
        store = MemoryStore(tmp_path, session_scoped_history=True)
        cursor = store.append_history("test entry", session_key="wecom:123")

        # Both files exist
        assert store.history_file.exists()
        session_file = store._session_history_file("wecom:123")
        assert session_file.exists()

        # Both have the same entry
        global_entries = store._read_entries()
        session_entries = store.read_session_history("wecom:123")
        assert len(global_entries) == 1
        assert len(session_entries) == 1
        assert global_entries[0]["content"] == "test entry"
        assert session_entries[0]["content"] == "test entry"

    def test_no_session_key_skips_session_file(self, tmp_path):
        """When session_key is not provided, only global file is written."""
        store = MemoryStore(tmp_path, session_scoped_history=True)
        cursor = store.append_history("global only entry")

        assert store.history_file.exists()
        # No session files created
        assert not list(store.memory_dir.glob("history-*.jsonl"))

    def test_different_sessions_have_separate_files(self, tmp_path):
        """Different sessions have separate history files."""
        store = MemoryStore(tmp_path, session_scoped_history=True)

        store.append_history("wecom entry", session_key="wecom:123")
        store.append_history("telegram entry", session_key="telegram:456")

        wecom_file = store._session_history_file("wecom:123")
        telegram_file = store._session_history_file("telegram:456")

        assert wecom_file.exists()
        assert telegram_file.exists()

        wecom_entries = store.read_session_history("wecom:123")
        telegram_entries = store.read_session_history("telegram:456")

        assert len(wecom_entries) == 1
        assert len(telegram_entries) == 1
        assert wecom_entries[0]["content"] == "wecom entry"
        assert telegram_entries[0]["content"] == "telegram entry"

    def test_global_file_has_all_entries(self, tmp_path):
        """Global history file contains entries from all sessions."""
        store = MemoryStore(tmp_path, session_scoped_history=True)

        store.append_history("wecom entry", session_key="wecom:123")
        store.append_history("telegram entry", session_key="telegram:456")

        global_entries = store._read_entries()
        assert len(global_entries) == 2

    def test_read_session_history_returns_empty_for_missing_session(self, tmp_path):
        """Reading history for a non-existent session returns empty list."""
        store = MemoryStore(tmp_path, session_scoped_history=True)
        entries = store.read_session_history("nonexistent:session")
        assert entries == []

    def test_compact_session_history_drops_old_entries(self, tmp_path):
        """compact_session_history removes entries below min_cursor."""
        store = MemoryStore(tmp_path, session_scoped_history=True)

        c1 = store.append_history("entry 1", session_key="wecom:123")
        c2 = store.append_history("entry 2", session_key="wecom:123")
        c3 = store.append_history("entry 3", session_key="wecom:123")

        # Compact to keep only entries with cursor >= c2
        store.compact_session_history("wecom:123", min_cursor=c2)

        session_entries = store.read_session_history("wecom:123")
        assert len(session_entries) == 2
        assert session_entries[0]["cursor"] == c2
        assert session_entries[1]["cursor"] == c3

    def test_compact_session_history_noop_for_missing_session(self, tmp_path):
        """compact_session_history is a no-op for non-existent session."""
        store = MemoryStore(tmp_path, session_scoped_history=True)
        # Should not raise
        store.compact_session_history("nonexistent:session", min_cursor=1)

    def test_raw_archive_with_session_key(self, tmp_path):
        """raw_archive respects session_key for dual-write."""
        store = MemoryStore(tmp_path, session_scoped_history=True)

        messages = [
            {"role": "user", "content": "hello", "timestamp": "2026-04-27T10:00:00"},
            {"role": "assistant", "content": "hi", "timestamp": "2026-04-27T10:00:05"},
        ]
        store.raw_archive(messages, session_key="wecom:123")

        # Both files should have the entry
        assert store.history_file.exists()
        session_file = store._session_history_file("wecom:123")
        assert session_file.exists()

        session_entries = store.read_session_history("wecom:123")
        assert len(session_entries) == 1
        assert "[RAW]" in session_entries[0]["content"]

    def test_session_file_path_sanitization(self, tmp_path):
        """Session key is properly sanitized for use in filename."""
        store = MemoryStore(tmp_path, session_scoped_history=True)

        # Session key with colons should be converted to underscores
        store.append_history("test", session_key="wecom:123:456")

        # Should create file with sanitized name
        session_file = store._session_history_file("wecom:123:456")
        assert session_file.exists()
        assert "wecom_123_456" in session_file.name
