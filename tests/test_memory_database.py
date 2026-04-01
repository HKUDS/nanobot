"""Tests for MemoryDatabase -- connection management and simple CRUD."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nanobot.memory.db import MemoryDatabase


@pytest.fixture()
def db(tmp_path: Path) -> MemoryDatabase:
    d = MemoryDatabase(tmp_path / "test.db", dims=4)
    yield d  # type: ignore[misc]
    d.close()


class TestConstruction:
    def test_creates_all_tables(self, db: MemoryDatabase) -> None:
        tables = {
            row[0]
            for row in db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "events" in tables
        assert "profile" in tables
        assert "history" in tables
        assert "snapshots" in tables
        assert "entities" in tables
        assert "edges" in tables
        assert "strategies" in tables

    def test_wal_mode(self, db: MemoryDatabase) -> None:
        mode = db.connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_dims_must_be_positive(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="positive"):
            MemoryDatabase(tmp_path / "bad.db", dims=0)

    def test_connection_property(self, db: MemoryDatabase) -> None:
        assert isinstance(db.connection, sqlite3.Connection)

    def test_events_indexes_exist(self, db: MemoryDatabase) -> None:
        indexes = {
            row[0]
            for row in db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_events_type" in indexes
        assert "idx_events_status" in indexes
        assert "idx_events_timestamp" in indexes
        assert "idx_edges_target" in indexes

    def test_context_manager(self, tmp_path: Path) -> None:
        with MemoryDatabase(tmp_path / "ctx.db", dims=4) as d:
            assert d.connection is not None


class TestProfileCRUD:
    def test_read_missing_returns_none(self, db: MemoryDatabase) -> None:
        assert db.read_profile("nonexistent") is None

    def test_write_and_read_roundtrip(self, db: MemoryDatabase) -> None:
        db.write_profile("test_key", {"hello": "world", "count": 42})
        result = db.read_profile("test_key")
        assert result == {"hello": "world", "count": 42}

    def test_write_upserts(self, db: MemoryDatabase) -> None:
        db.write_profile("k", {"v": 1})
        db.write_profile("k", {"v": 2})
        assert db.read_profile("k") == {"v": 2}

    def test_mixed_type_values(self, db: MemoryDatabase) -> None:
        """Profile values with mixed types including None, list, nested dict."""
        data: dict[str, object] = {
            "name": "test",
            "count": 99,
            "tags": ["a", "b"],
            "nested": {"x": 1},
            "empty": None,
        }
        db.write_profile("mixed", data)  # type: ignore[arg-type]
        result = db.read_profile("mixed")
        assert result == data


class TestHistoryCRUD:
    def test_append_and_read(self, db: MemoryDatabase) -> None:
        db.append_history("entry one")
        db.append_history("entry two")
        rows = db.read_history(limit=10)
        assert len(rows) == 2
        assert rows[0]["entry"] == "entry one"
        assert rows[1]["entry"] == "entry two"

    def test_read_empty(self, db: MemoryDatabase) -> None:
        assert db.read_history() == []

    def test_limit_respected(self, db: MemoryDatabase) -> None:
        for i in range(5):
            db.append_history(f"entry {i}")
        rows = db.read_history(limit=3)
        assert len(rows) == 3


class TestSnapshotCRUD:
    def test_read_missing_returns_empty(self, db: MemoryDatabase) -> None:
        assert db.read_snapshot("missing") == ""

    def test_write_and_read_roundtrip(self, db: MemoryDatabase) -> None:
        db.write_snapshot("current", "# Memory\n\nSome content")
        assert db.read_snapshot("current") == "# Memory\n\nSome content"

    def test_write_upserts(self, db: MemoryDatabase) -> None:
        db.write_snapshot("k", "old")
        db.write_snapshot("k", "new")
        assert db.read_snapshot("k") == "new"

    def test_empty_string_content(self, db: MemoryDatabase) -> None:
        db.write_snapshot("empty", "")
        assert db.read_snapshot("empty") == ""

    def test_max_length_content(self, db: MemoryDatabase) -> None:
        """Snapshot with large content string."""
        big = "x" * 100_000
        db.write_snapshot("big", big)
        assert db.read_snapshot("big") == big
