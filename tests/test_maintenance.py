"""Tests for MemoryMaintenance (Task 5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.memory.maintenance import MemoryMaintenance


def _make_maintenance(tmp_path: Path) -> MemoryMaintenance:
    """Create a MemoryMaintenance with default config."""
    return MemoryMaintenance(rollout_fn=lambda: {})


class TestBackendStats:
    def test_returns_dict(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        stats = maint._backend_stats_for_eval()
        assert isinstance(stats, dict)
        assert "vector_points_count" in stats
        assert "vector_enabled" in stats


class TestEnsureHealth:
    @pytest.mark.asyncio
    async def test_ensure_health_runs(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        await maint.ensure_health()


class TestReindexReturnsNoOp:
    def test_reindex_returns_unified_db_active(self, tmp_path: Path) -> None:
        maint = _make_maintenance(tmp_path)
        result = maint.reindex_from_structured_memory()
        assert result["ok"] is True
        assert result["reason"] == "unified_db_active"


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
