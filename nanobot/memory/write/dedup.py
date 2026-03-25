"""Event deduplication and merge logic.

Extracted from ``EventIngester`` — owns similarity computation, duplicate
detection, supersession detection, and event merging.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from .._text import _norm_text, _safe_float, _to_datetime, _to_str_list, _tokenize, _utc_now_iso
from ..event import memory_type_for_item

if TYPE_CHECKING:
    from .coercion import EventCoercer


class EventDeduplicator:
    """Detects duplicates and supersessions, merges events."""

    def __init__(
        self,
        coercer: EventCoercer,
        conflict_pair_fn: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._coercer = coercer
        self._conflict_pair_fn = conflict_pair_fn

    @staticmethod
    def event_similarity(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
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

    def find_semantic_duplicate(
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
            lexical, semantic = self.event_similarity(candidate, existing)
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

    def find_semantic_supersession(
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

            lexical, semantic = self.event_similarity(candidate, existing)
            if lexical >= 0.35 or semantic >= 0.35:
                return idx
        return None

    def merge_events(
        self,
        base: dict[str, Any],
        incoming: dict[str, Any],
        *,
        similarity: float,
    ) -> dict[str, Any]:
        """Merge *incoming* into *base*, unioning entities and averaging confidence."""
        canonical = self._coercer.ensure_event_provenance(base)
        candidate = self._coercer.ensure_event_provenance(incoming)

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
        merged["source_span"] = self.merge_source_span(
            canonical.get("source_span"), candidate.get("source_span")
        )
        merged["confidence"] = min(max((c_conf + i_conf) / 2.0 + 0.03, 0.0), 1.0)
        merged["salience"] = min(max(max(c_sal, i_sal), 0.0), 1.0)
        merged["merged_event_count"] = merged_count
        merged["last_merged_at"] = _utc_now_iso()
        merged["last_dedup_score"] = round(similarity, 4)
        merged["canonical_id"] = str(canonical.get("canonical_id") or canonical.get("id", ""))
        merged_status = self._coercer.infer_episodic_status(
            event_type=str(merged.get("type", "")),
            summary=str(merged.get("summary", "")),
            raw_status=merged.get("status"),
        )
        incoming_status = self._coercer.infer_episodic_status(
            event_type=str(candidate.get("type", "")),
            summary=str(candidate.get("summary", "")),
            raw_status=candidate.get("status"),
        )
        if merged_status in {
            self._coercer.EPISODIC_STATUS_OPEN,
            self._coercer.EPISODIC_STATUS_RESOLVED,
        }:
            if incoming_status == self._coercer.EPISODIC_STATUS_RESOLVED:
                merged["status"] = self._coercer.EPISODIC_STATUS_RESOLVED
                merged["resolved_at"] = str(candidate.get("timestamp", _utc_now_iso()))
            else:
                merged["status"] = merged_status

        canonical_ts = _to_datetime(str(canonical.get("timestamp", "")))
        candidate_ts = _to_datetime(str(candidate.get("timestamp", "")))
        if canonical_ts and candidate_ts and candidate_ts > canonical_ts:
            merged["timestamp"] = str(candidate.get("timestamp", merged.get("timestamp", "")))
        return merged

    @staticmethod
    def merge_source_span(base: list[int] | Any, incoming: list[int] | Any) -> list[int]:
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
