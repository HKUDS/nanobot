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

    def test_search_fts_after_replace_finds_new_not_old(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        event = {
            "id": "evt-replace",
            "type": "fact",
            "summary": "User likes tea",
            "timestamp": "2026-03-23T12:00:00Z",
            "source": "test",
            "status": "active",
            "metadata": None,
            "created_at": "2026-03-23T12:00:00Z",
        }
        db.insert_event(event, embedding=[1.0, 0.0, 0.0, 0.0])
        # Replace with new summary
        event["summary"] = "User likes coffee"
        db.insert_event(event, embedding=[0.0, 1.0, 0.0, 0.0])
        # Old term should not match
        assert len(db.search_fts("tea", k=5)) == 0
        # New term should match
        results = db.search_fts("coffee", k=5)
        assert len(results) == 1
        assert results[0]["id"] == "evt-replace"
        # Vector search should find only the new embedding
        vec_results = db.search_vector([0.0, 1.0, 0.0, 0.0], k=5)
        assert len(vec_results) == 1
        assert vec_results[0]["id"] == "evt-replace"
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


class TestGraphTables:
    def test_entities_table_exists(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        tables = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "entities" in tables
        assert "edges" in tables
        db.close()

    def test_upsert_and_read_entity(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity(
            "alice",
            type="person",
            aliases="ali",
            properties='{"dept": "eng"}',
            first_seen="2026-01-01",
            last_seen="2026-03-01",
        )
        entity = db.get_entity("alice")
        assert entity is not None
        assert entity["type"] == "person"
        assert entity["aliases"] == "ali"
        db.close()

    def test_get_entity_returns_none_for_missing(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        assert db.get_entity("nonexistent") is None
        db.close()

    def test_upsert_entity_updates_existing(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity(
            "alice", type="person", aliases="", first_seen="2026-01-01", last_seen="2026-01-01"
        )
        db.upsert_entity(
            "alice", type="person", aliases="ali", first_seen="2026-01-01", last_seen="2026-03-01"
        )
        entity = db.get_entity("alice")
        assert entity["aliases"] == "ali"
        assert entity["last_seen"] == "2026-03-01"
        db.close()

    def test_add_and_read_edge(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice", type="person")
        db.upsert_entity("project_x", type="project")
        db.add_edge(
            "alice",
            "project_x",
            relation="WORKS_ON",
            confidence=0.9,
            event_id="e1",
            timestamp="2026-01-01",
        )
        edges = db.get_edges_from("alice")
        assert len(edges) == 1
        assert edges[0]["target"] == "project_x"
        assert edges[0]["relation"] == "WORKS_ON"
        db.close()

    def test_get_edges_to(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice", type="person")
        db.upsert_entity("project_x", type="project")
        db.add_edge("alice", "project_x", relation="WORKS_ON")
        edges = db.get_edges_to("project_x")
        assert len(edges) == 1
        assert edges[0]["source"] == "alice"
        db.close()

    def test_get_neighbors(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice", type="person")
        db.upsert_entity("bob", type="person")
        db.upsert_entity("project_x", type="project")
        db.add_edge("alice", "project_x", relation="WORKS_ON")
        db.add_edge("bob", "project_x", relation="WORKS_ON")
        neighbors = db.get_neighbors("project_x", depth=1)
        names = {n["name"] for n in neighbors}
        assert "alice" in names
        assert "bob" in names
        db.close()

    def test_get_neighbors_depth_2(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice", type="person")
        db.upsert_entity("project_x", type="project")
        db.upsert_entity("python", type="technology")
        db.add_edge("alice", "project_x", relation="WORKS_ON")
        db.add_edge("project_x", "python", relation="USES")
        # From alice, depth=2 should reach python
        neighbors = db.get_neighbors("alice", depth=2)
        names = {n["name"] for n in neighbors}
        assert "project_x" in names
        assert "python" in names
        db.close()

    def test_search_entities(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice_smith", type="person", aliases="ali")
        db.upsert_entity("bob_jones", type="person")
        results = db.search_entities("alice", limit=5)
        assert len(results) >= 1
        assert results[0]["name"] == "alice_smith"
        db.close()

    def test_search_entities_by_alias(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice_smith", type="person", aliases="ali, smithy")
        results = db.search_entities("ali", limit=5)
        assert len(results) >= 1
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
