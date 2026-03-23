# tests/test_unified_db.py
"""Tests for UnifiedMemoryDB — SQLite + FTS5 + sqlite-vec storage."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.agent.memory.unified_db import UnifiedMemoryDB


class TestSchemaCreation:
    def test_creates_database_file(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=384)
        assert (tmp_path / "memory.db").exists()
        db.close()

    def test_wal_mode_enabled(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=384)
        result = db._conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"
        db.close()

    def test_tables_created(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=384)
        tables = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "events" in tables
        assert "profile" in tables
        assert "history" in tables
        assert "snapshots" in tables
        db.close()


class TestEventCRUD:
    def test_insert_event_and_read_back(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        event = {
            "id": "evt-1",
            "type": "fact",
            "summary": "User likes coffee",
            "timestamp": "2026-03-23T12:00:00Z",
            "source": "test",
            "status": "active",
            "metadata": json.dumps({"topic": "preference"}),
            "created_at": "2026-03-23T12:00:00Z",
        }
        embedding = [0.1, 0.2, 0.3, 0.4]
        db.insert_event(event, embedding)
        events = db.read_events(limit=10)
        assert len(events) == 1
        assert events[0]["id"] == "evt-1"
        assert events[0]["summary"] == "User likes coffee"
        db.close()

    def test_insert_event_without_embedding(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        event = {
            "id": "evt-2",
            "type": "fact",
            "summary": "No embedding event",
            "timestamp": "2026-03-23T12:00:00Z",
            "source": "test",
            "status": "active",
            "metadata": None,
            "created_at": "2026-03-23T12:00:00Z",
        }
        db.insert_event(event, embedding=None)
        events = db.read_events(limit=10)
        assert len(events) == 1
        db.close()

    def test_read_events_respects_limit(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        for i in range(5):
            db.insert_event(
                {
                    "id": f"evt-{i}",
                    "type": "fact",
                    "summary": f"Event {i}",
                    "timestamp": f"2026-03-23T12:0{i}:00Z",
                    "source": "test",
                    "status": "active",
                    "metadata": None,
                    "created_at": f"2026-03-23T12:0{i}:00Z",
                },
                embedding=None,
            )
        events = db.read_events(limit=3)
        assert len(events) == 3
        db.close()


class TestFTS5Search:
    def test_search_fts_finds_matching_event(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.insert_event(
            {
                "id": "evt-coffee",
                "type": "fact",
                "summary": "User prefers dark roast coffee",
                "timestamp": "2026-03-23T12:00:00Z",
                "source": "test",
                "status": "active",
                "metadata": None,
                "created_at": "2026-03-23T12:00:00Z",
            },
            embedding=None,
        )
        results = db.search_fts("coffee", k=5)
        assert len(results) >= 1
        assert any("coffee" in r["summary"].lower() for r in results)
        db.close()

    def test_search_fts_returns_empty_for_no_match(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.insert_event(
            {
                "id": "evt-1",
                "type": "fact",
                "summary": "User likes tea",
                "timestamp": "2026-03-23T12:00:00Z",
                "source": "test",
                "status": "active",
                "metadata": None,
                "created_at": "2026-03-23T12:00:00Z",
            },
            embedding=None,
        )
        results = db.search_fts("nonexistent_xyz", k=5)
        assert len(results) == 0
        db.close()


class TestVectorSearch:
    def test_search_vector_returns_nearest(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.insert_event(
            {
                "id": "evt-a",
                "type": "fact",
                "summary": "Alpha event",
                "timestamp": "2026-03-23T12:00:00Z",
                "source": "test",
                "status": "active",
                "metadata": None,
                "created_at": "2026-03-23T12:00:00Z",
            },
            embedding=[1.0, 0.0, 0.0, 0.0],
        )
        db.insert_event(
            {
                "id": "evt-b",
                "type": "fact",
                "summary": "Beta event",
                "timestamp": "2026-03-23T12:01:00Z",
                "source": "test",
                "status": "active",
                "metadata": None,
                "created_at": "2026-03-23T12:01:00Z",
            },
            embedding=[0.0, 1.0, 0.0, 0.0],
        )
        # Query near Alpha
        results = db.search_vector([0.9, 0.1, 0.0, 0.0], k=1)
        assert len(results) == 1
        assert results[0]["id"] == "evt-a"
        db.close()

    def test_search_vector_skips_events_without_embedding(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.insert_event(
            {
                "id": "evt-no-vec",
                "type": "fact",
                "summary": "No vector",
                "timestamp": "2026-03-23T12:00:00Z",
                "source": "test",
                "status": "active",
                "metadata": None,
                "created_at": "2026-03-23T12:00:00Z",
            },
            embedding=None,
        )
        results = db.search_vector([1.0, 0.0, 0.0, 0.0], k=5)
        assert len(results) == 0
        db.close()


class TestProfileCRUD:
    def test_write_and_read_profile(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.write_profile("preferences", {"likes": ["coffee", "hiking"]})
        result = db.read_profile("preferences")
        assert result == {"likes": ["coffee", "hiking"]}
        db.close()

    def test_read_missing_profile_returns_none(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        result = db.read_profile("nonexistent")
        assert result is None
        db.close()

    def test_write_profile_overwrites(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.write_profile("key", {"v": 1})
        db.write_profile("key", {"v": 2})
        assert db.read_profile("key") == {"v": 2}
        db.close()


class TestHistoryAndSnapshots:
    def test_append_and_read_history(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.append_history("First entry")
        db.append_history("Second entry")
        entries = db.read_history(limit=10)
        assert len(entries) == 2
        assert entries[0]["entry"] == "First entry"
        db.close()

    def test_write_and_read_snapshot(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.write_snapshot("current", "# Memory\n\nSome content")
        result = db.read_snapshot("current")
        assert result == "# Memory\n\nSome content"
        db.close()

    def test_read_missing_snapshot_returns_empty(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        result = db.read_snapshot("nonexistent")
        assert result == ""
        db.close()


class TestMetadataSearch:
    def test_search_by_metadata_filters_by_type(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.insert_event(
            {
                "id": "evt-pref",
                "type": "preference",
                "summary": "Likes coffee",
                "timestamp": "2026-03-23T12:00:00Z",
                "source": "test",
                "status": "active",
                "metadata": json.dumps({"topic": "food"}),
                "created_at": "2026-03-23T12:00:00Z",
            },
            embedding=None,
        )
        db.insert_event(
            {
                "id": "evt-task",
                "type": "task",
                "summary": "Fix bug",
                "timestamp": "2026-03-23T12:01:00Z",
                "source": "test",
                "status": "active",
                "metadata": json.dumps({"topic": "work"}),
                "created_at": "2026-03-23T12:01:00Z",
            },
            embedding=None,
        )
        results = db.search_by_metadata(memory_type="preference", k=5)
        assert len(results) == 1
        assert results[0]["type"] == "preference"
        db.close()
