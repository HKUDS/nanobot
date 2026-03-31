"""Tests for ConflictRecord dataclass."""

from __future__ import annotations

from nanobot.memory.persistence.conflict_types import ConflictRecord


def _full_conflict_dict() -> dict:
    """A complete conflict dict as stored in profile['conflicts']."""
    return {
        "timestamp": "2026-03-28T12:00:00Z",
        "field": "preferences",
        "old": "Prefers dark mode",
        "new": "Prefers light mode",
        "status": "needs_user",
        "belief_id_old": "bel-old-001",
        "belief_id_new": "bel-new-002",
        "old_memory_id": "mem-old-100",
        "new_memory_id": "mem-new-200",
        "old_confidence": 0.72,
        "new_confidence": 0.45,
        "old_last_seen_at": "2026-03-20T08:00:00Z",
        "new_last_seen_at": "2026-03-28T12:00:00Z",
        "resolution": "",
        "resolved_at": "",
        "source": "live_correction",
        "asked_at": "2026-03-28T12:05:00Z",
    }


class TestFromDict:
    def test_full_dict_populates_all_fields(self) -> None:
        data = _full_conflict_dict()
        rec = ConflictRecord.from_dict(data, index=3)

        assert rec.timestamp == "2026-03-28T12:00:00Z"
        assert rec.field == "preferences"
        assert rec.old == "Prefers dark mode"
        assert rec.new == "Prefers light mode"
        assert rec.status == "needs_user"
        assert rec.belief_id_old == "bel-old-001"
        assert rec.belief_id_new == "bel-new-002"
        assert rec.old_memory_id == "mem-old-100"
        assert rec.new_memory_id == "mem-new-200"
        assert rec.old_confidence == 0.72
        assert rec.new_confidence == 0.45
        assert rec.old_last_seen_at == "2026-03-20T08:00:00Z"
        assert rec.new_last_seen_at == "2026-03-28T12:00:00Z"
        assert rec.resolution == ""
        assert rec.resolved_at == ""
        assert rec.source == "live_correction"
        assert rec.asked_at == "2026-03-28T12:05:00Z"
        assert rec.index == 3

    def test_empty_dict_uses_defaults(self) -> None:
        rec = ConflictRecord.from_dict({})

        assert rec.timestamp == ""
        assert rec.field == ""
        assert rec.old == ""
        assert rec.new == ""
        assert rec.status == "open"
        assert rec.belief_id_old == ""
        assert rec.belief_id_new == ""
        assert rec.old_memory_id == ""
        assert rec.new_memory_id == ""
        assert rec.old_confidence == 0.65
        assert rec.new_confidence == 0.65
        assert rec.old_last_seen_at == ""
        assert rec.new_last_seen_at == ""
        assert rec.resolution == ""
        assert rec.resolved_at == ""
        assert rec.source == "consolidation"
        assert rec.asked_at == ""
        assert rec.index == -1

    def test_index_defaults_to_negative_one(self) -> None:
        rec = ConflictRecord.from_dict({"field": "preferences"})
        assert rec.index == -1


class TestToDict:
    def test_roundtrip(self) -> None:
        data = _full_conflict_dict()
        rec = ConflictRecord.from_dict(data, index=5)
        result = rec.to_dict()

        # Every key in the original should match the roundtrip.
        for key, value in data.items():
            assert result[key] == value, f"Mismatch on key {key!r}"

    def test_does_not_include_index(self) -> None:
        rec = ConflictRecord.from_dict(_full_conflict_dict(), index=7)
        d = rec.to_dict()
        assert "index" not in d

    def test_roundtrip_from_defaults(self) -> None:
        rec = ConflictRecord.from_dict({})
        d = rec.to_dict()
        rec2 = ConflictRecord.from_dict(d)
        assert rec2.status == rec.status
        assert rec2.old_confidence == rec.old_confidence
        assert rec2.source == rec.source


class TestMutability:
    def test_status_can_be_changed(self) -> None:
        rec = ConflictRecord.from_dict({"status": "open"})
        rec.status = "resolved"
        assert rec.status == "resolved"

    def test_resolution_can_be_set(self) -> None:
        rec = ConflictRecord.from_dict({})
        rec.resolution = "keep_new"
        rec.resolved_at = "2026-03-28T13:00:00Z"
        assert rec.resolution == "keep_new"
        assert rec.resolved_at == "2026-03-28T13:00:00Z"

    def test_asked_at_can_be_set(self) -> None:
        rec = ConflictRecord.from_dict({})
        rec.asked_at = "2026-03-28T14:00:00Z"
        assert rec.asked_at == "2026-03-28T14:00:00Z"
