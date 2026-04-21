"""Regression tests for cursor recovery after non-integer cursor corruption.

Root cause: cron jobs and other callers occasionally wrote string cursors to
history.jsonl (e.g. ``"cursor": "abc"``).  The original ``_next_cursor`` and
``read_unprocessed_history`` assumed integer cursors and crashed with
``TypeError`` / ``ValueError``, blocking all subsequent history appends.
"""

import json

import pytest

from nanobot.agent.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


class TestNextCursorRecovery:
    """``_next_cursor`` must recover a valid int even when the last entry's
    cursor is corrupted (non-int)."""

    def test_string_cursor_falls_back_to_scan(self, store):
        """Last entry has a string cursor — scan backwards to find a valid int."""
        store.history_file.write_text(
            '{"cursor": 5, "timestamp": "2026-04-01 10:00", "content": "good"}\n'
            '{"cursor": 6, "timestamp": "2026-04-01 10:01", "content": "also good"}\n'
            '{"cursor": "bad", "timestamp": "2026-04-01 10:02", "content": "corrupted"}\n',
            encoding="utf-8",
        )
        # Delete .cursor file so _next_cursor falls back to reading JSONL
        store._cursor_file.unlink(missing_ok=True)
        cursor = store.append_history("recovered event")
        assert cursor == 7

    def test_all_corrupted_cursors_return_one(self, store):
        """Every entry has a non-int cursor — should restart at 1."""
        store.history_file.write_text(
            '{"cursor": "a", "timestamp": "2026-04-01 10:00", "content": "bad1"}\n'
            '{"cursor": "b", "timestamp": "2026-04-01 10:01", "content": "bad2"}\n',
            encoding="utf-8",
        )
        store._cursor_file.unlink(missing_ok=True)
        cursor = store.append_history("fresh start")
        assert cursor == 1

    def test_non_int_cursor_types(self, store):
        """Float, None, list — all non-int types handled gracefully."""
        store.history_file.write_text(
            '{"cursor": 3, "timestamp": "2026-04-01 10:00", "content": "valid"}\n'
            '{"cursor": 3.5, "timestamp": "2026-04-01 10:01", "content": "float"}\n'
            '{"cursor": null, "timestamp": "2026-04-01 10:02", "content": "null"}\n'
            '{"cursor": [1,2], "timestamp": "2026-04-01 10:03", "content": "list"}\n',
            encoding="utf-8",
        )
        store._cursor_file.unlink(missing_ok=True)
        cursor = store.append_history("handles weird types")
        assert cursor == 4

    def test_cursor_file_with_string_content(self, store):
        """Cursor file contains a non-numeric string — should fall back."""
        store._cursor_file.write_text("not_a_number", encoding="utf-8")
        # Also add valid JSONL so the fallback scan finds something
        store.history_file.write_text(
            '{"cursor": 10, "timestamp": "2026-04-01 10:00", "content": "valid"}\n',
            encoding="utf-8",
        )
        cursor = store.append_history("after bad cursor file")
        assert cursor == 11


class TestReadUnprocessedWithCorruption:
    """``read_unprocessed_history`` must skip entries with non-int cursors
    instead of crashing on comparison."""

    def test_skips_string_cursor_entries(self, store):
        """Entries with string cursors are silently skipped."""
        store.history_file.write_text(
            '{"cursor": 1, "timestamp": "2026-04-01 10:00", "content": "valid1"}\n'
            '{"cursor": "bad", "timestamp": "2026-04-01 10:01", "content": "corrupted"}\n'
            '{"cursor": 3, "timestamp": "2026-04-01 10:02", "content": "valid3"}\n',
            encoding="utf-8",
        )
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 2
        assert [e["cursor"] for e in entries] == [1, 3]

    def test_mixed_corruption_preserves_order(self, store):
        """Valid entries maintain correct order despite corrupt neighbors."""
        store.history_file.write_text(
            '{"cursor": "x", "timestamp": "2026-04-01 10:00", "content": "bad"}\n'
            '{"cursor": 2, "timestamp": "2026-04-01 10:01", "content": "good2"}\n'
            '{"cursor": null, "timestamp": "2026-04-01 10:02", "content": "also bad"}\n'
            '{"cursor": 4, "timestamp": "2026-04-01 10:03", "content": "good4"}\n',
            encoding="utf-8",
        )
        entries = store.read_unprocessed_history(since_cursor=0)
        assert [e["cursor"] for e in entries] == [2, 4]

    def test_all_valid_still_works(self, store):
        """Normal operation unaffected — baseline regression check."""
        store.append_history("event 1")
        store.append_history("event 2")
        store.append_history("event 3")
        entries = store.read_unprocessed_history(since_cursor=1)
        assert len(entries) == 2
        assert entries[0]["cursor"] == 2
        assert entries[1]["cursor"] == 3


