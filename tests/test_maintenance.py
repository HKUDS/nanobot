"""Tests for MemoryMaintenance (Task 5)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.memory.maintenance import MemoryMaintenance


def _make_maintenance(tmp_path: Path) -> MemoryMaintenance:
    """Create a MemoryMaintenance with mocked collaborators."""
    from nanobot.agent.memory.mem0_adapter import _Mem0Adapter
    from nanobot.agent.memory.persistence import MemoryPersistence

    persistence = MemoryPersistence(tmp_path)
    mem0 = _Mem0Adapter(workspace=tmp_path)
    return MemoryMaintenance(mem0=mem0, persistence=persistence, rollout={})


class TestVectorPointsCount:
    def test_returns_zero_when_no_qdrant_dir(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        assert maint._vector_points_count() == 0

    def test_returns_cached_value(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        maint._vector_count_cache = (float("inf"), 42)
        assert maint._vector_points_count() == 42


class TestHistoryRowCount:
    def test_returns_zero_when_no_history_db(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        assert maint._history_row_count() == 0

    def test_returns_cached_value(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        maint._history_count_cache = (float("inf"), 17)
        assert maint._history_row_count() == 17


class TestEnsureHealth:
    @pytest.mark.asyncio
    async def test_ensure_health_runs(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        # mem0 disabled by default, so it should return without error
        await maint.ensure_health()


class TestReindexClearsAndRebuilds:
    def test_reindex_disabled_mem0(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        result = maint.reindex_from_structured_memory()
        assert result["ok"] is False
        assert result["reason"] == "mem0_disabled"

    def test_reindex_basic_flow(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        maint.mem0.enabled = True
        maint.mem0.add_text = MagicMock(return_value=True)  # type: ignore[method-assign]
        maint.mem0.flush_vector_store = MagicMock(return_value=False)  # type: ignore[method-assign]
        maint.mem0.last_add_mode = "vector"

        profile = {
            "preferences": ["dark mode"],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }
        result = maint.reindex_from_structured_memory(
            read_profile_fn=lambda: profile,
            read_events_fn=lambda limit=None: [],
            vector_points_count_fn=lambda: 1,
            mem0_get_all_rows_fn=lambda limit=500: [{"id": "x"}],
        )
        assert result["ok"] is True
        assert result["written"] >= 1


class TestCompactEvents:
    def test_empty_events(self) -> None:
        out, stats = MemoryMaintenance._compact_events_for_reindex([])
        assert out == []
        assert stats["before"] == 0

    def test_dedup_same_summary(self) -> None:
        events = [
            {"summary": "likes coffee", "type": "preference", "timestamp": "2025-01-01"},
            {"summary": "likes coffee", "type": "preference", "timestamp": "2025-01-02"},
        ]
        out, stats = MemoryMaintenance._compact_events_for_reindex(events)
        assert len(out) == 1
        assert stats["duplicates_dropped"] == 1

    def test_superseded_dropped(self) -> None:
        events = [
            {"summary": "old fact", "type": "fact", "status": "superseded"},
            {"summary": "new fact", "type": "fact", "timestamp": "2025-01-01"},
        ]
        out, stats = MemoryMaintenance._compact_events_for_reindex(events)
        assert stats["superseded_dropped"] == 1
        assert len(out) == 1


class TestBackendStats:
    def test_returns_dict(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        stats = maint._backend_stats_for_eval()
        assert isinstance(stats, dict)
        assert "vector_points_count" in stats
        assert "mem0_get_all_count" in stats
        assert "history_rows_count" in stats
        assert "mem0_enabled" in stats
        assert "mem0_mode" in stats
