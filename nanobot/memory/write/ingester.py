"""Event ingestion pipeline for the memory subsystem.

Extracts the complete event write path from ``MemoryStore`` into a focused
module.  ``EventIngester`` owns:

- Event coercion and ID generation
- Classification and metadata enrichment
- Deduplication and merge logic
- Persistence writes (events.jsonl)
- mem0 sync for structured events
- Knowledge graph triple ingestion

All file I/O goes through ``MemoryPersistence``; all vector operations go
through ``_Mem0Adapter``.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import TYPE_CHECKING, Any, Callable

from nanobot.observability.tracing import bind_trace

from .._text import (
    _contains_any,
    _norm_text,
    _safe_float,
    _to_datetime,
    _to_str_list,
    _tokenize,
    _utc_now_iso,
)
from ..event import is_resolved_task_or_decision, memory_type_for_item

if TYPE_CHECKING:
    from ..embedder import Embedder
    from ..graph.graph import KnowledgeGraph
    from ..unified_db import UnifiedMemoryDB

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVENT_TYPES: set[str] = {"preference", "fact", "task", "decision", "constraint", "relationship"}
MEMORY_TYPES: set[str] = {"semantic", "episodic", "reflection"}
MEMORY_STABILITY: set[str] = {"high", "medium", "low"}
EPISODIC_STATUS_OPEN: str = "open"
EPISODIC_STATUS_RESOLVED: str = "resolved"


class EventIngester:
    """Owns the full event write path: coerce → dedup → persist → sync."""

    # Class-level aliases so external code can reference ``EventIngester.EVENT_TYPES`` etc.
    EVENT_TYPES = EVENT_TYPES
    MEMORY_TYPES = MEMORY_TYPES
    MEMORY_STABILITY = MEMORY_STABILITY
    EPISODIC_STATUS_OPEN = EPISODIC_STATUS_OPEN
    EPISODIC_STATUS_RESOLVED = EPISODIC_STATUS_RESOLVED

    def __init__(
        self,
        graph: KnowledgeGraph | None,
        rollout: dict[str, Any],
        *,
        conflict_pair_fn: Callable[[str, str], bool] | None = None,
        db: UnifiedMemoryDB | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._graph = graph
        self._rollout = rollout
        self._conflict_pair_fn = conflict_pair_fn
        self._db = db
        self._embedder = embedder

    # ------------------------------------------------------------------
    # Event coercion & ID building
    # ------------------------------------------------------------------

    @staticmethod
    def _build_event_id(event_type: str, summary: str, timestamp: str) -> str:
        """Generate a deterministic hash-based event ID."""
        raw = f"{_norm_text(event_type)}|{_norm_text(summary)}|{timestamp[:16]}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _infer_episodic_status(
        self, *, event_type: str, summary: str, raw_status: Any = None
    ) -> str | None:
        """Infer episodic status (open/resolved) for task/decision events."""
        if event_type not in {"task", "decision"}:
            return None
        if isinstance(raw_status, str):
            normalized = raw_status.strip().lower()
            if normalized in {self.EPISODIC_STATUS_OPEN, self.EPISODIC_STATUS_RESOLVED}:
                return normalized
        return (
            self.EPISODIC_STATUS_RESOLVED
            if is_resolved_task_or_decision(summary)
            else self.EPISODIC_STATUS_OPEN
        )

    def _coerce_event(
        self,
        raw: dict[str, Any],
        *,
        source_span: list[int],
        channel: str = "",
        chat_id: str = "",
    ) -> dict[str, Any] | None:
        """Normalize a raw event dict into canonical form.

        Returns ``None`` if the event is invalid (e.g. missing summary).
        """
        summary = raw.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        event_type = raw.get("type") if isinstance(raw.get("type"), str) else "fact"
        event_type = event_type if event_type in self.EVENT_TYPES else "fact"
        _raw_ts = raw.get("timestamp")
        timestamp: str = _raw_ts if isinstance(_raw_ts, str) else _utc_now_iso()
        salience = min(max(_safe_float(raw.get("salience"), 0.6), 0.0), 1.0)
        confidence = min(max(_safe_float(raw.get("confidence"), 0.7), 0.0), 1.0)
        entities = _to_str_list(raw.get("entities"))
        ttl_days = raw.get("ttl_days")
        if not isinstance(ttl_days, int) or ttl_days <= 0:
            ttl_days = None
        source = str(raw.get("source", "chat")).strip().lower() or "chat"
        status = self._infer_episodic_status(
            event_type=event_type,
            summary=summary.strip(),
            raw_status=raw.get("status"),
        )
        metadata_input = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None
        metadata, _ = self._normalize_memory_metadata(
            metadata_input,
            event_type=event_type,
            summary=summary.strip(),
            source=source,
        )
        if ttl_days is not None:
            metadata["ttl_days"] = ttl_days

        event_id = raw.get("id") if isinstance(raw.get("id"), str) else ""
        if not event_id:
            event_id = self._build_event_id(event_type, summary, timestamp)

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

        return {
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
            "topic": metadata.get("topic", self._default_topic_for_event_type(event_type)),
            "stability": metadata.get("stability", "medium"),
            "source": metadata.get("source", source),
            "evidence_refs": metadata.get("evidence_refs", []),
            "status": status,
            "metadata": metadata,
            "triples": triples,
        }

    # ------------------------------------------------------------------
    # Classification & metadata
    # ------------------------------------------------------------------

    @staticmethod
    def _default_topic_for_event_type(event_type: str) -> str:
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

    def _classify_memory_type(
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
    def _distill_semantic_summary(summary: str) -> str:
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

    def _normalize_memory_metadata(
        self,
        metadata: dict[str, Any] | None,
        *,
        event_type: str,
        summary: str,
        source: str,
    ) -> tuple[dict[str, Any], bool]:
        """Enrich event metadata with classification, topic, stability, etc."""
        payload = dict(metadata or {})
        memory_type, default_stability, is_mixed = self._classify_memory_type(
            event_type=event_type,
            summary=summary,
            source=source,
        )

        topic = str(payload.get("topic", "")).strip() or self._default_topic_for_event_type(
            event_type
        )
        raw_type = str(payload.get("memory_type", "")).strip().lower()
        if raw_type in self.MEMORY_TYPES:
            memory_type = raw_type

        stability = str(payload.get("stability", default_stability)).strip().lower()
        if stability not in self.MEMORY_STABILITY:
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

    def _event_mem0_write_plan(self, event: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """Plan mem0 writes for an event, handling mixed semantic/episodic splits."""
        summary = str(event.get("summary", "")).strip()
        if not summary:
            return []
        event_type = str(event.get("type", "fact"))
        base_source = str(event.get("source", "chat"))
        metadata, is_mixed = self._normalize_memory_metadata(
            event.get("metadata") if isinstance(event.get("metadata"), dict) else None,
            event_type=event_type,
            summary=summary,
            source=base_source,
        )
        merged = {
            **metadata,
            "event_type": event_type,
            "entities": _to_str_list(event.get("entities")),
            "source_span": event.get("source_span"),
            "channel": str(event.get("channel", "")),
            "chat_id": str(event.get("chat_id", "")),
            "canonical_id": str(event.get("canonical_id") or event.get("id", "")),
            "status": event.get("status"),
            "supersedes_event_id": event.get("supersedes_event_id"),
            "supersedes_at": event.get("supersedes_at"),
        }
        writes: list[tuple[str, dict[str, Any]]] = []

        if is_mixed:
            episodic_meta = dict(merged)
            episodic_meta["memory_type"] = "episodic"
            episodic_meta["stability"] = "low"
            writes.append((summary, episodic_meta))

            semantic_summary = self._distill_semantic_summary(summary)
            if semantic_summary:
                semantic_meta = dict(merged)
                semantic_meta["memory_type"] = "semantic"
                semantic_meta["stability"] = "high"
                semantic_meta["dual_write_parent_id"] = episodic_meta.get("canonical_id")
                writes.append((semantic_summary, semantic_meta))
            return writes

        writes.append((summary, merged))
        return writes

    @staticmethod
    def _looks_blob_like_summary(summary: str) -> bool:
        """Return ``True`` if *summary* looks like a data blob rather than prose."""
        text = str(summary or "").strip()
        if not text:
            return True
        lowered = text.lower()
        blob_markers = (
            "[runtime context]",
            "/home/",
            ".jsonl:",
            "```",
            "{",
            "}",
            "# memory",
            "## ",
        )
        if any(marker in lowered for marker in blob_markers):
            return True
        if text.count("\n") >= 4:
            return True
        return False

    @staticmethod
    def _sanitize_mem0_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        """Strip ``None`` values and flatten non-scalar types for mem0."""
        clean: dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, str | int | float | bool):
                clean[key] = value
                continue
            if isinstance(value, list):
                items: list[str | int | float | bool] = []
                for item in value:
                    if isinstance(item, str | int | float | bool):
                        items.append(item)
                    elif item is not None:
                        items.append(str(item))
                clean[key] = items
                continue
            clean[key] = str(value)
        return clean

    def _sanitize_mem0_text(self, text: str, *, allow_archival: bool = False) -> str:
        """Strip runtime context markers and enforce length limits."""
        value = str(text or "")
        if not value.strip():
            return ""
        if "[Runtime Context]" in value:
            value = value.split("[Runtime Context]", 1)[0]
        value = re.sub(r"\s+", " ", value).strip()
        max_chars = int(self._rollout.get("memory_fallback_max_summary_chars", 280) or 280)
        if len(value) > max_chars and not allow_archival:
            return ""
        if len(value) > max_chars and allow_archival:
            value = value[:max_chars].rstrip() + "..."
        if self._looks_blob_like_summary(value):
            return ""
        return value

    # ------------------------------------------------------------------
    # Dedup & merge
    # ------------------------------------------------------------------

    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Read events from UnifiedMemoryDB.

        Extra fields packed into metadata._extra on write are unpacked back
        to top-level keys so callers see the same dict shape as was stored.
        """
        if self._db is not None:
            import json as _json

            rows = self._db.read_events(limit=limit or 100)
            result: list[dict[str, Any]] = []
            for row in rows:
                event = dict(row)
                raw_meta = event.get("metadata")
                if isinstance(raw_meta, str):
                    try:
                        meta = _json.loads(raw_meta)
                    except (ValueError, TypeError):
                        meta = {}
                else:
                    meta = raw_meta if isinstance(raw_meta, dict) else {}
                extras = meta.pop("_extra", None) if isinstance(meta, dict) else None
                if isinstance(extras, dict):
                    event.update(extras)
                if meta:
                    event["metadata"] = meta
                result.append(event)
            return result
        return []

    @staticmethod
    def _merge_source_span(base: list[int] | Any, incoming: list[int] | Any) -> list[int]:
        """Merge two source spans into a single span covering both."""
        base_span = (
            base
            if isinstance(base, list) and len(base) == 2 and all(isinstance(x, int) for x in base)
            else [0, 0]
        )
        incoming_span = (
            incoming
            if isinstance(incoming, list)
            and len(incoming) == 2
            and all(isinstance(x, int) for x in incoming)
            else base_span
        )
        return [min(base_span[0], incoming_span[0]), max(base_span[1], incoming_span[1])]

    def _ensure_event_provenance(self, event: dict[str, Any]) -> dict[str, Any]:
        """Enrich an event with full provenance metadata."""
        event_copy = dict(event)
        event_type = str(event_copy.get("type", "fact"))
        summary = str(event_copy.get("summary", ""))
        source = str(event_copy.get("source", "chat"))
        metadata_input = (
            event_copy.get("metadata") if isinstance(event_copy.get("metadata"), dict) else None
        )
        metadata, _ = self._normalize_memory_metadata(
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
            if current_memory_type in self.MEMORY_TYPES
            else str(metadata.get("memory_type", "episodic"))
        )
        event_copy["topic"] = str(
            event_copy.get("topic")
            or metadata.get("topic", self._default_topic_for_event_type(event_type))
        )
        current_stability = str(event_copy.get("stability", "")).strip().lower()
        event_copy["stability"] = (
            current_stability
            if current_stability in self.MEMORY_STABILITY
            else str(metadata.get("stability", "medium"))
        )
        event_copy["source"] = (
            str(event_copy.get("source") or metadata.get("source", "chat")).strip().lower()
            or "chat"
        )
        normalized_status = self._infer_episodic_status(
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

    @staticmethod
    def _event_similarity(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
        """Compute Jaccard similarity between two events (lexical, semantic)."""

        def _event_text(event: dict[str, Any]) -> str:
            summary = str(event.get("summary", ""))
            entities = " ".join(_to_str_list(event.get("entities")))
            event_type = str(event.get("type", "fact"))
            return f"{event_type}. {summary}. {entities}".strip()

        left_text = _event_text(left)
        right_text = _event_text(right)

        left_tokens = _tokenize(left_text)
        right_tokens = _tokenize(right_text)
        overlap = left_tokens & right_tokens
        union = left_tokens | right_tokens
        lexical = (len(overlap) / len(union)) if union else 0.0
        semantic = lexical
        return lexical, semantic

    def _find_semantic_duplicate(
        self,
        candidate: dict[str, Any],
        existing_events: list[dict[str, Any]],
    ) -> tuple[int | None, float]:
        """Find an existing event that is a semantic duplicate of *candidate*."""
        best_idx: int | None = None
        best_score = 0.0
        candidate_type = str(candidate.get("type", ""))

        for idx, existing in enumerate(existing_events):
            if str(existing.get("type", "")) != candidate_type:
                continue
            lexical, semantic = self._event_similarity(candidate, existing)
            candidate_entities = {_norm_text(x) for x in _to_str_list(candidate.get("entities"))}
            existing_entities = {_norm_text(x) for x in _to_str_list(existing.get("entities"))}
            entity_overlap = 0.0
            if candidate_entities and existing_entities:
                entity_overlap = len(candidate_entities & existing_entities) / max(
                    len(candidate_entities | existing_entities), 1
                )

            score = 0.4 * semantic + 0.45 * lexical + 0.15 * entity_overlap
            is_duplicate = (
                lexical >= 0.84
                or semantic >= 0.94
                or (lexical >= 0.6 and semantic >= 0.86)
                or (entity_overlap >= 0.33 and (lexical >= 0.42 or semantic >= 0.52))
                or (
                    entity_overlap >= 0.30
                    and lexical >= 0.25
                    and candidate_type == str(existing.get("type", ""))
                )
            )
            if not is_duplicate:
                continue
            if score > best_score:
                best_score = score
                best_idx = idx

        return best_idx, best_score

    def _find_semantic_supersession(
        self,
        candidate: dict[str, Any],
        existing_events: list[dict[str, Any]],
    ) -> int | None:
        """Find an existing event that the *candidate* supersedes (contradicts)."""
        if memory_type_for_item(candidate) != "semantic":
            return None
        candidate_summary = str(candidate.get("summary", "")).strip()
        candidate_type = str(candidate.get("type", ""))
        if not candidate_summary:
            return None

        for idx, existing in enumerate(existing_events):
            if memory_type_for_item(existing) != "semantic":
                continue
            if str(existing.get("type", "")) != candidate_type:
                continue
            if str(existing.get("status", "")).strip().lower() == "superseded":
                continue

            existing_summary = str(existing.get("summary", "")).strip()
            if not existing_summary:
                continue
            has_conflict = (
                self._conflict_pair_fn(existing_summary, candidate_summary)
                if self._conflict_pair_fn
                else False
            )
            if not has_conflict:
                existing_norm = _norm_text(existing_summary)
                candidate_norm = _norm_text(candidate_summary)
                existing_not = " not " in f" {existing_norm} " or "n't" in existing_norm
                candidate_not = " not " in f" {candidate_norm} " or "n't" in candidate_norm
                if existing_not != candidate_not:
                    stop = {"do", "does", "did"}
                    left_tokens = {
                        t for t in _tokenize(existing_norm.replace("not", "")) if t not in stop
                    }
                    right_tokens = {
                        t for t in _tokenize(candidate_norm.replace("not", "")) if t not in stop
                    }
                    if left_tokens and right_tokens:
                        overlap = len(left_tokens & right_tokens) / max(
                            len(left_tokens | right_tokens), 1
                        )
                        has_conflict = overlap >= 0.45
            if not has_conflict:
                continue

            lexical, semantic = self._event_similarity(candidate, existing)
            if lexical >= 0.35 or semantic >= 0.35:
                return idx
        return None

    def _merge_events(
        self,
        base: dict[str, Any],
        incoming: dict[str, Any],
        *,
        similarity: float,
    ) -> dict[str, Any]:
        """Merge *incoming* into *base*, unioning entities and averaging confidence."""
        canonical = self._ensure_event_provenance(base)
        candidate = self._ensure_event_provenance(incoming)

        entities = list(
            dict.fromkeys(
                _to_str_list(canonical.get("entities")) + _to_str_list(candidate.get("entities"))
            )
        )
        aliases = list(
            dict.fromkeys(
                _to_str_list(canonical.get("aliases")) + _to_str_list(candidate.get("aliases"))
            )
        )
        _raw_evidence_c = canonical.get("evidence")
        evidence: list[Any] = _raw_evidence_c if isinstance(_raw_evidence_c, list) else []
        _raw_evidence_i = candidate.get("evidence")
        cand_evidence: list[Any] = _raw_evidence_i if isinstance(_raw_evidence_i, list) else []
        evidence.extend(cand_evidence)
        if len(evidence) > 20:
            evidence = evidence[-20:]

        merged_count = max(int(canonical.get("merged_event_count", 1)), 1) + 1
        c_conf = _safe_float(canonical.get("confidence"), 0.7)
        i_conf = _safe_float(candidate.get("confidence"), 0.7)
        c_sal = _safe_float(canonical.get("salience"), 0.6)
        i_sal = _safe_float(candidate.get("salience"), 0.6)

        merged = dict(canonical)
        merged["summary"] = str(canonical.get("summary") or candidate.get("summary") or "")
        merged["entities"] = entities
        merged["aliases"] = aliases
        merged["evidence"] = evidence
        merged["source_span"] = self._merge_source_span(
            canonical.get("source_span"), candidate.get("source_span")
        )
        merged["confidence"] = min(max((c_conf + i_conf) / 2.0 + 0.03, 0.0), 1.0)
        merged["salience"] = min(max(max(c_sal, i_sal), 0.0), 1.0)
        merged["merged_event_count"] = merged_count
        merged["last_merged_at"] = _utc_now_iso()
        merged["last_dedup_score"] = round(similarity, 4)
        merged["canonical_id"] = str(canonical.get("canonical_id") or canonical.get("id", ""))
        merged_status = self._infer_episodic_status(
            event_type=str(merged.get("type", "")),
            summary=str(merged.get("summary", "")),
            raw_status=merged.get("status"),
        )
        incoming_status = self._infer_episodic_status(
            event_type=str(candidate.get("type", "")),
            summary=str(candidate.get("summary", "")),
            raw_status=candidate.get("status"),
        )
        if merged_status in {self.EPISODIC_STATUS_OPEN, self.EPISODIC_STATUS_RESOLVED}:
            if incoming_status == self.EPISODIC_STATUS_RESOLVED:
                merged["status"] = self.EPISODIC_STATUS_RESOLVED
                merged["resolved_at"] = str(candidate.get("timestamp", _utc_now_iso()))
            else:
                merged["status"] = merged_status

        canonical_ts = _to_datetime(str(canonical.get("timestamp", "")))
        candidate_ts = _to_datetime(str(candidate.get("timestamp", "")))
        if canonical_ts and candidate_ts and candidate_ts > canonical_ts:
            merged["timestamp"] = str(candidate.get("timestamp", merged.get("timestamp", "")))
        return merged

    def append_events(self, events: list[dict[str, Any]]) -> int:
        """Main ingestion entry point: dedup, merge, persist, and sync to mem0."""
        if not events:
            return 0
        t0_append = time.monotonic()
        existing_events = [self._ensure_event_provenance(event) for event in self.read_events()]
        existing_ids = {e.get("id") for e in existing_events if e.get("id")}
        written = 0
        merged = 0
        superseded = 0
        appended_events: list[dict[str, Any]] = []

        for raw in events:
            event_id = raw.get("id")
            if not event_id:
                # Auto-generate ID for events without one (mirrors _coerce_event).
                summary = str(raw.get("summary", "")).strip()
                if not summary:
                    continue
                event_type = str(raw.get("type", "fact"))
                ts = str(raw.get("timestamp", _utc_now_iso()))
                event_id = self._build_event_id(event_type, summary, ts)
                raw = {**raw, "id": event_id}
            candidate = self._ensure_event_provenance(raw)

            if event_id in existing_ids:
                for idx, existing in enumerate(existing_events):
                    if existing.get("id") == event_id:
                        existing_events[idx] = self._merge_events(
                            existing, candidate, similarity=1.0
                        )
                        merged += 1
                        break
                continue

            superseded_idx = self._find_semantic_supersession(candidate, existing_events)
            if superseded_idx is not None:
                now_iso = _utc_now_iso()
                superseded_event = dict(existing_events[superseded_idx])
                superseded_id = str(superseded_event.get("id", "")).strip()
                superseded_event["status"] = "superseded"
                superseded_event["superseded_at"] = now_iso
                if event_id:
                    superseded_event["superseded_by_event_id"] = event_id
                existing_events[superseded_idx] = superseded_event
                if superseded_id:
                    candidate["supersedes_event_id"] = superseded_id
                candidate["supersedes_at"] = now_iso
                existing_ids.add(event_id)
                existing_events.append(candidate)
                appended_events.append(candidate)
                written += 1
                superseded += 1
                continue

            dup_idx, dup_score = self._find_semantic_duplicate(candidate, existing_events)
            if dup_idx is not None:
                existing_events[dup_idx] = self._merge_events(
                    existing_events[dup_idx], candidate, similarity=dup_score
                )
                merged += 1
                continue

            existing_ids.add(event_id)
            existing_events.append(candidate)
            appended_events.append(candidate)
            written += 1

        if written <= 0 and merged <= 0:
            return 0

        # Write to UnifiedMemoryDB
        if self._db is not None:
            import json as _json

            # Collect all events that need writing: newly appended or modified
            # (merged/superseded). Use existing_events which has the final state
            # after all in-memory merges.
            appended_ids = {a.get("id") for a in appended_events}
            events_to_write = [
                e
                for e in existing_events
                if e.get("id") in appended_ids
                or e.get("merged_event_count", 1) > 1
                or e.get("status") == "superseded"
            ]

            for event in events_to_write:
                # Events are inserted without embeddings in the sync write path.
                # Embeddings are backfilled by maintenance.reindex() or by the
                # caller via db.insert_event() with a pre-computed embedding.
                embedding = None
                # Pack extra fields (entities, triples, confidence, salience,
                # source_span, etc.) into metadata JSON so they survive the
                # SQLite round-trip through the fixed-column events table.
                evt_copy = dict(event)
                _db_columns = {
                    "id",
                    "type",
                    "summary",
                    "timestamp",
                    "source",
                    "status",
                    "metadata",
                    "created_at",
                }
                meta = evt_copy.get("metadata")
                meta = meta if isinstance(meta, dict) else {}
                extras = {k: v for k, v in evt_copy.items() if k not in _db_columns}
                if extras:
                    meta = {**meta, "_extra": extras}
                evt_copy["metadata"] = _json.dumps(meta) if meta else None
                evt_copy.setdefault("created_at", evt_copy.get("timestamp", _utc_now_iso()))
                self._db.insert_event(evt_copy, embedding=embedding)
        bind_trace().debug(
            "memory_append | written={} | merged={} | superseded={} | {:.0f}ms",
            written,
            merged,
            superseded,
            (time.monotonic() - t0_append) * 1000,
        )
        return written

    async def _ingest_graph_triples(self, events: list[dict[str, Any]]) -> int:
        """Feed triples from events into the knowledge graph (async).

        Returns the number of triples ingested.  No-op when graph is disabled.
        """
        if not self._graph or not self._graph.enabled:
            return 0

        from ..graph.ontology_types import Triple

        total = 0
        for event in events:
            raw_triples = event.get("triples")
            if not isinstance(raw_triples, list) or not raw_triples:
                continue
            event_id = str(event.get("id", ""))
            timestamp = str(event.get("timestamp", ""))
            parsed = [Triple.from_dict(t, source_event_id=event_id) for t in raw_triples]
            parsed = [t for t in parsed if t.subject and t.object]
            if parsed:
                await self._graph.ingest_event_triples(event_id, parsed, timestamp=timestamp)
                total += len(parsed)

        return total

    # ------------------------------------------------------------------
    # Mem0 sync
    # ------------------------------------------------------------------

    def _sync_events_to_mem0(self, events: list[dict[str, Any]]) -> int:
        """No-op: events are stored directly in UnifiedMemoryDB.

        Legacy mem0 sync has been removed.  Returns 0.
        """
        return 0
