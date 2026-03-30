"""Event classification and metadata enrichment.

Extracted from ``EventIngester`` — owns memory-type classification,
stability inference, topic defaults, and metadata normalization.
"""

from __future__ import annotations

import re
from typing import Any

from .._text import _contains_any, _safe_float, _utc_now_iso
from ..constants import MEMORY_STABILITY, MEMORY_TYPES


class EventClassifier:
    """Classifies events by memory type, stability, and topic."""

    @staticmethod
    def default_topic_for_event_type(event_type: str) -> str:
        """Map an event type to its default topic label."""
        topic_by_event_type = {
            "preference": "user_preference",
            "fact": "knowledge",
            "task": "task_progress",
            "decision": "decision_log",
            "constraint": "constraint",
            "relationship": "relationship",
        }
        return topic_by_event_type.get(str(event_type or "").lower(), "general")

    def classify_memory_type(
        self,
        *,
        event_type: str,
        summary: str,
        source: str,
    ) -> tuple[str, str, bool]:
        """Determine memory_type, stability, and is_mixed flag."""
        event_kind = str(event_type or "fact").lower()
        text = str(summary or "")
        source_norm = str(source or "chat").strip().lower() or "chat"

        if source_norm == "reflection":
            return "reflection", "medium", False

        semantic_default = {"preference", "fact", "constraint", "relationship"}
        episodic_default = {"task", "decision"}
        memory_type = "semantic" if event_kind in semantic_default else "episodic"
        if event_kind in episodic_default:
            memory_type = "episodic"

        incident_markers = (
            "failed",
            "error",
            "issue",
            "incident",
            "debug",
            "tried",
            "attempt",
            "fix",
            "resolved",
            "yesterday",
            "today",
            "last time",
        )
        causal_markers = ("because", "due to", "after", "when", "since")
        has_incident = _contains_any(text, incident_markers)
        has_causal = _contains_any(text, causal_markers)
        is_mixed = memory_type == "semantic" and has_incident and has_causal

        if memory_type == "semantic":
            stability = "high"
            if has_incident:
                stability = "medium"
        elif memory_type == "reflection":
            stability = "medium"
        else:
            stability = "low" if has_incident else "medium"
        return memory_type, stability, is_mixed

    @staticmethod
    def distill_semantic_summary(summary: str) -> str:
        """Extract the semantic core from a summary by stripping causal clauses."""
        text = re.sub(r"\s+", " ", str(summary or "").strip())
        if not text:
            return ""
        splitters = (" because ", " due to ", " after ", " when ", " since ")
        lowered = text.lower()
        cut = len(text)
        for marker in splitters:
            idx = lowered.find(marker)
            if idx >= 0:
                cut = min(cut, idx)
        distilled = text[:cut].strip(" .;:-")
        if len(distilled) < 12:
            return text
        return distilled

    def normalize_memory_metadata(
        self,
        metadata: dict[str, Any] | None,
        *,
        event_type: str,
        summary: str,
        source: str,
    ) -> tuple[dict[str, Any], bool]:
        """Enrich event metadata with classification, topic, stability, etc."""
        payload = dict(metadata or {})
        memory_type, default_stability, is_mixed = self.classify_memory_type(
            event_type=event_type,
            summary=summary,
            source=source,
        )

        topic = str(payload.get("topic", "")).strip() or self.default_topic_for_event_type(
            event_type
        )
        raw_type = str(payload.get("memory_type", "")).strip().lower()
        if raw_type in MEMORY_TYPES:
            memory_type = raw_type

        stability = str(payload.get("stability", default_stability)).strip().lower()
        if stability not in MEMORY_STABILITY:
            stability = default_stability

        confidence = min(max(_safe_float(payload.get("confidence"), 0.7), 0.0), 1.0)
        timestamp = str(payload.get("timestamp", "")).strip() or _utc_now_iso()
        ttl_days = payload.get("ttl_days")
        if not isinstance(ttl_days, int) or ttl_days <= 0:
            ttl_days = None
        evidence_refs = payload.get("evidence_refs")
        if not isinstance(evidence_refs, list):
            evidence_refs = []
        evidence_refs = [str(x).strip() for x in evidence_refs if str(x).strip()]

        reflection_safety_downgraded = bool(payload.get("reflection_safety_downgraded"))
        if memory_type == "reflection":
            # Reflection memories must be grounded to avoid self-reinforcing hallucinations.
            if not evidence_refs:
                memory_type = "episodic"
                stability = "low"
                reflection_safety_downgraded = True
            elif ttl_days is None:
                ttl_days = 30

        return {
            "memory_type": memory_type,
            "topic": topic,
            "stability": stability,
            "source": str(source or "chat").strip().lower() or "chat",
            "confidence": confidence,
            "timestamp": timestamp,
            "ttl_days": ttl_days,
            "evidence_refs": evidence_refs,
            "reflection_safety_downgraded": reflection_safety_downgraded,
        }, is_mixed
