"""Tests for MemorySnapshot (Task 6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.memory.persistence.profile_io import ProfileStore as ProfileManager
from nanobot.memory.persistence.snapshot import MemorySnapshot


def _make_snapshot(
    tmp_path: Path,
    *,
    profile: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> MemorySnapshot:
    """Create a MemorySnapshot with mocked collaborators."""
    profile_mgr = ProfileManager()

    _events = events or []
    _long_term: dict[str, str] = {"content": ""}

    return MemorySnapshot(
        profile_mgr=profile_mgr,
        read_events_fn=lambda **kw: _events[: kw.get("limit") or len(_events)],
        profile_section_lines_fn=lambda p, **kw: (
            ["## Preferences", "- test pref"] if p.get("preferences") else []
        ),
        recent_unresolved_fn=lambda evts, **kw: [e for e in evts if e.get("status") == "open"][
            : kw.get("max_items", 8)
        ],
        read_long_term_fn=lambda: _long_term["content"],
        write_long_term_fn=lambda content: _long_term.__setitem__("content", content),
        verify_beliefs_fn=lambda: {"summary": {"total": 0, "well_supported": 0}},
        write_profile_fn=lambda p: None,
    )


class TestRebuildWritesMemoryMd:
    def test_produces_content(self, tmp_path: Path) -> None:
        events = [
            {"type": "fact", "summary": "likes cats", "timestamp": "2025-01-15T10:00:00Z"},
        ]
        snap = _make_snapshot(
            tmp_path,
            profile={"preferences": ["dark mode"]},
            events=events,
        )
        result = snap.rebuild_memory_snapshot(write=True)
        assert "# Memory" in result
        assert "likes cats" in result


class TestRebuildEmptyProfile:
    def test_handles_empty_gracefully(self, tmp_path: Path) -> None:
        snap = _make_snapshot(tmp_path)
        result = snap.rebuild_memory_snapshot(write=False)
        assert "# Memory" in result
        # Should not crash on empty profile/events


class TestVerifyDetectsStaleItems:
    def test_stale_items_flagged(self, tmp_path: Path) -> None:
        events = [
            {
                "type": "fact",
                "summary": "old fact",
                "timestamp": "2020-01-01T00:00:00Z",
            },
        ]
        snap = _make_snapshot(tmp_path, events=events)
        report = snap.verify_memory(stale_days=30)
        assert report["stale_events"] >= 1


class TestVerifyReportsEventStats:
    def test_event_counts_in_report(self, tmp_path: Path) -> None:
        events = [
            {"type": "fact", "summary": "a", "timestamp": "2025-01-01T00:00:00Z"},
            {"type": "preference", "summary": "b", "timestamp": "2025-01-02T00:00:00Z"},
        ]
        snap = _make_snapshot(tmp_path, events=events)
        report = snap.verify_memory()
        assert report["events"] == 2
        assert isinstance(report["stale_events"], int)
        assert isinstance(report["open_conflicts"], int)
        assert "belief_quality" in report
