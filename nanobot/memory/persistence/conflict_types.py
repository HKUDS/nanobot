"""Typed conflict record for profile contradictions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["ConflictRecord"]


@dataclass(slots=True)
class ConflictRecord:
    """A detected contradiction between two profile beliefs.

    Mutable because conflict status is updated during resolution
    and user interaction.
    """

    timestamp: str
    field: str
    old: str
    new: str
    status: str = "open"  # open | needs_user | resolved
    # Belief tracking
    belief_id_old: str = ""
    belief_id_new: str = ""
    old_memory_id: str = ""
    new_memory_id: str = ""
    # Confidence at detection time
    old_confidence: float = 0.65
    new_confidence: float = 0.65
    old_last_seen_at: str = ""
    new_last_seen_at: str = ""
    # Resolution
    resolution: str = ""  # keep_old | keep_new | dismiss
    resolved_at: str = ""
    source: str = "consolidation"
    # User interaction
    asked_at: str = ""
    # Runtime (set by list_conflicts, not persisted)
    index: int = -1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the dict format stored in profile['conflicts']."""
        return {
            "timestamp": self.timestamp,
            "field": self.field,
            "old": self.old,
            "new": self.new,
            "status": self.status,
            "belief_id_old": self.belief_id_old,
            "belief_id_new": self.belief_id_new,
            "old_memory_id": self.old_memory_id,
            "new_memory_id": self.new_memory_id,
            "old_confidence": self.old_confidence,
            "new_confidence": self.new_confidence,
            "old_last_seen_at": self.old_last_seen_at,
            "new_last_seen_at": self.new_last_seen_at,
            "resolution": self.resolution,
            "resolved_at": self.resolved_at,
            "source": self.source,
            "asked_at": self.asked_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int = -1) -> ConflictRecord:
        """Parse a conflict dict from profile storage."""
        return cls(
            timestamp=str(data.get("timestamp", "")),
            field=str(data.get("field", "")),
            old=str(data.get("old", "")),
            new=str(data.get("new", "")),
            status=str(data.get("status", "open")),
            belief_id_old=str(data.get("belief_id_old", "")),
            belief_id_new=str(data.get("belief_id_new", "")),
            old_memory_id=str(data.get("old_memory_id", "")),
            new_memory_id=str(data.get("new_memory_id", "")),
            old_confidence=float(data.get("old_confidence", 0.65)),
            new_confidence=float(data.get("new_confidence", 0.65)),
            old_last_seen_at=str(data.get("old_last_seen_at", "")),
            new_last_seen_at=str(data.get("new_last_seen_at", "")),
            resolution=str(data.get("resolution", "")),
            resolved_at=str(data.get("resolved_at", "")),
            source=str(data.get("source", "consolidation")),
            asked_at=str(data.get("asked_at", "")),
            index=index,
        )
