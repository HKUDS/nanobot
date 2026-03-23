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
