"""Tests for Task 7: consumer migration to UnifiedMemoryDB.

Verifies that snapshot, maintenance, conflicts, profile_io, and eval
route through UnifiedMemoryDB when the db parameter is provided.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.memory.unified_db import UnifiedMemoryDB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_consumer.db"


@pytest.fixture()
def db(db_path: Path) -> UnifiedMemoryDB:
    return UnifiedMemoryDB(db_path, dims=4)


# ---------------------------------------------------------------------------
# snapshot.py
# ---------------------------------------------------------------------------


class TestSnapshotDBPath:
    def test_rebuild_uses_db_for_read_write(self, db: UnifiedMemoryDB, tmp_path: Path) -> None:
        from nanobot.agent.memory.snapshot import MemorySnapshot

        profile_mgr = MagicMock()
        profile_mgr.read_profile.return_value = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "last_verified_at": None,
            "meta": {},
        }

        # Seed snapshot so read_snapshot returns something
        db.write_snapshot("current", "# Old Memory\n")

        snap = MemorySnapshot(
            profile_mgr=profile_mgr,
            read_events_fn=MagicMock(side_effect=AssertionError("should not be called")),
            profile_section_lines_fn=lambda p, **kw: [],
            recent_unresolved_fn=lambda e, **kw: [],
            read_long_term_fn=MagicMock(side_effect=AssertionError("should not be called")),
            write_long_term_fn=MagicMock(side_effect=AssertionError("should not be called")),
            verify_beliefs_fn=lambda: {"summary": {}},
            write_profile_fn=MagicMock(),
            db=db,
        )

        # Insert an event into the DB for the snapshot to pick up.
        db.insert_event(
            {
                "id": "evt-1",
                "type": "fact",
                "summary": "test event",
                "timestamp": "2026-01-01T00:00:00Z",
                "created_at": "2026-01-01T00:00:00Z",
            }
        )

        result = snap.rebuild_memory_snapshot(max_events=10, write=True)
        assert "# Memory" in result

        # Verify it was written to DB, not to file
        stored = db.read_snapshot("current")
        assert "# Memory" in stored

    def test_verify_memory_uses_db_events(self, db: UnifiedMemoryDB, tmp_path: Path) -> None:
        from nanobot.agent.memory.snapshot import MemorySnapshot

        profile_mgr = MagicMock()
        profile_mgr.read_profile.return_value = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "last_verified_at": None,
            "meta": {},
        }
        profile_mgr._meta_section = MagicMock(return_value={})

        snap = MemorySnapshot(
            profile_mgr=profile_mgr,
            read_events_fn=MagicMock(side_effect=AssertionError("should not be called")),
            profile_section_lines_fn=lambda p, **kw: [],
            recent_unresolved_fn=lambda e, **kw: [],
            read_long_term_fn=MagicMock(return_value=""),
            write_long_term_fn=MagicMock(),
            verify_beliefs_fn=lambda: {"summary": {}},
            write_profile_fn=MagicMock(),
            db=db,
        )

        report = snap.verify_memory(stale_days=90)
        assert "events" in report
        assert report["events"] == 0


# ---------------------------------------------------------------------------
# maintenance.py
# ---------------------------------------------------------------------------


class TestMaintenanceDBPath:
    def test_reindex_returns_early_with_db(self, db: UnifiedMemoryDB, tmp_path: Path) -> None:
        from nanobot.agent.memory.maintenance import MemoryMaintenance

        maint = MemoryMaintenance(
            rollout={},
            db=db,
        )

        result = maint.reindex_from_structured_memory()
        assert result["ok"] is True
        assert result["reason"] == "unified_db_active"
        assert result["written"] == 0


# ---------------------------------------------------------------------------
# conflicts.py
# ---------------------------------------------------------------------------


class TestConflictsDBPath:
    def test_resolve_conflict_skips_mem0_with_db(self, db: UnifiedMemoryDB, tmp_path: Path) -> None:
        from nanobot.agent.memory.conflicts import ConflictManager

        profile_mgr = MagicMock()
        profile_mgr.PROFILE_KEYS = (
            "preferences",
            "stable_facts",
            "active_projects",
            "relationships",
            "constraints",
        )
        profile_mgr.PROFILE_STATUS_ACTIVE = "active"
        profile_mgr.PROFILE_STATUS_STALE = "stale"
        profile_mgr._validate_profile_field = MagicMock(return_value="preferences")
        profile_mgr._to_str_list = MagicMock(return_value=["old value", "new value"])
        profile_mgr._meta_entry = MagicMock(
            return_value={"id": "bf-123", "confidence": 0.7, "status": "active"}
        )
        profile_mgr._find_mem0_id_for_text = MagicMock(return_value=None)
        profile_mgr._update_belief_in_profile = MagicMock()
        profile_mgr.read_profile.return_value = {
            "preferences": ["old value", "new value"],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [
                {
                    "field": "preferences",
                    "old": "old value",
                    "new": "new value",
                    "status": "open",
                }
            ],
            "meta": {},
        }
        profile_mgr.write_profile = MagicMock()

        mgr = ConflictManager(
            profile_mgr,
            db=db,
        )

        result = mgr.resolve_conflict_details(0, "keep_old")
        assert result["ok"] is True
        assert result["mem0_operation"] == "none_db"

    def test_resolve_keep_new_skips_mem0_with_db(self, db: UnifiedMemoryDB, tmp_path: Path) -> None:
        from nanobot.agent.memory.conflicts import ConflictManager

        profile_mgr = MagicMock()
        profile_mgr.PROFILE_KEYS = (
            "preferences",
            "stable_facts",
            "active_projects",
            "relationships",
            "constraints",
        )
        profile_mgr.PROFILE_STATUS_ACTIVE = "active"
        profile_mgr.PROFILE_STATUS_STALE = "stale"
        profile_mgr._validate_profile_field = MagicMock(return_value="preferences")
        profile_mgr._to_str_list = MagicMock(return_value=["old value", "new value"])
        profile_mgr._meta_entry = MagicMock(
            return_value={"id": "bf-456", "confidence": 0.7, "status": "active"}
        )
        profile_mgr._find_mem0_id_for_text = MagicMock(return_value=None)
        profile_mgr._update_belief_in_profile = MagicMock()
        profile_mgr.read_profile.return_value = {
            "preferences": ["old value", "new value"],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [
                {
                    "field": "preferences",
                    "old": "old value",
                    "new": "new value",
                    "status": "open",
                }
            ],
            "meta": {},
        }
        profile_mgr.write_profile = MagicMock()

        mgr = ConflictManager(
            profile_mgr,
            db=db,
        )

        result = mgr.resolve_conflict_details(0, "keep_new")
        assert result["ok"] is True
        assert result["mem0_operation"] == "none_db"


# ---------------------------------------------------------------------------
# profile_io.py
# ---------------------------------------------------------------------------


class TestProfileIODBPath:
    def test_read_profile_from_db(self, db: UnifiedMemoryDB, tmp_path: Path) -> None:
        from nanobot.agent.memory.profile_io import ProfileStore

        profile_data = {
            "preferences": ["coffee"],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "last_verified_at": None,
            "meta": {
                "preferences": {},
                "stable_facts": {},
                "active_projects": {},
                "relationships": {},
                "constraints": {},
            },
            "updated_at": "2026-01-01T00:00:00Z",
        }
        db.write_profile("profile", profile_data)

        store = ProfileStore(db=db)

        result = store.read_profile()
        assert "coffee" in result["preferences"]

    def test_write_profile_to_db(self, db: UnifiedMemoryDB, tmp_path: Path) -> None:
        from nanobot.agent.memory.profile_io import ProfileStore

        store = ProfileStore(db=db)

        profile = {
            "preferences": ["tea"],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "last_verified_at": None,
            "meta": {},
        }
        store.write_profile(profile)

        # Verify written to DB
        stored = db.read_profile("profile")
        assert stored is not None
        assert "tea" in stored["preferences"]

    def test_find_mem0_id_uses_db_fts(self, db: UnifiedMemoryDB, tmp_path: Path) -> None:
        from nanobot.agent.memory.profile_io import ProfileStore

        store = ProfileStore(db=db)

        # Insert an event so FTS can find it
        db.insert_event(
            {
                "id": "evt-fts-1",
                "type": "fact",
                "summary": "user likes coffee",
                "timestamp": "2026-01-01T00:00:00Z",
                "created_at": "2026-01-01T00:00:00Z",
            }
        )

        result = store._find_mem0_id_for_text("coffee")
        assert result == "evt-fts-1"

    def test_find_mem0_id_returns_none_for_no_match(
        self, db: UnifiedMemoryDB, tmp_path: Path
    ) -> None:
        from nanobot.agent.memory.profile_io import ProfileStore

        store = ProfileStore(db=db)

        result = store._find_mem0_id_for_text("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# eval.py
# ---------------------------------------------------------------------------


class TestEvalDBPath:
    def test_save_report_uses_db_path(self, db: UnifiedMemoryDB, tmp_path: Path) -> None:
        from nanobot.agent.memory.eval import EvalRunner

        runner = EvalRunner(
            retrieve_fn=MagicMock(return_value=[]),
            workspace=tmp_path,
            memory_dir=tmp_path / "memory",
            get_rollout_status_fn=lambda: {"mode": "enabled"},
            get_rollout_fn=lambda: {},
            get_backend_stats_fn=lambda: {
                "vector_points_count": 0,
                "mem0_get_all_count": 0,
                "history_rows_count": 0,
                "mem0_enabled": False,
                "mem0_mode": "disabled",
            },
            db=db,
        )

        report_path = runner.save_evaluation_report(
            {"summary": {"recall_at_k": 0.5}},
            {"metrics": {}},
            output_file=str(tmp_path / "report.json"),
        )

        # Verify it wrote the file directly
        assert report_path.exists()
        content = json.loads(report_path.read_text(encoding="utf-8"))
        assert "evaluation" in content
