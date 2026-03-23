"""Evaluation and observability helpers extracted from MemoryStore.

``EvalRunner`` encapsulates retrieval-quality evaluation, rollout gate
checking, and observability reporting.  It is instantiated by
``MemoryStore`` and delegates back via callables so that no direct
import cycle is introduced.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.agent.memory.helpers import _safe_float, _utc_now_iso
from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.agent.memory.unified_db import UnifiedMemoryDB

class EvalRunner:
    """Retrieval evaluation, rollout-gate checking, and observability reports."""

    def __init__(
        self,
        retrieve_fn: Callable[..., list[dict[str, Any]]],
        workspace: Path,
        memory_dir: Path,
        *,
        get_rollout_status_fn: Callable[[], dict[str, Any]],
        get_rollout_fn: Callable[[], dict[str, Any]],
        get_backend_stats_fn: Callable[[], dict[str, Any]],
        db: UnifiedMemoryDB | None = None,
    ) -> None:
        self._retrieve = retrieve_fn
        self.workspace = workspace
        self.memory_dir = memory_dir
        self._get_rollout_status = get_rollout_status_fn
        self._get_rollout = get_rollout_fn
        self._get_backend_stats = get_backend_stats_fn
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_observability_report(self) -> dict[str, Any]:
        """Return backend health and rollout status.

        Legacy per-counter metrics have been removed in favour of Langfuse.
        The ``metrics`` and ``kpis`` keys are kept empty for backward
        compatibility with callers that destructure the return value.
        """
        stats = self._get_backend_stats()
        vector_points_count = stats["vector_points_count"]
        mem0_get_all_count = stats["mem0_get_all_count"]
        history_rows_count = stats["history_rows_count"]
        mem0_enabled = stats["mem0_enabled"]
        mem0_mode = stats["mem0_mode"]

        vector_health_state = (
            "degraded"
            if (history_rows_count > 0 and vector_points_count == 0 and mem0_get_all_count == 0)
            else "healthy"
        )

        return {
            "metrics": {},
            "kpis": {},
            "backend": {
                "mem0_enabled": mem0_enabled,
                "mem0_mode": mem0_mode,
                "vector_points_count": vector_points_count,
                "mem0_get_all_count": mem0_get_all_count,
                "history_rows_count": history_rows_count,
                "vector_health_state": vector_health_state,
            },
            "rollout": self._get_rollout_status(),
        }

    def evaluate_retrieval_cases(
        self,
        cases: list[dict[str, Any]],
        *,
        default_top_k: int = 6,
        recency_half_life_days: float | None = None,
        embedding_provider: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate retrieval quality using labeled cases.

        Case format (each dict):
        - query: str (required)
        - expected_ids: list[str] (optional)
        - expected_any: list[str] substrings expected in retrieved summaries (optional)
        - expected_topics: list[str] expected topic substrings (optional)
        - expected_memory_types: list[str] expected memory_type values (optional)
        - expected_status_any: list[str] expected status substrings (optional)
        - expected_any_mode: "substring" | "normalized" (optional)
        - required_min_hits: int minimum matched expectations for full recall (optional)
        - top_k: int (optional)
        """
        valid_cases = [
            c
            for c in cases
            if isinstance(c, dict)
            and isinstance(c.get("query"), str)
            and c.get("query", "").strip()
        ]
        if not valid_cases:
            return {
                "cases": 0,
                "evaluated": [],
                "summary": {
                    "recall_at_k": 0.0,
                    "precision_at_k": 0.0,
                },
            }

        total_expected = 0
        total_found = 0
        total_relevant_retrieved = 0
        total_retrieved_slots = 0
        evaluated: list[dict[str, Any]] = []

        synonym_map = {
            "failed": "fail",
            "failure": "fail",
            "failing": "fail",
            "constraints": "constraint",
            "resolved": "resolve",
            "completed": "resolve",
            "closed": "resolve",
            "learned": "lesson",
            "lessons": "lesson",
            "updates": "update",
            "corrected": "correct",
            "corrections": "correct",
            "correction": "correct",
            "preferences": "prefer",
            "preference": "prefer",
            "preferred": "prefer",
            "prefers": "prefer",
            "relationships": "relationship",
            "reflections": "reflection",
            "decisions": "decision",
            "tasks": "task",
            "incidents": "incident",
            "superseded": "supersede",
        }

        def _normalize_phrase(value: str) -> str:
            tokens = [t for t in re.findall(r"[a-z0-9_]+", str(value or "").lower()) if t]
            normalized = [synonym_map.get(tok, tok) for tok in tokens]
            return " ".join(normalized)

        for case in valid_cases:
            query = str(case.get("query", "")).strip()
            top_k = int(case.get("top_k", default_top_k) or default_top_k)
            top_k = max(1, min(top_k, 30))

            expected_ids = [
                str(x) for x in case.get("expected_ids", []) if isinstance(x, str) and x.strip()
            ]
            expected_any = [
                str(x).lower()
                for x in case.get("expected_any", [])
                if isinstance(x, str) and x.strip()
            ]
            expected_topics = [
                str(x).strip().lower()
                for x in case.get("expected_topics", [])
                if isinstance(x, str) and x.strip()
            ]
            expected_memory_types = [
                str(x).strip().lower()
                for x in case.get("expected_memory_types", [])
                if isinstance(x, str) and x.strip()
            ]
            expected_status_any = [
                str(x).strip().lower()
                for x in case.get("expected_status_any", [])
                if isinstance(x, str) and x.strip()
            ]
            expected_any_mode = str(case.get("expected_any_mode", "normalized")).strip().lower()
            if expected_any_mode not in {"substring", "normalized"}:
                expected_any_mode = "normalized"
            required_min_hits_raw = case.get("required_min_hits")
            try:
                required_min_hits = (
                    int(required_min_hits_raw) if required_min_hits_raw is not None else None
                )
            except (TypeError, ValueError):
                required_min_hits = None

            expected_any_norm = [_normalize_phrase(x) for x in expected_any if _normalize_phrase(x)]

            retrieved = self._retrieve(
                query,
                top_k=top_k,
                recency_half_life_days=recency_half_life_days,
                embedding_provider=embedding_provider,
            )

            hits = 0
            relevant_retrieved = 0
            matched_expected_tokens: set[str] = set()
            matched_topics: set[str] = set()
            matched_types: set[str] = set()
            matched_status: set[str] = set()

            for item in retrieved:
                summary = str(item.get("summary", "")).lower()
                summary_norm = _normalize_phrase(summary)
                event_id = str(item.get("id", ""))
                item_topic = str(item.get("topic", "")).strip().lower()
                item_type = str(item.get("memory_type", "")).strip().lower()
                item_status = str(item.get("status", "")).strip().lower()
                is_relevant = False

                for expected_id in expected_ids:
                    if expected_id == event_id:
                        matched_expected_tokens.add(f"id:{expected_id}")
                        is_relevant = True

                for expected_text in expected_any:
                    if expected_any_mode == "substring" and expected_text in summary:
                        matched_expected_tokens.add(f"txt:{expected_text}")
                        is_relevant = True
                if expected_any_mode == "normalized":
                    for expected_norm in expected_any_norm:
                        if expected_norm and expected_norm in summary_norm:
                            matched_expected_tokens.add(f"txtn:{expected_norm}")
                            is_relevant = True

                for expected_topic in expected_topics:
                    if expected_topic and expected_topic in item_topic:
                        matched_topics.add(expected_topic)
                        is_relevant = True

                for expected_type in expected_memory_types:
                    if expected_type and expected_type == item_type:
                        matched_types.add(expected_type)
                        is_relevant = True

                for expected_status in expected_status_any:
                    if expected_status and expected_status in item_status:
                        matched_status.add(expected_status)
                        is_relevant = True

                if is_relevant:
                    relevant_retrieved += 1

            expected_count = (
                len(expected_ids)
                + len(expected_any)
                + len(expected_topics)
                + len(expected_memory_types)
                + len(expected_status_any)
            )
            if expected_count > 0:
                hits = (
                    len(matched_expected_tokens)
                    + len(matched_topics)
                    + len(matched_types)
                    + len(matched_status)
                )
                total_expected += expected_count
                total_found += hits

            total_relevant_retrieved += relevant_retrieved
            total_retrieved_slots += top_k

            case_recall = (hits / expected_count) if expected_count else 0.0
            case_precision = (relevant_retrieved / top_k) if top_k > 0 else 0.0
            if required_min_hits is not None and expected_count > 0:
                effective_required = max(min(required_min_hits, expected_count), 0)
                case_recall = min(hits / max(effective_required, 1), 1.0)
            why_missed: list[str] = []
            if hits == 0:
                if not retrieved:
                    why_missed.append("no_candidate")
                else:
                    if expected_memory_types and not matched_types:
                        why_missed.append("wrong_type")
                    if expected_topics and not matched_topics:
                        why_missed.append("wrong_topic")
                    if expected_status_any and not matched_status:
                        why_missed.append("wrong_status")
                    if not why_missed:
                        why_missed.append("token_mismatch")
            evaluated.append(
                {
                    "query": query,
                    "top_k": top_k,
                    "expected": expected_count,
                    "hits": hits,
                    "retrieved": len(retrieved),
                    "case_recall_at_k": round(case_recall, 4),
                    "case_precision_at_k": round(case_precision, 4),
                    "why_missed": why_missed,
                }
            )

        overall_recall = (total_found / total_expected) if total_expected else 0.0
        overall_precision = (
            (total_relevant_retrieved / total_retrieved_slots) if total_retrieved_slots else 0.0
        )

        return {
            "cases": len(valid_cases),
            "evaluated": evaluated,
            "summary": {
                "recall_at_k": round(overall_recall, 4),
                "precision_at_k": round(overall_precision, 4),
            },
        }

    def save_evaluation_report(
        self,
        evaluation: dict[str, Any],
        observability: dict[str, Any],
        *,
        rollout: dict[str, Any] | None = None,
        output_file: str | None = None,
    ) -> Path:
        """Persist evaluation + observability report to disk and return the file path."""
        reports_dir = ensure_dir(self.memory_dir / "reports")
        if output_file:
            path = Path(output_file).expanduser().resolve()
            ensure_dir(path.parent)
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = reports_dir / f"memory_eval_{ts}.json"

        payload = {
            "generated_at": _utc_now_iso(),
            "evaluation": evaluation,
            "observability": observability,
            "rollout": rollout or self._get_rollout_status(),
        }
        import json as _json

        path.write_text(_json.dumps(payload, default=str, indent=2), encoding="utf-8")
        return path

    def evaluate_rollout_gates(
        self,
        evaluation: dict[str, Any],
        observability: dict[str, Any],
    ) -> dict[str, Any]:
        rollout = self._get_rollout()
        gates = rollout.get("rollout_gates", {})
        if not isinstance(gates, dict):
            gates = {}

        min_recall = _safe_float(gates.get("min_recall_at_k"), 0.55)
        min_precision = _safe_float(gates.get("min_precision_at_k"), 0.25)
        max_tokens = _safe_float(gates.get("max_avg_memory_context_tokens"), 1400.0)
        max_history_fallback_ratio = _safe_float(gates.get("max_history_fallback_ratio"), 0.05)

        summary = evaluation.get("summary", {}) if isinstance(evaluation, dict) else {}
        recall = _safe_float(summary.get("recall_at_k"), 0.0)
        precision = _safe_float(summary.get("precision_at_k"), 0.0)
        kpis = observability.get("kpis", {}) if isinstance(observability, dict) else {}
        avg_ctx_tokens = _safe_float(kpis.get("avg_memory_context_tokens"), 0.0)
        history_fallback_ratio = _safe_float(kpis.get("history_fallback_ratio"), 0.0)

        checks = [
            {
                "name": "recall_at_k",
                "actual": round(recall, 4),
                "threshold": round(min_recall, 4),
                "op": ">=",
                "passed": recall >= min_recall,
            },
            {
                "name": "precision_at_k",
                "actual": round(precision, 4),
                "threshold": round(min_precision, 4),
                "op": ">=",
                "passed": precision >= min_precision,
            },
            {
                "name": "avg_memory_context_tokens",
                "actual": round(avg_ctx_tokens, 2),
                "threshold": round(max_tokens, 2),
                "op": "<=",
                "passed": avg_ctx_tokens <= max_tokens,
            },
            {
                "name": "history_fallback_ratio",
                "actual": round(history_fallback_ratio, 4),
                "threshold": round(max_history_fallback_ratio, 4),
                "op": "<=",
                "passed": history_fallback_ratio <= max_history_fallback_ratio,
            },
        ]
        return {
            "passed": all(bool(item["passed"]) for item in checks),
            "checks": checks,
            "rollout_mode": str(rollout.get("memory_rollout_mode", "enabled")),
        }