class TestCursorValidationInvariant:
    """First-principles checks: the cursor validity rules and the
    observability we layer on top of them."""

    def test_bool_cursor_rejected(self, store):
        """``isinstance(True, int) is True`` in Python; the guard must
        still treat ``{"cursor": true}`` as corruption, otherwise a
        boolean silently becomes cursor ``1`` / ``0`` downstream.
        """
        assert MemoryStore._valid_cursor(True) is None
        assert MemoryStore._valid_cursor(False) is None
        assert MemoryStore._valid_cursor(5) == 5
        assert MemoryStore._valid_cursor(0) == 0

        store.history_file.write_text(
            '{"cursor": 4, "timestamp": "2026-04-01 10:00", "content": "real"}\n'
            '{"cursor": true, "timestamp": "2026-04-01 10:01", "content": "bool"}\n',
            encoding="utf-8",
        )
        store._cursor_file.unlink(missing_ok=True)
        assert store.append_history("next") == 5

        entries = store.read_unprocessed_history(since_cursor=0)
        assert [e["cursor"] for e in entries] == [4, 5]

    def test_next_cursor_returns_max_not_just_last_int(self, store):
        """Under adversarial corruption, file order ≠ numeric order.  The
        recovery scan must return ``max(valid cursors) + 1``, not the
        first int seen from the tail, so the returned cursor is strictly
        greater than every legitimate cursor already on disk.
        """
        # Tail is corrupt → recovery scan runs.  Valid cursors are 100
        # and 5, in that order on disk; a naive "first int from the tail"
        # recovery would return 6, which would then silently collide with
        # the existing cursor 100.  ``max`` is the only safe choice.
        store.history_file.write_text(
            '{"cursor": 100, "timestamp": "2026-04-01 10:00", "content": "high"}\n'
            '{"cursor": 5,   "timestamp": "2026-04-01 10:01", "content": "out of order"}\n'
            '{"cursor": "poison", "timestamp": "2026-04-01 10:02", "content": "tail corrupt"}\n',
            encoding="utf-8",
        )
        store._cursor_file.unlink(missing_ok=True)
        assert store.append_history("safe next") == 101

    def test_corruption_is_logged_exactly_once_per_store(self, store, caplog):
        """Observability without spam: the first non-int cursor emits one
        warning, subsequent reads on the same store stay quiet.  Without
        this, a poisoned file produces one warning per agent turn."""
        import logging
        from loguru import logger as loguru_logger

        store.history_file.write_text(
            '{"cursor": "bad1", "timestamp": "2026-04-01 10:00", "content": "x"}\n'
            '{"cursor": 2, "timestamp": "2026-04-01 10:01", "content": "y"}\n',
            encoding="utf-8",
        )
        store._cursor_file.unlink(missing_ok=True)

        handler_id = loguru_logger.add(
            caplog.handler, format="{message}", level="WARNING"
        )
        try:
            with caplog.at_level(logging.WARNING):
                store.read_unprocessed_history(since_cursor=0)
                store.read_unprocessed_history(since_cursor=0)
                store.append_history("another")
        finally:
            loguru_logger.remove(handler_id)

        corruption_warnings = [
            r for r in caplog.records if "non-int cursor" in r.getMessage()
        ]
        assert len(corruption_warnings) == 1, (
            "Expected exactly one corruption warning per store instance; "
            f"got {len(corruption_warnings)}: {[r.getMessage() for r in corruption_warnings]}"
        )
