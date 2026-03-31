"""Typed data objects for the retrieval pipeline.

``RetrievedMemory`` replaces the ``dict[str, Any]`` that previously flowed
through retriever -> scorer -> reranker -> context assembler. Every field
that any pipeline stage reads or writes is an explicit typed attribute.

``RetrievalScores`` captures the scoring signals accumulated as an item
passes through the scoring and reranking stages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["RetrievalScores", "RetrievedMemory", "retrieved_memory_from_dict"]


@dataclass(slots=True)
class RetrievalScores:
    """Scoring signals accumulated during the retrieval pipeline."""

    rrf_score: float = 0.0
    final_score: float = 0.0
    recency: float = 0.0
    type_boost: float = 0.0
    stability_boost: float = 0.0
    reflection_penalty: float = 0.0
    profile_adjustment: float = 0.0
    profile_adjustment_reasons: list[str] = field(default_factory=list)
    intent: str = ""
    semantic: float = 0.0
    provider: str = "vector"
    # Optional reranker scores
    ce_score: float | None = None
    blended_score: float | None = None
    reranker_alpha: float | None = None


@dataclass(slots=True)
class RetrievedMemory:
    """A memory item flowing through the retrieval pipeline.

    Replaces ``dict[str, Any]`` with typed attributes that mypy can check.
    Mutable because the scorer and reranker update scores incrementally.
    """

    # From database (always present)
    id: str
    type: str
    summary: str
    timestamp: str
    source: str = ""
    status: str = "active"
    created_at: str = ""
    # From metadata unpacking
    memory_type: str = "episodic"
    topic: str = ""
    stability: str = "medium"
    entities: list[str] = field(default_factory=list)
    triples: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.7
    superseded_by_event_id: str = ""
    # Computed during pipeline
    scores: RetrievalScores = field(default_factory=RetrievalScores)
    # Raw metadata for pass-through (keys not explicitly modeled)
    raw_metadata: dict[str, Any] = field(default_factory=dict)


def retrieved_memory_from_dict(item: dict[str, Any]) -> RetrievedMemory:
    """Convert an enriched event dict (after metadata unpacking) to a typed object.

    Called by ``MemoryRetriever._enrich_and_convert()`` after the dict has been
    enriched with memory_type, topic, stability, and _extra keys.
    """
    # Parse metadata if still a string
    raw_meta = item.get("metadata")
    if isinstance(raw_meta, str):
        import json

        try:
            raw_meta = json.loads(raw_meta)
        except (json.JSONDecodeError, TypeError):
            raw_meta = {}
    if not isinstance(raw_meta, dict):
        raw_meta = {}

    # Build initial scores from any existing scoring data
    reason = item.get("retrieval_reason")
    scores = RetrievalScores()
    if isinstance(reason, dict):
        scores.rrf_score = float(reason.get("score", 0.0))
        scores.recency = float(reason.get("recency", 0.0))
        scores.semantic = float(reason.get("semantic", 0.0))
        scores.provider = str(reason.get("provider", "vector"))
    # RRF score from fusion
    if "_rrf_score" in item:
        scores.rrf_score = float(item["_rrf_score"])

    return RetrievedMemory(
        id=str(item.get("id", "")),
        type=str(item.get("type", "fact")),
        summary=str(item.get("summary", "")),
        timestamp=str(item.get("timestamp", "")),
        source=str(item.get("source", "")),
        status=str(item.get("status", "active")),
        created_at=str(item.get("created_at", "")),
        memory_type=str(item.get("memory_type", "episodic")),
        topic=str(item.get("topic", "")),
        stability=str(item.get("stability", "medium")),
        entities=list(item.get("entities", [])) if isinstance(item.get("entities"), list) else [],
        triples=list(item.get("triples", [])) if isinstance(item.get("triples"), list) else [],
        evidence_refs=list(item.get("evidence_refs", []))
        if isinstance(item.get("evidence_refs"), list)
        else [],
        confidence=float(item.get("confidence", 0.7)),
        superseded_by_event_id=str(item.get("superseded_by_event_id", "")),
        scores=scores,
        raw_metadata=raw_meta,
    )
