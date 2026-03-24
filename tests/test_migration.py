# tests/test_migration.py
"""Tests for file-to-SQLite migration."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.agent.memory.migration import migrate_to_sqlite
from nanobot.agent.memory.unified_db import UnifiedMemoryDB


def _setup_old_files(memory_dir: Path) -> None:
    """Create mock old-format files in memory_dir."""
    memory_dir.mkdir(parents=True, exist_ok=True)

    # events.jsonl
    events = [
        {
            "id": "e1",
            "type": "fact",
            "summary": "User likes coffee",
            "timestamp": "2026-03-01T10:00:00Z",
            "source": "chat",
            "status": "active",
            "created_at": "2026-03-01T10:00:00Z",
        },
        {
            "id": "e2",
            "type": "task",
            "summary": "Fix the bug",
            "timestamp": "2026-03-02T10:00:00Z",
            "source": "chat",
            "status": "open",
            "created_at": "2026-03-02T10:00:00Z",
        },
    ]
    with open(memory_dir / "events.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    # profile.json
    profile = {
        "preferences": ["dark roast coffee"],
        "stable_facts": ["software engineer"],
        "active_projects": [],
        "relationships": [],
        "constraints": [],
        "conflicts": [],
        "last_verified_at": None,
        "meta": {},
    }
    with open(memory_dir / "profile.json", "w") as f:
        json.dump(profile, f)

    # HISTORY.md
    (memory_dir / "HISTORY.md").write_text(
        "[2026-03-01] First session summary\n\n[2026-03-02] Second session summary\n"
    )

    # MEMORY.md
    (memory_dir / "MEMORY.md").write_text(
        "# Memory\n\n## Preferences\n- dark roast coffee\n\n"
        "<!-- user-pinned -->\nImportant note\n<!-- end-user-pinned -->\n"
    )


class TestMigration:
    def test_migrates_events(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        events = db.read_events(limit=10)
        assert len(events) == 2
        db.close()

    def test_migrates_profile(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        profile = db.read_profile("profile")
        assert profile is not None
        assert "preferences" in profile
        db.close()

    def test_migrates_history(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        entries = db.read_history(limit=10)
        assert len(entries) >= 1
        db.close()

    def test_migrates_memory_md_to_snapshot(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        current = db.read_snapshot("current")
        assert "Memory" in current or "coffee" in current
        db.close()

    def test_extracts_user_pinned_section(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        pinned = db.read_snapshot("user_pinned")
        assert "Important note" in pinned
        db.close()

    def test_renames_old_files_to_bak(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        assert (memory_dir / "events.jsonl.bak").exists()
        assert (memory_dir / "profile.json.bak").exists()
        assert (memory_dir / "HISTORY.md.bak").exists()
        assert (memory_dir / "MEMORY.md.bak").exists()

    def test_no_migration_when_db_exists(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        # Create the DB first
        db = UnifiedMemoryDB(memory_dir / "memory.db", dims=4)
        db.close()
        # Migration should return existing DB, not re-migrate
        db2 = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        events = db2.read_events(limit=10)
        assert len(events) == 0  # no migration happened
        db2.close()

    def test_no_old_files_creates_empty_db(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        events = db.read_events(limit=10)
        assert len(events) == 0
        db.close()

    def test_migrates_knowledge_graph_json(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        # Create a knowledge_graph.json in old format
        graph_data = {
            "nodes": [
                {
                    "id": "alice",
                    "entity_type": "person",
                    "aliases_text": "ali, smithy",
                    "first_seen": "2026-01-01",
                    "last_seen": "2026-03-01",
                    "prop_department": "engineering",
                },
                {
                    "id": "project_x",
                    "entity_type": "project",
                    "aliases_text": "",
                    "first_seen": "2026-01-01",
                    "last_seen": "2026-03-01",
                },
            ],
            "edges": [
                {
                    "source": "alice",
                    "target": "project_x",
                    "type": "WORKS_ON",
                    "confidence": 0.9,
                    "source_event_id": "e1",
                    "timestamp": "2026-01-01",
                },
            ],
        }
        (memory_dir / "knowledge_graph.json").write_text(json.dumps(graph_data))
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        # Verify entities migrated
        alice = db.get_entity("alice")
        assert alice is not None
        assert alice["type"] == "person"
        assert "ali" in alice["aliases"]
        # Verify edges migrated
        edges = db.get_edges_from("alice")
        assert len(edges) == 1
        assert edges[0]["target"] == "project_x"
        assert edges[0]["relation"] == "WORKS_ON"
        assert edges[0]["confidence"] == 0.9
        # Verify properties migrated
        props = json.loads(alice.get("properties", "{}"))
        assert props.get("department") == "engineering"
        db.close()

    def test_graph_json_renamed_to_bak(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        graph_data = {"nodes": [{"id": "x"}], "edges": []}
        (memory_dir / "knowledge_graph.json").write_text(json.dumps(graph_data))
        migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        assert (memory_dir / "knowledge_graph.json.bak").exists()
        assert not (memory_dir / "knowledge_graph.json").exists()

    def test_corrupted_graph_json_skipped(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "knowledge_graph.json").write_text("NOT VALID JSON")
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        # Should not crash; no entities migrated
        assert db.get_entity("anything") is None
        db.close()
