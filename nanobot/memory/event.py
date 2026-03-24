"""Typed MemoryEvent model for structured memory event validation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enums as Literal types (matching MemoryStore class constants)
# ---------------------------------------------------------------------------

EventType = Literal["preference", "fact", "task", "decision", "constraint", "relationship"]
MemoryType = Literal["semantic", "episodic", "reflection"]
Stability = Literal["high", "medium", "low"]

# Runtime set for membership checks (mirrors the MemoryType Literal above).
MEMORY_TYPES: frozenset[str] = frozenset({"semantic", "episodic", "reflection"})

_RESOLVED_MARKERS: tuple[str, ...] = (
    "done",
    "completed",
    "resolved",
    "closed",
    "finished",
    "cancelled",
    "canceled",
)


def is_resolved_task_or_decision(summary: str) -> bool:
    """Check whether a task/decision summary indicates resolved status."""
    text = summary.lower()
    return any(marker in text for marker in _RESOLVED_MARKERS)


def memory_type_for_item(item: dict[str, Any]) -> str:
    """Classify the memory type of an event/item dict."""
    mt = str(item.get("memory_type", "")).strip().lower()
    if mt in MEMORY_TYPES:
        return mt
    meta = item.get("metadata")
    if isinstance(meta, dict):
        meta_type = str(meta.get("memory_type", "")).strip().lower()
        if meta_type in MEMORY_TYPES:
            return meta_type
    event_type = str(item.get("type", "")).strip().lower()
    if event_type in {"task", "decision"}:
        return "episodic"
    if event_type in {"preference", "fact", "constraint", "relationship"}:
        return "semantic"
    return "episodic"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class KnowledgeTriple(BaseModel):
    """A single subject-predicate-object triple for the knowledge graph."""

    subject: str
    predicate: str = "RELATED_TO"
    object: str
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Main MemoryEvent model
# ---------------------------------------------------------------------------


class BeliefRecord(BaseModel):
    """A single belief about the user, with evidence and lifecycle tracking."""

    id: str
    field: (
        str  # "preferences" | "stable_facts" | "active_projects" | "relationships" | "constraints"
    )
    text: str
    confidence: float = 0.65
    evidence_count: int = 1
    evidence_event_ids: list[str] = Field(default_factory=list)
    status: str = "active"  # active | conflicted | stale | retracted
    created_at: str = ""
    last_seen_at: str = ""
    pinned: bool = False
    supersedes_id: str | None = None
    superseded_by_id: str | None = None


class MemoryEvent(BaseModel):
    """Typed, validated representation of a memory event.

    This replaces the plain ``dict[str, Any]`` used throughout the memory
    subsystem.  All fields match the schema enforced by
    ``MemoryStore._coerce_event``.
    """

    id: str = ""
    timestamp: str = ""
    channel: str = ""
    chat_id: str = ""
    type: EventType = "fact"
    summary: str
    entities: list[str] = Field(default_factory=list)
    salience: float = Field(default=0.6, ge=0.0, le=1.0)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    source_span: list[int] = Field(default_factory=list)
    ttl_days: int | None = None
    memory_type: MemoryType = "episodic"
    topic: str = ""
    stability: Stability = "medium"
    source: str = "chat"
    evidence_refs: list[str] = Field(default_factory=list)
    status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    triples: list[KnowledgeTriple] = Field(default_factory=list)

    # Fields used for supersession tracking
    canonical_id: str = ""
    supersedes_event_id: str = ""
    supersedes_at: str = ""

    model_config = {"extra": "allow"}

    @field_validator("summary")
    @classmethod
    def summary_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("summary must not be empty")
        return stripped

    @field_validator("ttl_days")
    @classmethod
    def ttl_positive_or_none(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            return None
        return v

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the dict format used by persistence/retrieval."""
        d = self.model_dump(mode="python")
        # Convert KnowledgeTriple models to plain dicts
        d["triples"] = [t.model_dump(mode="python") for t in self.triples]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEvent:
        """Parse a raw dict (e.g. from JSONL) into a validated MemoryEvent.

        Applies lenient coercion similar to ``MemoryStore._coerce_event``:
        unknown ``type`` values fall back to ``"fact"``, out-of-range floats
        are clamped, and missing fields use defaults.
        """
        # Coerce event type
        raw_type = data.get("type", "fact")
        valid_types = {"preference", "fact", "task", "decision", "constraint", "relationship"}
        if raw_type not in valid_types:
            data = {**data, "type": "fact"}
        return cls.model_validate(data)
