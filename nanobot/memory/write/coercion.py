"""Event coercion — normalizes raw event dicts into canonical form.

Extracted from ``EventIngester`` — owns ID generation, episodic status
inference, and the full coercion pipeline.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from .._text import _norm_text, _safe_float, _to_str_list, _utc_now_iso
from ..constants import (
    EPISODIC_STATUS_OPEN,
    EPISODIC_STATUS_RESOLVED,
    EVENT_TYPES,
    MEMORY_STABILITY,
    MEMORY_TYPES,
)
from ..event import MemoryEvent, is_resolved_task_or_decision

if TYPE_CHECKING:
    from .classification import EventClassifier


class EventCoercer:
    """Normalizes raw event dicts into canonical form."""

    def __init__(self, classifier: EventClassifier) -> None:
        self._classifier = classifier

    @staticmethod
    def build_event_id(event_type: str, summary: str, timestamp: str) -> str:
        """Generate a deterministic hash-based event ID."""
        raw = f"{_norm_text(event_type)}|{_norm_text(summary)}|{timestamp[:16]}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def infer_episodic_status(
        self, *, event_type: str, summary: str, raw_status: Any = None
    ) -> str | None:
        """Infer episodic status (open/resolved) for task/decision events."""
        if event_type not in {"task", "decision"}:
            return None
        if isinstance(raw_status, str):
            normalized = raw_status.strip().lower()
            if normalized in {EPISODIC_STATUS_OPEN, EPISODIC_STATUS_RESOLVED}:
                return normalized
        return (
            EPISODIC_STATUS_RESOLVED
            if is_resolved_task_or_decision(summary)
            else EPISODIC_STATUS_OPEN
        )

    def coerce_event(
        self,
        raw: dict[str, Any],
        *,
        source_span: list[int],
        channel: str = "",
        chat_id: str = "",
    ) -> MemoryEvent | None:
        """Normalize a raw event dict into canonical form.

        Returns ``None`` if the event is invalid (e.g. missing summary).
        """
        summary = raw.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        event_type = raw.get("type") if isinstance(raw.get("type"), str) else "fact"
        event_type = event_type if event_type in EVENT_TYPES else "fact"
        _raw_ts = raw.get("timestamp")
        timestamp: str = _raw_ts if isinstance(_raw_ts, str) else _utc_now_iso()
        salience = min(max(_safe_float(raw.get("salience"), 0.6), 0.0), 1.0)
        confidence = min(max(_safe_float(raw.get("confidence"), 0.7), 0.0), 1.0)
        entities = _to_str_list(raw.get("entities"))
        ttl_days = raw.get("ttl_days")
        if not isinstance(ttl_days, int) or ttl_days <= 0:
            ttl_days = None
        source = str(raw.get("source", "chat")).strip().lower() or "chat"
        status = self.infer_episodic_status(
            event_type=event_type,
            summary=summary.strip(),
            raw_status=raw.get("status"),
        )
        metadata_input = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None
        metadata, _ = self._classifier.normalize_memory_metadata(
            metadata_input,
            event_type=event_type,
            summary=summary.strip(),
            source=source,
        )
        if ttl_days is not None:
            metadata["ttl_days"] = ttl_days

        event_id = raw.get("id") if isinstance(raw.get("id"), str) else ""
        if not event_id:
            event_id = self.build_event_id(event_type, summary, timestamp)

        # Parse optional triples (knowledge-graph edges).
        raw_triples = raw.get("triples")
        triples: list[dict[str, Any]] = []
        if isinstance(raw_triples, list):
            for t in raw_triples:
                if isinstance(t, dict) and t.get("subject") and t.get("object"):
                    triples.append(
                        {
                            "subject": str(t["subject"]).strip(),
                            "predicate": str(t.get("predicate", "RELATED_TO")).strip(),
                            "object": str(t["object"]).strip(),
                            "confidence": min(
                                max(_safe_float(t.get("confidence"), confidence), 0.0), 1.0
                            ),
                        }
                    )

        return MemoryEvent.from_dict(
            {
                "id": event_id,
                "timestamp": timestamp,
                "channel": channel,
                "chat_id": chat_id,
                "type": event_type,
                "summary": summary.strip(),
                "entities": entities,
                "salience": salience,
                "confidence": confidence,
                "source_span": source_span,
                "ttl_days": ttl_days,
                "memory_type": metadata.get("memory_type", "episodic"),
                "topic": metadata.get(
                    "topic", self._classifier.default_topic_for_event_type(event_type)
                ),
                "stability": metadata.get("stability", "medium"),
                "source": metadata.get("source", source),
                "evidence_refs": metadata.get("evidence_refs", []),
                "status": status,
                "metadata": metadata,
                "triples": triples,
            }
        )

    def ensure_event_provenance(self, event: dict[str, Any]) -> dict[str, Any]:
        """Enrich an event with full provenance metadata."""
        event_copy = dict(event)
        event_type = str(event_copy.get("type", "fact"))
        summary = str(event_copy.get("summary", ""))
        source = str(event_copy.get("source", "chat"))
        metadata_input = (
            event_copy.get("metadata") if isinstance(event_copy.get("metadata"), dict) else None
        )
        metadata, _ = self._classifier.normalize_memory_metadata(
            metadata_input,
            event_type=event_type,
            summary=summary,
            source=source,
        )
        if isinstance(event_copy.get("ttl_days"), int) and int(event_copy.get("ttl_days", 0)) > 0:
            metadata["ttl_days"] = int(event_copy["ttl_days"])
        if not isinstance(event_copy.get("evidence_refs"), list):
            event_copy["evidence_refs"] = metadata.get("evidence_refs", [])
        current_memory_type = str(event_copy.get("memory_type", "")).strip().lower()
        event_copy["memory_type"] = (
            current_memory_type
            if current_memory_type in MEMORY_TYPES
            else str(metadata.get("memory_type", "episodic"))
        )
        event_copy["topic"] = str(
            event_copy.get("topic")
            or metadata.get("topic", self._classifier.default_topic_for_event_type(event_type))
        )
        current_stability = str(event_copy.get("stability", "")).strip().lower()
        event_copy["stability"] = (
            current_stability
            if current_stability in MEMORY_STABILITY
            else str(metadata.get("stability", "medium"))
        )
        event_copy["source"] = (
            str(event_copy.get("source") or metadata.get("source", "chat")).strip().lower()
            or "chat"
        )
        normalized_status = self.infer_episodic_status(
            event_type=event_type,
            summary=summary,
            raw_status=event_copy.get("status"),
        )
        event_copy["status"] = normalized_status
        merged_metadata = dict(metadata_input or {})
        merged_metadata.update(metadata)
        if normalized_status:
            merged_metadata["status"] = normalized_status
        event_copy["metadata"] = merged_metadata
        event_id = str(event_copy.get("id", "")).strip()
        if not event_id:
            return event_copy

        event_copy.setdefault("canonical_id", event_id)
        aliases = event_copy.get("aliases")
        if not isinstance(aliases, list):
            aliases = []
        summary = str(event_copy.get("summary", "")).strip()
        if summary and summary not in aliases:
            aliases.append(summary)
        event_copy["aliases"] = aliases

        evidence = event_copy.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
        if not evidence:
            evidence.append(
                {
                    "event_id": event_id,
                    "timestamp": str(event_copy.get("timestamp", "")),
                    "summary": summary,
                    "source_span": event_copy.get("source_span"),
                    "confidence": _safe_float(event_copy.get("confidence"), 0.7),
                    "salience": _safe_float(event_copy.get("salience"), 0.6),
                }
            )
        event_copy["evidence"] = evidence
        event_copy["merged_event_count"] = max(int(event_copy.get("merged_event_count", 1)), 1)
        return event_copy
