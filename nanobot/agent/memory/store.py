"""mem0-first memory store with structured profile/events maintenance.

This is the **primary public API** for all memory operations.  ``MemoryStore``
orchestrates the full lifecycle:

1. **Retrieval** — queries mem0 vector store first; falls back to local
   keyword search (``retrieval.py``) when mem0 is unavailable; optionally
   re-ranks results via cross-encoder (``reranker.py``).
2. **Consolidation** — after each conversation turn, extracts structured
   events via ``MemoryExtractor``, persists them through
   ``MemoryPersistence``, and updates ``MEMORY.md`` / ``profile.json``.
3. **Compaction** — periodic LLM-driven merge of redundant events and
   profile contradiction resolution.

All file I/O is delegated to ``MemoryPersistence``; all vector operations
go through ``_Mem0Adapter``.  This module owns the coordination logic only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.tracing import bind_trace
from nanobot.utils.helpers import ensure_dir

from .constants import _SAVE_MEMORY_TOOL
from .extractor import MemoryExtractor
from .graph import KnowledgeGraph
from .mem0_adapter import _Mem0Adapter, _Mem0RuntimeInfo
from .persistence import MemoryPersistence
from .reranker import DEFAULT_MODEL as _DEFAULT_RERANKER_MODEL
from .reranker import CrossEncoderReranker
from .retrieval import _local_retrieve, _topic_fallback_retrieve

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


class MemoryStore:
    """mem0-first memory store with structured profile/events maintenance."""

    PROFILE_KEYS = (
        "preferences",
        "stable_facts",
        "active_projects",
        "relationships",
        "constraints",
    )
    EVENT_TYPES = {"preference", "fact", "task", "decision", "constraint", "relationship"}
    MEMORY_TYPES = {"semantic", "episodic", "reflection"}
    MEMORY_STABILITY = {"high", "medium", "low"}
    PROFILE_STATUS_ACTIVE = "active"
    PROFILE_STATUS_CONFLICTED = "conflicted"
    PROFILE_STATUS_STALE = "stale"
    CONFLICT_STATUS_OPEN = "open"
    CONFLICT_STATUS_NEEDS_USER = "needs_user"
    CONFLICT_STATUS_RESOLVED = "resolved"
    EPISODIC_STATUS_OPEN = "open"
    EPISODIC_STATUS_RESOLVED = "resolved"
    ROLLOUT_MODES = {"enabled", "shadow", "disabled"}

    def __init__(
        self,
        workspace: Path,
        rollout_overrides: dict[str, Any] | None = None,
        *,
        embedding_provider: str | None = None,
        vector_backend: str | None = None,
    ):
        self.workspace = workspace
        self.persistence = MemoryPersistence(workspace)
        self.memory_dir = self.persistence.memory_dir
        self.memory_file = self.persistence.memory_file
        self.history_file = self.persistence.history_file
        self.events_file = self.persistence.events_file
        self.profile_file = self.persistence.profile_file
        self.metrics_file = self.persistence.metrics_file
        self.index_dir: Path = self.memory_dir / "index"
        self.retriever = _Mem0RuntimeInfo()
        self.extractor = MemoryExtractor(
            to_str_list=self._to_str_list,
            coerce_event=self._coerce_event,
            utc_now_iso=self._utc_now_iso,
        )
        self.rollout = self._load_rollout_config()
        if isinstance(rollout_overrides, dict):
            self._apply_rollout_overrides(rollout_overrides)
        self.mem0 = _Mem0Adapter(
            workspace=workspace,
            user_id=str(self.rollout.get("mem0_user_id", "nanobot")),
            add_debug=bool(self.rollout.get("mem0_add_debug", False)),
            verify_write=bool(self.rollout.get("mem0_verify_write", True)),
            force_infer_true=bool(self.rollout.get("mem0_force_infer_true", False)),
        )

        # In-memory metrics collector — must be initialised before
        # _ensure_vector_health() which records metrics.
        from nanobot.agent.metrics import MetricsCollector

        self._metrics = MetricsCollector(
            self.metrics_file,
            flush_interval_s=60.0,
            defaults=self._default_metrics(),
        )

        self._ensure_vector_health()

        # Cross-encoder re-ranker (Step 7)
        reranker_alpha = float(self.rollout.get("reranker_alpha", 0.5))
        reranker_model = str(self.rollout.get("reranker_model", "")).strip() or None
        self._reranker = CrossEncoderReranker(
            model_name=reranker_model or _DEFAULT_RERANKER_MODEL,
            alpha=reranker_alpha,
        )

        # Knowledge graph (Neo4j) — graceful degradation when disabled or
        # neo4j package is not installed.
        graph_enabled = self.rollout.get("graph_enabled", False)
        if graph_enabled:
            graph_uri = str(
                self.rollout.get("graph_neo4j_uri", "bolt://localhost:7687")
            )
            graph_auth = str(
                self.rollout.get("graph_neo4j_auth", "neo4j/nanobot_graph")
            )
            graph_db = str(
                self.rollout.get("graph_neo4j_database", "neo4j")
            )
            self.graph = KnowledgeGraph(uri=graph_uri, auth=graph_auth, database=graph_db)
        else:
            self.graph = KnowledgeGraph()  # disabled — all methods return empty
            self.graph.enabled = False

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _norm_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        return {t for t in re.findall(r"[a-zA-Z0-9_\-]+", value.lower()) if len(t) > 1}

    # Stopwords excluded when extracting query keywords for graph lookups.
    _GRAPH_QUERY_STOPWORDS = frozenset({
        "the", "this", "that", "then", "than", "they", "them", "there", "these", "those",
        "what", "when", "where", "which", "while", "who", "whom", "whose", "why", "how",
        "also", "and", "but", "for", "from", "into", "just", "like", "not", "only",
        "some", "such", "very", "will", "with", "would", "could", "should", "about",
        "after", "before", "been", "being", "have", "here", "more", "most", "much",
        "over", "same", "still", "each", "even", "every", "other", "are", "was",
        "were", "had", "has", "does", "did", "any", "its", "can", "may",
        "is", "it", "an", "or", "no", "do", "so", "if", "my", "me",
        "his", "her", "our", "your", "their", "a", "of", "in", "on", "to", "at", "by",
        "currently", "involved", "caused", "resolved", "apply",
    })

    @classmethod
    def _extract_query_keywords(cls, query: str) -> set[str]:
        """Extract significant keywords from a query for graph entity lookup."""
        tokens = {t for t in re.findall(r"[a-zA-Z0-9_\-]+", query.lower()) if len(t) > 2}
        return tokens - cls._GRAPH_QUERY_STOPWORDS

    @staticmethod
    def _to_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out

    @staticmethod
    def _to_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        value = str(text or "")
        if not value:
            return 0
        return max(1, len(value) // 4)

    def _load_rollout_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "memory_rollout_mode": "enabled",
            "memory_type_separation_enabled": True,
            "memory_router_enabled": True,
            "memory_reflection_enabled": True,
            "memory_shadow_mode": False,
            "memory_shadow_sample_rate": 0.2,
            "memory_vector_health_enabled": True,
            "memory_auto_reindex_on_empty_vector": True,
            "memory_history_fallback_enabled": False,
            "memory_fallback_allowed_sources": ["profile", "events", "mem0_get_all"],
            "memory_fallback_max_summary_chars": 280,
            "rollout_gates": {
                "min_recall_at_k": 0.55,
                "min_precision_at_k": 0.25,
                "max_avg_memory_context_tokens": 1400.0,
                "max_history_fallback_ratio": 0.05,
            },
            "reranker_mode": "disabled",
            "reranker_alpha": 0.5,
            "reranker_model": "",
            "mem0_user_id": "nanobot",
            "mem0_add_debug": False,
            "mem0_verify_write": True,
            "mem0_force_infer_true": False,
        }
        rollout = dict(defaults)

        mode = str(rollout.get("memory_rollout_mode", "enabled")).strip().lower()
        rollout["memory_rollout_mode"] = mode if mode in self.ROLLOUT_MODES else "enabled"

        for key in (
            "memory_type_separation_enabled",
            "memory_router_enabled",
            "memory_reflection_enabled",
            "memory_shadow_mode",
            "memory_vector_health_enabled",
            "memory_auto_reindex_on_empty_vector",
            "memory_history_fallback_enabled",
        ):
            rollout[key] = bool(rollout.get(key, defaults[key]))

        allowed_sources = rollout.get(
            "memory_fallback_allowed_sources", defaults["memory_fallback_allowed_sources"]
        )
        if not isinstance(allowed_sources, list):
            allowed_sources = defaults["memory_fallback_allowed_sources"]
        rollout["memory_fallback_allowed_sources"] = [
            str(item).strip().lower() for item in allowed_sources if str(item).strip()
        ] or list(defaults["memory_fallback_allowed_sources"])

        try:
            max_summary_chars = int(
                rollout.get(
                    "memory_fallback_max_summary_chars",
                    defaults["memory_fallback_max_summary_chars"],
                )
            )
        except (TypeError, ValueError):
            max_summary_chars = int(defaults["memory_fallback_max_summary_chars"])
        rollout["memory_fallback_max_summary_chars"] = max(80, min(max_summary_chars, 4000))

        try:
            sample_rate = float(rollout.get("memory_shadow_sample_rate", 0.2))
        except (TypeError, ValueError):
            sample_rate = 0.2
        rollout["memory_shadow_sample_rate"] = min(max(sample_rate, 0.0), 1.0)

        return rollout

    def get_rollout_status(self) -> dict[str, Any]:
        return dict(self.rollout)

    def _apply_rollout_overrides(self, overrides: dict[str, Any]) -> None:
        if not overrides:
            return
        mode = (
            str(
                overrides.get(
                    "memory_rollout_mode", self.rollout.get("memory_rollout_mode", "enabled")
                )
            )
            .strip()
            .lower()
        )
        if mode in self.ROLLOUT_MODES:
            self.rollout["memory_rollout_mode"] = mode
        for key in (
            "memory_type_separation_enabled",
            "memory_router_enabled",
            "memory_reflection_enabled",
            "memory_shadow_mode",
            "memory_vector_health_enabled",
            "memory_auto_reindex_on_empty_vector",
            "memory_history_fallback_enabled",
        ):
            if key in overrides:
                self.rollout[key] = bool(overrides[key])
        if "memory_fallback_allowed_sources" in overrides and isinstance(
            overrides.get("memory_fallback_allowed_sources"), list
        ):
            parsed = [
                str(item).strip().lower()
                for item in overrides.get("memory_fallback_allowed_sources", [])
                if str(item).strip()
            ]
            if parsed:
                self.rollout["memory_fallback_allowed_sources"] = parsed
        if "memory_fallback_max_summary_chars" in overrides:
            try:
                self.rollout["memory_fallback_max_summary_chars"] = max(
                    80,
                    min(int(overrides["memory_fallback_max_summary_chars"]), 4000),
                )
            except (TypeError, ValueError):
                pass
        if "memory_shadow_sample_rate" in overrides:
            try:
                rate = float(overrides["memory_shadow_sample_rate"])
                self.rollout["memory_shadow_sample_rate"] = min(max(rate, 0.0), 1.0)
            except (TypeError, ValueError):
                pass
        if isinstance(overrides.get("rollout_gates"), dict):
            gates = self.rollout.get("rollout_gates")
            if not isinstance(gates, dict):
                gates = {}
            for key in (
                "min_recall_at_k",
                "min_precision_at_k",
                "max_avg_memory_context_tokens",
                "max_history_fallback_ratio",
            ):
                if key not in overrides["rollout_gates"]:
                    continue
                try:
                    gates[key] = float(overrides["rollout_gates"][key])
                except (TypeError, ValueError):
                    continue
            self.rollout["rollout_gates"] = gates
        # Reranker overrides
        if "reranker_mode" in overrides:
            rm = str(overrides["reranker_mode"]).strip().lower()
            if rm in ("enabled", "shadow", "disabled"):
                self.rollout["reranker_mode"] = rm
        if "reranker_alpha" in overrides:
            try:
                self.rollout["reranker_alpha"] = min(
                    max(float(overrides["reranker_alpha"]), 0.0), 1.0
                )
            except (TypeError, ValueError):
                pass
        if "reranker_model" in overrides:
            self.rollout["reranker_model"] = str(overrides["reranker_model"]).strip()
        # mem0 overrides
        if "mem0_user_id" in overrides:
            self.rollout["mem0_user_id"] = str(overrides["mem0_user_id"]).strip() or "nanobot"
        for bk in ("mem0_add_debug", "mem0_verify_write", "mem0_force_infer_true"):
            if bk in overrides:
                self.rollout[bk] = bool(overrides[bk])

    @staticmethod
    def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
        lowered = str(text or "").lower()
        return any(needle in lowered for needle in needles)

    @staticmethod
    def _infer_retrieval_intent(query: str) -> str:
        text = str(query or "").strip().lower()
        if not text:
            return "fact_lookup"

        debug_markers = (
            "what happened",
            "last time",
            "failed",
            "failure",
            "error",
            "incident",
            "debug",
            "timeline",
            "yesterday",
            "what did we try",
            "correction",
            "corrected",
            "post-mortem",
            "postmortem",
            "root cause",
            "outage",
        )
        reflection_markers = (
            "reflect", "reflection", "lesson", "learned", "retrospective",
            "insight", "insights",
        )
        planning_markers = (
            "plan",
            "next step",
            "roadmap",
            "todo",
            "should we",
            "what should",
            "task",
            "tasks",
            "decision",
            "decisions",
            "in progress",
            "still open",
            "resolved",
            "completed",
            "closed",
            "project",
            "projects",
            "active",
        )
        architecture_markers = (
            "architecture",
            "architectural",
            "design decision",
            "memory architecture",
        )
        constraints_markers = ("constraint", "must", "cannot", "before running commands")
        conflict_markers = ("conflict", "needs_user", "unresolved decision")
        rollout_markers = ("rollout", "router", "shadow mode", "memory behavior enabled")

        if any(marker in text for marker in reflection_markers):
            return "reflection"
        if any(marker in text for marker in rollout_markers):
            return "rollout_status"
        if any(marker in text for marker in conflict_markers):
            return "conflict_review"
        if any(marker in text for marker in constraints_markers):
            return "constraints_lookup"
        if any(marker in text for marker in debug_markers):
            return "debug_history"
        if any(marker in text for marker in architecture_markers):
            return "planning"
        if any(marker in text for marker in planning_markers):
            return "planning"
        return "fact_lookup"

    @staticmethod
    def _retrieval_policy(intent: str) -> dict[str, Any]:
        policy = {
            "fact_lookup": {
                "candidate_multiplier": 3,
                "half_life_days": 120.0,
                "type_boost": {"semantic": 0.18, "episodic": -0.05, "reflection": -0.12},
                "fallback_topics": [
                    "knowledge", "user_preference", "relationship", "profile_update",
                ],
                "fallback_types": ["semantic"],
            },
            "debug_history": {
                "candidate_multiplier": 4,
                "half_life_days": 21.0,
                "type_boost": {"semantic": -0.04, "episodic": 0.22, "reflection": -0.1},
                "fallback_topics": ["infra", "user_correction"],
                "fallback_types": ["episodic"],
            },
            "planning": {
                "candidate_multiplier": 3,
                "half_life_days": 45.0,
                "type_boost": {"semantic": 0.1, "episodic": 0.08, "reflection": -0.06},
                "fallback_topics": ["task_progress", "decision_log", "project"],
                "fallback_types": ["episodic"],
            },
            "reflection": {
                "candidate_multiplier": 3,
                "half_life_days": 60.0,
                "type_boost": {"semantic": 0.03, "episodic": -0.03, "reflection": 0.2},
                "fallback_topics": ["reflection"],
                "fallback_types": ["reflection"],
            },
            "constraints_lookup": {
                "candidate_multiplier": 4,
                "half_life_days": 180.0,
                "type_boost": {"semantic": 0.24, "episodic": -0.1, "reflection": -0.14},
                "fallback_topics": ["constraint"],
                "fallback_types": ["semantic"],
            },
            "conflict_review": {
                "candidate_multiplier": 4,
                "half_life_days": 90.0,
                "type_boost": {"semantic": 0.05, "episodic": 0.15, "reflection": -0.08},
                "fallback_topics": ["decision_log"],
                "fallback_types": ["episodic"],
            },
            "rollout_status": {
                "candidate_multiplier": 2,
                "half_life_days": 365.0,
                "type_boost": {"semantic": 0.3, "episodic": -0.16, "reflection": -0.2},
                "fallback_topics": ["rollout"],
                "fallback_types": ["semantic"],
            },
        }
        return policy.get(intent, policy["fact_lookup"])

    @staticmethod
    def _query_routing_hints(query: str) -> dict[str, Any]:
        text = str(query or "").strip().lower()
        open_markers = (
            "still open",
            "open task",
            "open tasks",
            "pending",
            "in progress",
            "unresolved",
            "needs user",
        )
        resolved_markers = ("resolved", "completed", "closed", "finished", "done")
        planning_markers = ("plan", "next step", "roadmap", "todo", "planning")
        architecture_markers = (
            "architecture",
            "architectural",
            "design decision",
            "memory architecture",
        )
        task_decision_markers = ("task", "tasks", "decision", "decisions")

        requires_open = any(marker in text for marker in open_markers)
        requires_resolved = any(marker in text for marker in resolved_markers)
        if requires_open and requires_resolved:
            # If query mixes both terms, prefer broader task/decision focus without status hard-filter.
            requires_open = False
            requires_resolved = False

        focus_architecture = any(marker in text for marker in architecture_markers)
        focus_planning = focus_architecture or any(marker in text for marker in planning_markers)
        focus_task_decision = (
            requires_open
            or requires_resolved
            or any(marker in text for marker in task_decision_markers)
        )

        return {
            "requires_open": requires_open,
            "requires_resolved": requires_resolved,
            "focus_planning": focus_planning,
            "focus_architecture": focus_architecture,
            "focus_task_decision": focus_task_decision,
        }

    def _status_matches_query_hint(
        self,
        *,
        status: str,
        summary: str,
        requires_open: bool,
        requires_resolved: bool,
    ) -> bool:
        status_norm = str(status or "").strip().lower()
        summary_text = str(summary or "")
        open_statuses = {"open", "in_progress", "pending", "active", "needs_user"}
        resolved_statuses = {"resolved", "completed", "closed", "done", "superseded"}
        summary_is_resolved = self._is_resolved_task_or_decision(summary_text)

        if requires_open:
            if status_norm in resolved_statuses:
                return False
            if status_norm in open_statuses:
                return True
            return not summary_is_resolved
        if requires_resolved:
            if status_norm in resolved_statuses:
                return True
            if status_norm in open_statuses:
                return False
            return summary_is_resolved
        return True

    def _memory_type_for_item(self, item: dict[str, Any]) -> str:
        memory_type = str(item.get("memory_type", "")).strip().lower()
        if memory_type in self.MEMORY_TYPES:
            return memory_type
        # Check metadata as fallback for raw JSONL events.
        meta = item.get("metadata")
        if isinstance(meta, dict):
            meta_type = str(meta.get("memory_type", "")).strip().lower()
            if meta_type in self.MEMORY_TYPES:
                return meta_type
        event_type = str(item.get("type", "")).strip().lower()
        if event_type in {"task", "decision"}:
            return "episodic"
        if event_type in {"preference", "fact", "constraint", "relationship"}:
            return "semantic"
        return "episodic"

    def _recency_signal(self, timestamp: str, *, half_life_days: float) -> float:
        ts = self._to_datetime(timestamp)
        if ts is None:
            return 0.0
        now = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = max((now - ts).total_seconds() / 86400.0, 0.0)
        if half_life_days <= 0:
            return 0.0
        decay = math.exp(-math.log(2) * age_days / half_life_days)
        return max(min(decay, 1.0), 0.0)

    def _default_topic_for_event_type(self, event_type: str) -> str:
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
        has_incident = self._contains_any(text, incident_markers)
        has_causal = self._contains_any(text, causal_markers)
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

    def _distill_semantic_summary(self, summary: str) -> str:
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

        confidence = min(max(self._safe_float(payload.get("confidence"), 0.7), 0.0), 1.0)
        timestamp = str(payload.get("timestamp", "")).strip() or self._utc_now_iso()
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
            "entities": self._to_str_list(event.get("entities")),
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

    def _load_metrics(self) -> dict[str, Any]:
        return self._metrics.snapshot()

    @classmethod
    def _default_metrics(cls) -> dict[str, int | str]:
        """Default/initial counters for a fresh metrics file."""
        return {
            "consolidations": 0,
            "events_extracted": 0,
            "extraction_source_llm": 0,
            "extraction_source_heuristic": 0,
            "extraction_events_preference": 0,
            "extraction_events_fact": 0,
            "extraction_events_task": 0,
            "extraction_events_decision": 0,
            "extraction_events_constraint": 0,
            "extraction_events_relationship": 0,
            "event_dedup_merges": 0,
            "semantic_supersessions": 0,
            "retrieval_queries": 0,
            "retrieval_hits": 0,
            "retrieval_candidates": 0,
            "retrieval_returned": 0,
            "retrieval_filtered_out": 0,
            "retrieval_intent_fact_lookup": 0,
            "retrieval_intent_debug_history": 0,
            "retrieval_intent_planning": 0,
            "retrieval_intent_reflection": 0,
            "retrieval_intent_constraints_lookup": 0,
            "retrieval_intent_conflict_review": 0,
            "retrieval_intent_rollout_status": 0,
            "retrieval_returned_semantic": 0,
            "retrieval_returned_episodic": 0,
            "retrieval_returned_reflection": 0,
            "retrieval_returned_unknown": 0,
            "retrieval_shadow_runs": 0,
            "retrieval_shadow_overlap_count": 0,
            "retrieval_shadow_overlap_sum": 0,
            "retrieval_source_vector_count": 0,
            "retrieval_source_get_all_count": 0,
            "retrieval_source_history_count": 0,
            "retrieval_rejected_blob_count": 0,
            "vector_health_degraded_count": 0,
            "vector_health_probe_runs": 0,
            "vector_health_probe_vector_rows": 0,
            "vector_health_probe_vector_points": 0,
            "vector_health_probe_history_rows": 0,
            "reindex_runs": 0,
            "reindex_written": 0,
            "reindex_failed": 0,
            "mem0_add_mode_counts_infer_true": 0,
            "mem0_add_mode_counts_default_signature": 0,
            "mem0_add_mode_counts_infer_false_fallback": 0,
            "mem0_add_mode_counts_infer_true_local_fallback": 0,
            "mem0_add_mode_counts_default_signature_local_fallback": 0,
            "mem0_add_mode_counts_infer_false_local_fallback": 0,
            "index_updates": 0,
            "conflicts_detected": 0,
            "messages_processed": 0,
            "user_messages_processed": 0,
            "user_corrections": 0,
            "profile_updates_applied": 0,
            "memory_writes_total": 0,
            "memory_writes_semantic": 0,
            "memory_writes_episodic": 0,
            "memory_writes_reflection": 0,
            "memory_writes_dual": 0,
            "memory_write_failures": 0,
            "reflection_downgraded_no_evidence": 0,
            "reflection_filtered_non_reflection_intent": 0,
            "reflection_filtered_no_evidence": 0,
            "memory_context_calls": 0,
            "memory_context_tokens_total": 0,
            "memory_context_tokens_max": 0,
            "memory_context_tokens_long_term_total": 0,
            "memory_context_tokens_profile_total": 0,
            "memory_context_tokens_semantic_total": 0,
            "memory_context_tokens_episodic_total": 0,
            "memory_context_tokens_reflection_total": 0,
            "memory_context_intent_fact_lookup": 0,
            "memory_context_intent_debug_history": 0,
            "memory_context_intent_planning": 0,
            "memory_context_intent_reflection": 0,
            "memory_context_intent_constraints_lookup": 0,
            "memory_context_intent_conflict_review": 0,
            "memory_context_intent_rollout_status": 0,
        }

    def _record_metric(self, key: str, delta: int = 1) -> None:
        self._metrics.record(key, delta)

    def _persist_metrics(self, metrics: dict[str, Any]) -> None:
        """Sync-update the in-memory collector and mark dirty.

        For backward compatibility with callers that build a full dict and
        pass it in.  The MetricsCollector will flush to disk on its own
        schedule.
        """
        self._metrics.set_fields(metrics)

    def _record_metrics(self, deltas: dict[str, int]) -> None:
        self._metrics.record_many(deltas)

    def _set_metric_fields(self, fields: dict[str, Any]) -> None:
        self._metrics.set_fields(fields)

    @staticmethod
    def _looks_blob_like_summary(summary: str) -> bool:
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
        clean: dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                clean[key] = value
                continue
            if isinstance(value, list):
                items: list[str | int | float | bool] = []
                for item in value:
                    if isinstance(item, (str, int, float, bool)):
                        items.append(item)
                    elif item is not None:
                        items.append(str(item))
                clean[key] = items
                continue
            clean[key] = str(value)
        return clean

    def _sanitize_mem0_text(self, text: str, *, allow_archival: bool = False) -> str:
        value = str(text or "")
        if not value.strip():
            return ""
        if "[Runtime Context]" in value:
            value = value.split("[Runtime Context]", 1)[0]
        value = re.sub(r"\s+", " ", value).strip()
        max_chars = int(self.rollout.get("memory_fallback_max_summary_chars", 280) or 280)
        if len(value) > max_chars and not allow_archival:
            return ""
        if len(value) > max_chars and allow_archival:
            value = value[:max_chars].rstrip() + "..."
        if self._looks_blob_like_summary(value):
            return ""
        return value

    def _mem0_get_all_rows(self, *, limit: int = 200) -> list[dict[str, Any]]:
        if not self.mem0.enabled or not self.mem0.client:
            return []
        try:
            raw = self.mem0.client.get_all(user_id=self.mem0.user_id, limit=max(1, limit))
        except TypeError:
            try:
                raw = self.mem0.client.get_all(self.mem0.user_id, max(1, limit))
            except Exception:  # crash-barrier: mem0 SDK produces varied errors
                return []
        except Exception:  # crash-barrier: mem0 SDK produces varied errors
            return []
        return self.mem0._rows(raw)

    def _vector_points_count(self) -> int:
        local_mem0_dir = self.mem0._local_mem0_dir or (self.workspace / "memory" / "mem0")
        base = local_mem0_dir / "qdrant" / "collection"
        if not base.exists() or not base.is_dir():
            return 0
        total = 0
        for child in base.iterdir():
            if not child.is_dir():
                continue
            storage = child / "storage.sqlite"
            if not storage.exists():
                continue
            try:
                conn = sqlite3.connect(storage)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM points")
                total += int(cur.fetchone()[0])
                conn.close()
            except (sqlite3.Error, OSError):
                continue
        return max(total, 0)

    def _history_row_count(self) -> int:
        local_mem0_dir = self.mem0._local_mem0_dir or (self.workspace / "memory" / "mem0")
        history_db = local_mem0_dir / "history.db"
        if not history_db.exists():
            return 0
        try:
            conn = sqlite3.connect(history_db)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*)
                FROM history
                WHERE COALESCE(is_deleted, 0) = 0
                  AND COALESCE(new_memory, '') != ''
                """
            )
            count = int(cur.fetchone()[0])
            conn.close()
            return max(count, 0)
        except (sqlite3.Error, OSError):
            return 0

    def _event_compaction_key(self, event: dict[str, Any]) -> tuple[str, str, str, str]:
        summary = self._norm_text(str(event.get("summary", "")))
        event_type = str(event.get("type", "fact")).strip().lower() or "fact"
        memory_type = str(event.get("memory_type", "episodic")).strip().lower() or "episodic"
        topic = str(event.get("topic", "general")).strip().lower() or "general"
        return (summary, event_type, memory_type, topic)

    def _compact_events_for_reindex(
        self, events: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        if not events:
            return [], {"before": 0, "after": 0, "superseded_dropped": 0, "duplicates_dropped": 0}

        compacted: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        superseded_dropped = 0
        duplicates_dropped = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            status = str(event.get("status", "")).strip().lower()
            if status == "superseded":
                superseded_dropped += 1
                continue
            key = self._event_compaction_key(event)
            if not key[0]:
                continue
            existing = compacted.get(key)
            if existing is None:
                compacted[key] = event
                continue
            old_ts = str(existing.get("timestamp", ""))
            new_ts = str(event.get("timestamp", ""))
            if new_ts >= old_ts:
                compacted[key] = event
            duplicates_dropped += 1

        out = sorted(compacted.values(), key=lambda e: str(e.get("timestamp", "")))
        return out, {
            "before": len(events),
            "after": len(out),
            "superseded_dropped": superseded_dropped,
            "duplicates_dropped": duplicates_dropped,
        }

    def reindex_from_structured_memory(
        self,
        *,
        max_events: int | None = None,
        reset_existing: bool = False,
        compact: bool = False,
    ) -> dict[str, Any]:
        if not self.mem0.enabled:
            result = {"ok": False, "reason": "mem0_disabled", "written": 0, "failed": 0}
            self._set_metric_fields(
                {"last_reindex_at": self._utc_now_iso(), "last_reindex_result": result}
            )
            return result

        reset_result: dict[str, Any] = {
            "requested": bool(reset_existing),
            "ok": True,
            "reason": "",
            "deleted_estimate": 0,
        }
        if reset_existing:
            ok, reason, deleted_estimate = self.mem0.delete_all_user_memories()
            reset_result = {
                "requested": True,
                "ok": bool(ok),
                "reason": str(reason),
                "deleted_estimate": int(deleted_estimate),
            }
            if not ok:
                result = {
                    "ok": False,
                    "reason": "structured_reindex_reset_failed",
                    "written": 0,
                    "failed": 0,
                    "events_indexed": 0,
                    "reset": reset_result,
                }
                self._set_metric_fields(
                    {"last_reindex_at": self._utc_now_iso(), "last_reindex_result": result}
                )
                return result

        profile = self.read_profile()
        events = self.read_events(
            limit=max_events if isinstance(max_events, int) and max_events > 0 else None
        )
        compaction_stats = {
            "before": len(events),
            "after": len(events),
            "superseded_dropped": 0,
            "duplicates_dropped": 0,
        }
        if compact:
            events, compaction_stats = self._compact_events_for_reindex(events)
        written = 0
        failed = 0
        seen: set[tuple[str, str, str]] = set()

        section_topic = {
            "preferences": "user_preference",
            "stable_facts": "knowledge",
            "active_projects": "project",
            "relationships": "relationship",
            "constraints": "constraint",
        }
        section_event_type = {
            "preferences": "preference",
            "stable_facts": "fact",
            "active_projects": "fact",
            "relationships": "relationship",
            "constraints": "constraint",
        }

        for section in self.PROFILE_KEYS:
            values = profile.get(section, [])
            if not isinstance(values, list):
                continue
            for value in values:
                summary = self._sanitize_mem0_text(str(value), allow_archival=False)
                if not summary:
                    continue
                metadata = self._sanitize_mem0_metadata(
                    {
                        "memory_type": "semantic",
                        "topic": section_topic.get(section, "general"),
                        "stability": "high",
                        "source": "profile",
                        "event_type": section_event_type.get(section, "fact"),
                        "status": "active",
                        "timestamp": profile.get("last_verified_at") or self._utc_now_iso(),
                    }
                )
                key = (
                    self._norm_text(summary),
                    str(metadata.get("memory_type", "")),
                    str(metadata.get("topic", "")),
                )
                if key in seen:
                    continue
                seen.add(key)
                if self.mem0.add_text(summary, metadata=metadata):
                    written += 1
                else:
                    failed += 1

        for event in events:
            for text, raw_metadata in self._event_mem0_write_plan(event):
                summary = self._sanitize_mem0_text(
                    text,
                    allow_archival=bool(raw_metadata.get("archival")),
                )
                if not summary:
                    continue
                metadata = self._sanitize_mem0_metadata(dict(raw_metadata))
                metadata["source"] = "events"
                key = (
                    self._norm_text(summary),
                    str(metadata.get("memory_type", "")),
                    str(metadata.get("topic", "")),
                )
                if key in seen:
                    continue
                seen.add(key)
                if self.mem0.add_text(summary, metadata=metadata):
                    written += 1
                else:
                    failed += 1

        flushed = self.mem0.flush_vector_store()
        if flushed:
            self.mem0.reopen_client()

        vector_points_after = self._vector_points_count()
        mem0_rows_after = len(self._mem0_get_all_rows(limit=500))
        ok = failed == 0 and (vector_points_after > 0 or mem0_rows_after > 0)
        result = {
            "ok": ok,
            "reason": "structured_reindex",
            "written": written,
            "failed": failed,
            "events_indexed": len(events),
            "compacted": bool(compact),
            "events_before_compaction": int(compaction_stats.get("before", len(events))),
            "events_after_compaction": int(compaction_stats.get("after", len(events))),
            "events_superseded_dropped": int(compaction_stats.get("superseded_dropped", 0)),
            "events_duplicates_dropped": int(compaction_stats.get("duplicates_dropped", 0)),
            "reset": reset_result,
            "vector_points_after": vector_points_after,
            "mem0_get_all_after": mem0_rows_after,
            "mem0_add_mode": str(self.mem0.last_add_mode),
            "flush_applied": flushed,
        }
        self._record_metrics(
            {
                "reindex_runs": 1,
                "reindex_written": written,
                "reindex_failed": failed,
                "reindex_events_compacted": int(
                    compaction_stats.get("before", len(events))
                    - compaction_stats.get("after", len(events))
                ),
            }
        )
        self._set_metric_fields(
            {
                "last_reindex_at": self._utc_now_iso(),
                "last_reindex_result": result,
            }
        )
        return result

    def seed_structured_corpus(self, *, profile_path: Path, events_path: Path) -> dict[str, Any]:
        try:
            profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
            if not isinstance(profile_payload, dict):
                raise ValueError("seed profile must be a JSON object")
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            return {"ok": False, "reason": f"invalid_profile_seed:{exc}"}

        seeded_profile = self.read_profile()
        for key in self.PROFILE_KEYS:
            incoming = profile_payload.get(key, [])
            if isinstance(incoming, list):
                seeded_profile[key] = [str(x).strip() for x in incoming if str(x).strip()]
            else:
                seeded_profile[key] = []
        conflicts = profile_payload.get("conflicts", [])
        seeded_profile["conflicts"] = conflicts if isinstance(conflicts, list) else []
        seeded_profile["last_verified_at"] = self._utc_now_iso()
        seeded_profile["updated_at"] = self._utc_now_iso()
        seeded_profile.setdefault("meta", {key: {} for key in self.PROFILE_KEYS})
        self.write_profile(seeded_profile)

        seeded_events: list[dict[str, Any]] = []
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                text = str(line).strip()
                if not text:
                    continue
                payload = json.loads(text)
                if not isinstance(payload, dict):
                    continue
                coerced = self._coerce_event(payload, source_span=[0, 0])
                if coerced:
                    seeded_events.append(coerced)
        except (json.JSONDecodeError, OSError) as exc:
            return {"ok": False, "reason": f"invalid_events_seed:{exc}"}

        self.persistence.write_jsonl(self.events_file, seeded_events)
        result = self.reindex_from_structured_memory(reset_existing=True, compact=True)
        return {
            "ok": bool(result.get("ok")),
            "reason": "seeded_structured_corpus",
            "seeded_profile_items": sum(
                len(self._to_str_list(seeded_profile.get(k))) for k in self.PROFILE_KEYS
            ),
            "seeded_events": len(seeded_events),
            "reindex": result,
        }

    def _ensure_vector_health(self) -> None:
        if not bool(self.rollout.get("memory_vector_health_enabled", True)):
            return
        if not self.mem0.enabled:
            return
        vector_rows = len(self._mem0_get_all_rows(limit=25))
        vector_points = self._vector_points_count()
        history_rows = self._history_row_count()
        # Explicit probe requested in rollout plan.
        _probe_result = self.mem0.search("__health__", top_k=1, allow_history_fallback=False)
        degraded = history_rows > 0 and vector_rows == 0 and vector_points == 0
        self._record_metrics(
            {
                "vector_health_probe_runs": 1,
                "vector_health_probe_vector_rows": vector_rows,
                "vector_health_probe_vector_points": vector_points,
                "vector_health_probe_history_rows": history_rows,
            }
        )
        self._set_metric_fields(
            {
                "vector_health_last_checked_at": self._utc_now_iso(),
                "vector_health_last_state": {
                    "vector_rows": vector_rows,
                    "vector_points": vector_points,
                    "history_rows": history_rows,
                    "degraded": degraded,
                },
            }
        )
        if not degraded:
            return
        self._record_metric("vector_health_degraded_count", 1)
        if not bool(self.rollout.get("memory_auto_reindex_on_empty_vector", True)):
            return
        metrics = self._load_metrics()
        last_reason = str(metrics.get("last_reindex_reason", ""))
        if last_reason == "vector_health_degraded":
            return
        result = self.reindex_from_structured_memory()
        if not bool(result.get("ok")):
            self._set_metric_fields({"vector_health_hard_degraded": True})
        self._set_metric_fields(
            {
                "last_reindex_reason": "vector_health_degraded",
                "last_reindex_result": result,
            }
        )

    def _record_mem0_write_metric(self, memory_type: str, *, dual: bool = False) -> None:
        normalized = str(memory_type or "").strip().lower()
        deltas: dict[str, int] = {"memory_writes_total": 1}
        if normalized == "semantic":
            deltas["memory_writes_semantic"] = 1
        elif normalized == "reflection":
            deltas["memory_writes_reflection"] = 1
        else:
            deltas["memory_writes_episodic"] = 1
        if dual:
            deltas["memory_writes_dual"] = 1
        self._record_metrics(deltas)
        add_mode = str(self.mem0.last_add_mode or "").strip()
        if add_mode:
            self._record_metric(f"mem0_add_mode_counts_{add_mode}", 1)
            self._set_metric_fields({"mem0_last_add_mode": add_mode})

    def get_metrics(self) -> dict[str, Any]:
        return self._load_metrics()

    def get_observability_report(self) -> dict[str, Any]:
        metrics = self.get_metrics()
        retrieval_queries = max(int(metrics.get("retrieval_queries", 0)), 0)
        retrieval_hits = max(int(metrics.get("retrieval_hits", 0)), 0)
        messages_processed = max(int(metrics.get("messages_processed", 0)), 0)
        user_messages_processed = max(int(metrics.get("user_messages_processed", 0)), 0)
        user_corrections = max(int(metrics.get("user_corrections", 0)), 0)
        conflicts_detected = max(int(metrics.get("conflicts_detected", 0)), 0)
        memory_context_calls = max(int(metrics.get("memory_context_calls", 0)), 0)
        memory_context_tokens_total = max(int(metrics.get("memory_context_tokens_total", 0)), 0)
        memory_context_tokens_max = max(int(metrics.get("memory_context_tokens_max", 0)), 0)
        retrieval_shadow_overlap_count = max(
            int(metrics.get("retrieval_shadow_overlap_count", 0)), 0
        )
        retrieval_shadow_overlap_sum = max(int(metrics.get("retrieval_shadow_overlap_sum", 0)), 0)
        source_vector = max(int(metrics.get("retrieval_source_vector_count", 0)), 0)
        source_get_all = max(int(metrics.get("retrieval_source_get_all_count", 0)), 0)
        source_history = max(int(metrics.get("retrieval_source_history_count", 0)), 0)
        source_total = max(source_vector + source_get_all + source_history, 0)
        vector_points_count = self._vector_points_count()
        mem0_get_all_count = len(self._mem0_get_all_rows(limit=500))
        history_rows_count = self._history_row_count()
        vector_health_state = (
            "degraded"
            if (history_rows_count > 0 and vector_points_count == 0 and mem0_get_all_count == 0)
            else "healthy"
        )

        retrieval_hit_rate = (retrieval_hits / retrieval_queries) if retrieval_queries else 0.0
        contradiction_rate_per_100 = (
            (conflicts_detected * 100.0 / messages_processed) if messages_processed else 0.0
        )
        user_correction_rate_per_100 = (
            (user_corrections * 100.0 / user_messages_processed) if user_messages_processed else 0.0
        )
        avg_memory_context_tokens = (
            (memory_context_tokens_total / memory_context_calls) if memory_context_calls else 0.0
        )
        avg_shadow_overlap = (
            (retrieval_shadow_overlap_sum / 1000.0) / retrieval_shadow_overlap_count
            if retrieval_shadow_overlap_count
            else 0.0
        )
        history_fallback_ratio = (source_history / source_total) if source_total else 0.0

        # Extraction KPIs
        extraction_llm = max(int(metrics.get("extraction_source_llm", 0)), 0)
        extraction_heuristic = max(int(metrics.get("extraction_source_heuristic", 0)), 0)
        extraction_total = extraction_llm + extraction_heuristic
        heuristic_fallback_rate = (
            (extraction_heuristic / extraction_total) if extraction_total else 0.0
        )

        return {
            "metrics": metrics,
            "kpis": {
                "retrieval_hit_rate": round(retrieval_hit_rate, 4),
                "contradiction_rate_per_100_messages": round(contradiction_rate_per_100, 4),
                "user_correction_rate_per_100_user_messages": round(
                    user_correction_rate_per_100, 4
                ),
                "avg_memory_context_tokens": round(avg_memory_context_tokens, 2),
                "max_memory_context_tokens": memory_context_tokens_max,
                "avg_shadow_overlap": round(avg_shadow_overlap, 4),
                "history_fallback_ratio": round(history_fallback_ratio, 4),
                "heuristic_fallback_rate": round(heuristic_fallback_rate, 4),
            },
            "backend": {
                "mem0_enabled": self.mem0.enabled,
                "mem0_mode": self.mem0.mode,
                "vector_points_count": vector_points_count,
                "mem0_get_all_count": mem0_get_all_count,
                "history_rows_count": history_rows_count,
                "vector_health_state": vector_health_state,
                "mem0_add_mode": str(metrics.get("mem0_last_add_mode", "")),
            },
            "rollout": self.get_rollout_status(),
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

            retrieved = self.retrieve(
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
            "generated_at": self._utc_now_iso(),
            "evaluation": evaluation,
            "observability": observability,
            "rollout": rollout or self.get_rollout_status(),
        }
        self.persistence.write_json(path, payload)
        return path

    def evaluate_rollout_gates(
        self,
        evaluation: dict[str, Any],
        observability: dict[str, Any],
    ) -> dict[str, Any]:
        gates = self.rollout.get("rollout_gates", {})
        if not isinstance(gates, dict):
            gates = {}

        min_recall = self._safe_float(gates.get("min_recall_at_k"), 0.55)
        min_precision = self._safe_float(gates.get("min_precision_at_k"), 0.25)
        max_tokens = self._safe_float(gates.get("max_avg_memory_context_tokens"), 1400.0)
        max_history_fallback_ratio = self._safe_float(gates.get("max_history_fallback_ratio"), 0.05)

        summary = evaluation.get("summary", {}) if isinstance(evaluation, dict) else {}
        recall = self._safe_float(summary.get("recall_at_k"), 0.0)
        precision = self._safe_float(summary.get("precision_at_k"), 0.0)
        kpis = observability.get("kpis", {}) if isinstance(observability, dict) else {}
        avg_ctx_tokens = self._safe_float(kpis.get("avg_memory_context_tokens"), 0.0)
        history_fallback_ratio = self._safe_float(kpis.get("history_fallback_ratio"), 0.0)

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
            "rollout_mode": str(self.rollout.get("memory_rollout_mode", "enabled")),
        }

    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        out = self.persistence.read_jsonl(self.events_file)
        if limit is not None and limit > 0:
            return out[-limit:]
        return out

    @staticmethod
    def _merge_source_span(base: list[int] | Any, incoming: list[int] | Any) -> list[int]:
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
                    "confidence": self._safe_float(event_copy.get("confidence"), 0.7),
                    "salience": self._safe_float(event_copy.get("salience"), 0.6),
                }
            )
        event_copy["evidence"] = evidence
        event_copy["merged_event_count"] = max(int(event_copy.get("merged_event_count", 1)), 1)
        return event_copy

    def _event_similarity(self, left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
        def _event_text(event: dict[str, Any]) -> str:
            summary = str(event.get("summary", ""))
            entities = " ".join(self._to_str_list(event.get("entities")))
            event_type = str(event.get("type", "fact"))
            return f"{event_type}. {summary}. {entities}".strip()

        left_text = _event_text(left)
        right_text = _event_text(right)

        left_tokens = self._tokenize(left_text)
        right_tokens = self._tokenize(right_text)
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
        best_idx: int | None = None
        best_score = 0.0
        candidate_type = str(candidate.get("type", ""))

        for idx, existing in enumerate(existing_events):
            if str(existing.get("type", "")) != candidate_type:
                continue
            lexical, semantic = self._event_similarity(candidate, existing)
            candidate_entities = {
                self._norm_text(x) for x in self._to_str_list(candidate.get("entities"))
            }
            existing_entities = {
                self._norm_text(x) for x in self._to_str_list(existing.get("entities"))
            }
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
        if self._memory_type_for_item(candidate) != "semantic":
            return None
        candidate_summary = str(candidate.get("summary", "")).strip()
        candidate_type = str(candidate.get("type", ""))
        if not candidate_summary:
            return None

        for idx, existing in enumerate(existing_events):
            if self._memory_type_for_item(existing) != "semantic":
                continue
            if str(existing.get("type", "")) != candidate_type:
                continue
            if str(existing.get("status", "")).strip().lower() == "superseded":
                continue

            existing_summary = str(existing.get("summary", "")).strip()
            if not existing_summary:
                continue
            has_conflict = self._conflict_pair(existing_summary, candidate_summary)
            if not has_conflict:
                existing_norm = self._norm_text(existing_summary)
                candidate_norm = self._norm_text(candidate_summary)
                existing_not = " not " in f" {existing_norm} " or "n't" in existing_norm
                candidate_not = " not " in f" {candidate_norm} " or "n't" in candidate_norm
                if existing_not != candidate_not:
                    stop = {"do", "does", "did"}
                    left_tokens = {
                        t for t in self._tokenize(existing_norm.replace("not", "")) if t not in stop
                    }
                    right_tokens = {
                        t
                        for t in self._tokenize(candidate_norm.replace("not", ""))
                        if t not in stop
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
        canonical = self._ensure_event_provenance(base)
        candidate = self._ensure_event_provenance(incoming)

        entities = list(
            dict.fromkeys(
                self._to_str_list(canonical.get("entities"))
                + self._to_str_list(candidate.get("entities"))
            )
        )
        aliases = list(
            dict.fromkeys(
                self._to_str_list(canonical.get("aliases"))
                + self._to_str_list(candidate.get("aliases"))
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
        c_conf = self._safe_float(canonical.get("confidence"), 0.7)
        i_conf = self._safe_float(candidate.get("confidence"), 0.7)
        c_sal = self._safe_float(canonical.get("salience"), 0.6)
        i_sal = self._safe_float(candidate.get("salience"), 0.6)

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
        merged["last_merged_at"] = self._utc_now_iso()
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
                merged["resolved_at"] = str(candidate.get("timestamp", self._utc_now_iso()))
            else:
                merged["status"] = merged_status

        canonical_ts = self._to_datetime(str(canonical.get("timestamp", "")))
        candidate_ts = self._to_datetime(str(candidate.get("timestamp", "")))
        if canonical_ts and candidate_ts and candidate_ts > canonical_ts:
            merged["timestamp"] = str(candidate.get("timestamp", merged.get("timestamp", "")))
        return merged

    def append_events(self, events: list[dict[str, Any]]) -> int:
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
                continue
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
                now_iso = self._utc_now_iso()
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

        self.persistence.write_jsonl(self.events_file, existing_events)
        if merged > 0:
            self._record_metric("event_dedup_merges", merged)
        if superseded > 0:
            self._record_metric("semantic_supersessions", superseded)

        if written > 0 and self.mem0.enabled:
            write_totals = {
                "memory_writes_total": 0,
                "memory_writes_semantic": 0,
                "memory_writes_episodic": 0,
                "memory_writes_reflection": 0,
                "memory_writes_dual": 0,
                "memory_write_failures": 0,
                "reflection_downgraded_no_evidence": 0,
            }
            for event in appended_events:
                plan = self._event_mem0_write_plan(event)
                dual_recorded = False
                for text, metadata in plan:
                    clean_text = self._sanitize_mem0_text(
                        text,
                        allow_archival=bool(metadata.get("archival")),
                    )
                    if not clean_text:
                        continue
                    clean_metadata = self._sanitize_mem0_metadata(metadata)
                    if bool(metadata.get("reflection_safety_downgraded")):
                        write_totals["reflection_downgraded_no_evidence"] += 1
                    mem0_ok = self.mem0.add_text(clean_text, metadata=clean_metadata)
                    if not mem0_ok:
                        write_totals["memory_write_failures"] += 1
                        continue
                    write_totals["memory_writes_total"] += 1
                    memory_type = str(clean_metadata.get("memory_type", "")).strip().lower()
                    if memory_type == "semantic":
                        write_totals["memory_writes_semantic"] += 1
                    elif memory_type == "reflection":
                        write_totals["memory_writes_reflection"] += 1
                    else:
                        write_totals["memory_writes_episodic"] += 1
                    if len(plan) > 1 and not dual_recorded:
                        write_totals["memory_writes_dual"] += 1
                        dual_recorded = True
            if write_totals["memory_writes_total"] > 0 or write_totals["memory_write_failures"] > 0:
                self._record_metrics(write_totals)
        bind_trace().debug(
            "memory_append | written={} | merged={} | superseded={} | {:.0f}ms",
            written, merged, superseded, (time.monotonic() - t0_append) * 1000,
        )
        return written

    async def _ingest_graph_triples(self, events: list[dict[str, Any]]) -> int:
        """Feed triples from events into the knowledge graph (async).

        Returns the number of triples ingested.  No-op when graph is disabled.
        """
        if not self.graph.enabled:
            return 0

        from .ontology import Triple

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
                await self.graph.ingest_event_triples(event_id, parsed, timestamp=timestamp)
                total += len(parsed)

        if total > 0:
            self._record_metric("graph_triples_ingested", total)
        return total

    def read_profile(self) -> dict[str, Any]:
        data = self.persistence.read_json(self.profile_file)
        if isinstance(data, dict):
            for key in self.PROFILE_KEYS:
                data.setdefault(key, [])
                if not isinstance(data[key], list):
                    data[key] = []
            data.setdefault("conflicts", [])
            data.setdefault("last_verified_at", None)
            data.setdefault("meta", {})
            for key in self.PROFILE_KEYS:
                section_meta = data["meta"].get(key)
                if not isinstance(section_meta, dict):
                    section_meta = {}
                    data["meta"][key] = section_meta
                for item in data[key]:
                    if not isinstance(item, str) or not item.strip():
                        continue
                    norm = self._norm_text(item)
                    entry = section_meta.get(norm)
                    if not isinstance(entry, dict):
                        section_meta[norm] = {
                            "text": item,
                            "confidence": 0.65,
                            "evidence_count": 1,
                            "status": self.PROFILE_STATUS_ACTIVE,
                            "last_seen_at": data.get("updated_at") or self._utc_now_iso(),
                        }
            return data
        if self.profile_file.exists():
            logger.warning("Failed to parse memory profile, resetting")
        return {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "last_verified_at": None,
            "meta": {key: {} for key in self.PROFILE_KEYS},
            "updated_at": self._utc_now_iso(),
        }

    def _meta_section(self, profile: dict[str, Any], key: str) -> dict[str, Any]:
        profile.setdefault("meta", {})
        section = profile["meta"].get(key)
        if not isinstance(section, dict):
            section = {}
            profile["meta"][key] = section
        return section

    def _meta_entry(self, profile: dict[str, Any], key: str, text: str) -> dict[str, Any]:
        norm = self._norm_text(text)
        section = self._meta_section(profile, key)
        entry = section.get(norm)
        if not isinstance(entry, dict):
            entry = {
                "text": text,
                "confidence": 0.65,
                "evidence_count": 1,
                "status": self.PROFILE_STATUS_ACTIVE,
                "last_seen_at": self._utc_now_iso(),
            }
            section[norm] = entry
        return entry

    def _touch_meta_entry(
        self,
        entry: dict[str, Any],
        *,
        confidence_delta: float,
        min_confidence: float = 0.05,
        max_confidence: float = 0.99,
        status: str | None = None,
    ) -> None:
        current_conf = self._safe_float(entry.get("confidence"), 0.65)
        entry["confidence"] = min(
            max(current_conf + confidence_delta, min_confidence), max_confidence
        )
        evidence = int(entry.get("evidence_count", 0)) + 1
        entry["evidence_count"] = max(evidence, 1)
        entry["last_seen_at"] = self._utc_now_iso()
        if status:
            entry["status"] = status

    def _validate_profile_field(self, field: str) -> str:
        key = str(field or "").strip()
        if key not in self.PROFILE_KEYS:
            raise ValueError(
                f"Invalid profile field '{field}'. Expected one of: {', '.join(self.PROFILE_KEYS)}"
            )
        return key

    def set_item_pin(self, field: str, text: str, *, pinned: bool) -> bool:
        key = self._validate_profile_field(field)
        value = str(text or "").strip()
        if not value:
            return False

        profile = self.read_profile()
        values = self._to_str_list(profile.get(key))
        normalized = self._norm_text(value)
        existing_map = {self._norm_text(v): v for v in values}
        if normalized not in existing_map:
            values.append(value)
            profile[key] = values

        canonical = existing_map.get(normalized, value)
        entry = self._meta_entry(profile, key, canonical)
        entry["pinned"] = bool(pinned)
        entry["last_seen_at"] = self._utc_now_iso()
        if entry.get("status") == self.PROFILE_STATUS_STALE and pinned:
            entry["status"] = self.PROFILE_STATUS_ACTIVE
        self.write_profile(profile)
        return True

    def mark_item_outdated(self, field: str, text: str) -> bool:
        key = self._validate_profile_field(field)
        value = str(text or "").strip()
        if not value:
            return False

        profile = self.read_profile()
        values = self._to_str_list(profile.get(key))
        normalized = self._norm_text(value)
        existing = None
        for item in values:
            if self._norm_text(item) == normalized:
                existing = item
                break
        if existing is None:
            return False

        entry = self._meta_entry(profile, key, existing)
        entry["status"] = self.PROFILE_STATUS_STALE
        entry["last_seen_at"] = self._utc_now_iso()
        self.write_profile(profile)
        return True

    def list_conflicts(self, *, include_closed: bool = False) -> list[dict[str, Any]]:
        profile = self.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            return []

        out: list[dict[str, Any]] = []
        for idx, item in enumerate(conflicts):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            if not include_closed and status not in {
                self.CONFLICT_STATUS_OPEN,
                self.CONFLICT_STATUS_NEEDS_USER,
            }:
                continue
            row = dict(item)
            row["index"] = idx
            out.append(row)
        return out

    @staticmethod
    def _parse_conflict_user_action(text: str) -> str | None:
        content = str(text or "").strip().lower()
        if not content:
            return None
        keep_old_markers = {"keep 1", "1", "old", "keep old", "keep_old"}
        keep_new_markers = {"keep 2", "2", "new", "keep new", "keep_new"}
        dismiss_markers = {"neither", "dismiss", "none", "skip"}
        merge_markers = {"merge", "combine"}
        if content in keep_old_markers:
            return "keep_old"
        if content in keep_new_markers:
            return "keep_new"
        if content in dismiss_markers:
            return "dismiss"
        if content in merge_markers:
            return "merge"
        return None

    def _auto_resolution_action(self, conflict: dict[str, Any]) -> str | None:
        source = str(conflict.get("source", "")).strip().lower()
        if source == "live_correction":
            # Live corrections surface conflicts for user review rather than
            # silently auto-resolving.  The user explicitly stated a change so
            # the conflict should be presented via ask_user_for_conflict().
            return None

        old_conf = self._safe_float(conflict.get("old_confidence"), 0.0)
        new_conf = self._safe_float(conflict.get("new_confidence"), 0.0)
        gap = abs(old_conf - new_conf)
        if gap < 0.25:
            return None
        return "keep_new" if new_conf > old_conf else "keep_old"

    def auto_resolve_conflicts(self, *, max_items: int = 10) -> dict[str, int]:
        profile = self.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            return {"auto_resolved": 0, "needs_user": 0}

        auto_resolved = 0
        needs_user = 0
        touched = False
        for idx, conflict in enumerate(conflicts):
            if max_items <= 0:
                break
            if not isinstance(conflict, dict):
                continue
            status = str(conflict.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            if status not in {self.CONFLICT_STATUS_OPEN, self.CONFLICT_STATUS_NEEDS_USER}:
                continue
            max_items -= 1

            action = self._auto_resolution_action(conflict)
            if action is None:
                if status != self.CONFLICT_STATUS_NEEDS_USER:
                    conflict["status"] = self.CONFLICT_STATUS_NEEDS_USER
                    touched = True
                needs_user += 1
                continue

            details = self.resolve_conflict_details(idx, action)
            if details.get("ok"):
                auto_resolved += 1
                continue

            conflict["status"] = self.CONFLICT_STATUS_NEEDS_USER
            touched = True
            needs_user += 1

        if touched:
            self.write_profile(profile)
        return {"auto_resolved": auto_resolved, "needs_user": needs_user}

    def get_next_user_conflict(self) -> dict[str, Any] | None:
        conflicts = self.list_conflicts(include_closed=False)
        if not conflicts:
            return None

        asked = [c for c in conflicts if isinstance(c.get("asked_at"), str) and c.get("asked_at")]
        pool = asked or conflicts
        if not pool:
            return None
        pool.sort(key=lambda c: str(c.get("asked_at", "")))
        return pool[0]

    def ask_user_for_conflict(self, *, include_already_asked: bool = False) -> str | None:
        profile = self.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            return None

        chosen_idx: int | None = None
        chosen: dict[str, Any] | None = None
        for idx, item in enumerate(conflicts):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            if status != self.CONFLICT_STATUS_NEEDS_USER:
                continue
            if not include_already_asked and item.get("asked_at"):
                continue
            chosen_idx = idx
            chosen = item
            break

        if chosen_idx is None or chosen is None:
            return None

        if not chosen.get("asked_at"):
            chosen["asked_at"] = self._utc_now_iso()
            self.write_profile(profile)

        old_value = str(chosen.get("old", "")).strip()
        new_value = str(chosen.get("new", "")).strip()
        return (
            "I found a memory conflict and need your choice:\n"
            f"1. {old_value}\n"
            f"2. {new_value}\n"
            "Reply with: `keep 1`, `keep 2`, `merge`, or `neither`."
        )

    def handle_user_conflict_reply(self, text: str) -> dict[str, Any]:
        action = self._parse_conflict_user_action(text)
        if action is None:
            return {"handled": False}

        conflict = self.get_next_user_conflict()
        if not conflict:
            return {"handled": False}

        idx = int(conflict.get("index", -1))
        if idx < 0:
            return {"handled": False}

        selected = "keep_new" if action == "merge" else action
        details = self.resolve_conflict_details(index=idx, action=selected)
        if not details.get("ok"):
            return {
                "handled": True,
                "ok": False,
                "message": "I couldn't resolve that conflict automatically. Please try `keep 1` or `keep 2`.",
            }

        return {
            "handled": True,
            "ok": True,
            "message": (
                f"Resolved conflict #{idx} with action `{selected}` "
                f"(mem0 op: {details.get('mem0_operation', 'none')})."
            ),
        }

    def resolve_conflict_details(self, index: int, action: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "index": index,
            "action": str(action or "").strip().lower(),
            "field": "",
            "old": "",
            "new": "",
            "old_memory_id": "",
            "new_memory_id": "",
            "mem0_operation": "none",
            "mem0_ok": False,
        }
        profile = self.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list) or index < 0 or index >= len(conflicts):
            return result

        conflict = conflicts[index]
        if not isinstance(conflict, dict) or str(
            conflict.get("status", "")
        ).strip().lower() not in {
            self.CONFLICT_STATUS_OPEN,
            self.CONFLICT_STATUS_NEEDS_USER,
        }:
            return result

        field = str(conflict.get("field", ""))
        result["field"] = field
        try:
            key = self._validate_profile_field(field)
        except ValueError:
            return result

        old_value = str(conflict.get("old", "")).strip()
        new_value = str(conflict.get("new", "")).strip()
        result["old"] = old_value
        result["new"] = new_value
        values = self._to_str_list(profile.get(key))
        old_memory_id = str(
            conflict.get("old_memory_id", "")
        ).strip() or self._find_mem0_id_for_text(old_value)
        new_memory_id = str(
            conflict.get("new_memory_id", "")
        ).strip() or self._find_mem0_id_for_text(new_value)
        if old_memory_id:
            conflict["old_memory_id"] = old_memory_id
        if new_memory_id:
            conflict["new_memory_id"] = new_memory_id

        result["old_memory_id"] = old_memory_id
        result["new_memory_id"] = new_memory_id

        def _remove_value(values_in: list[str], target: str) -> list[str]:
            target_norm = self._norm_text(target)
            return [v for v in values_in if self._norm_text(v) != target_norm]

        selected = str(action or "").strip().lower()
        mem0_ok = False
        if selected == "keep_old":
            if new_memory_id:
                mem0_ok = self.mem0.delete(new_memory_id)
                result["mem0_operation"] = "delete_new"
            else:
                mem0_ok = True
                result["mem0_operation"] = "none"
            values = _remove_value(values, new_value)
            old_entry = self._meta_entry(profile, key, old_value)
            self._touch_meta_entry(
                old_entry, confidence_delta=0.08, status=self.PROFILE_STATUS_ACTIVE
            )
            new_entry = self._meta_entry(profile, key, new_value)
            new_entry["status"] = self.PROFILE_STATUS_STALE
        elif selected == "keep_new":
            clean_new_value = self._sanitize_mem0_text(new_value, allow_archival=False) or new_value
            if old_memory_id:
                mem0_ok = self.mem0.update(old_memory_id, clean_new_value)
                result["mem0_operation"] = "update_old_to_new"
                if mem0_ok and new_memory_id and new_memory_id != old_memory_id:
                    self.mem0.delete(new_memory_id)
                    conflict["new_memory_id"] = old_memory_id
                    result["new_memory_id"] = old_memory_id
            else:
                conflict_metadata, _ = self._normalize_memory_metadata(
                    {
                        "topic": "conflict_resolution",
                        "memory_type": "semantic",
                        "stability": "high",
                    },
                    event_type="fact",
                    summary=clean_new_value,
                    source="chat",
                )
                conflict_metadata.update({"event_type": "conflict_resolution", "field": key})
                conflict_metadata = self._sanitize_mem0_metadata(conflict_metadata)
                mem0_ok = (
                    self.mem0.add_text(
                        clean_new_value,
                        metadata=conflict_metadata,
                    )
                    if clean_new_value
                    else False
                )
                if mem0_ok:
                    self._record_mem0_write_metric("semantic")
                result["mem0_operation"] = "add_new"
            values = _remove_value(values, old_value)
            new_entry = self._meta_entry(profile, key, new_value)
            self._touch_meta_entry(
                new_entry, confidence_delta=0.08, status=self.PROFILE_STATUS_ACTIVE
            )
            old_entry = self._meta_entry(profile, key, old_value)
            old_entry["status"] = self.PROFILE_STATUS_STALE
        elif selected == "dismiss":
            mem0_ok = True
            result["mem0_operation"] = "none"
            old_entry = self._meta_entry(profile, key, old_value)
            new_entry = self._meta_entry(profile, key, new_value)
            old_entry["status"] = self.PROFILE_STATUS_ACTIVE
            new_entry["status"] = self.PROFILE_STATUS_ACTIVE
        else:
            return result

        result["mem0_ok"] = mem0_ok
        if not mem0_ok and self.mem0.enabled:
            return result

        profile[key] = values
        conflict["status"] = self.CONFLICT_STATUS_RESOLVED
        conflict["resolution"] = selected
        conflict["resolved_at"] = self._utc_now_iso()
        self.write_profile(profile)
        result["ok"] = True
        return result

    def resolve_conflict(self, index: int, action: str) -> bool:
        return bool(self.resolve_conflict_details(index, action).get("ok"))

    def write_profile(self, profile: dict[str, Any]) -> None:
        profile["updated_at"] = self._utc_now_iso()
        self.persistence.write_json(self.profile_file, profile)

    def _build_event_id(self, event_type: str, summary: str, timestamp: str) -> str:
        raw = f"{self._norm_text(event_type)}|{self._norm_text(summary)}|{timestamp[:16]}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _infer_episodic_status(
        self, *, event_type: str, summary: str, raw_status: Any = None
    ) -> str | None:
        if event_type not in {"task", "decision"}:
            return None
        if isinstance(raw_status, str):
            normalized = raw_status.strip().lower()
            if normalized in {self.EPISODIC_STATUS_OPEN, self.EPISODIC_STATUS_RESOLVED}:
                return normalized
        return (
            self.EPISODIC_STATUS_RESOLVED
            if self._is_resolved_task_or_decision(summary)
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
        summary = raw.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        event_type = raw.get("type") if isinstance(raw.get("type"), str) else "fact"
        event_type = event_type if event_type in self.EVENT_TYPES else "fact"
        _raw_ts = raw.get("timestamp")
        timestamp: str = _raw_ts if isinstance(_raw_ts, str) else self._utc_now_iso()
        salience = min(max(self._safe_float(raw.get("salience"), 0.6), 0.0), 1.0)
        confidence = min(max(self._safe_float(raw.get("confidence"), 0.7), 0.0), 1.0)
        entities = self._to_str_list(raw.get("entities"))
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
                    triples.append({
                        "subject": str(t["subject"]).strip(),
                        "predicate": str(t.get("predicate", "RELATED_TO")).strip(),
                        "object": str(t["object"]).strip(),
                        "confidence": min(
                            max(self._safe_float(t.get("confidence"), confidence), 0.0), 1.0
                        ),
                    })

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

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
        recency_half_life_days: float | None = None,
        embedding_provider: str | None = None,
    ) -> list[dict[str, Any]]:
        t0 = time.monotonic()
        # Local BM25 retrieval with intent routing when mem0 is unavailable.
        if not self.mem0.enabled:
            events = self.read_events()
            intent = self._infer_retrieval_intent(query)
            policy = self._retrieval_policy(intent)
            candidate_k = max(1, min(top_k * int(policy.get("candidate_multiplier", 3)), 60))
            half_life = recency_half_life_days or float(policy.get("half_life_days", 60.0))

            # Detect queries about superseded/stale items.
            q_lower = str(query or "").lower()
            wants_superseded = any(
                m in q_lower for m in ("supersede", "stale", "older fact", "replaced")
            )

            # Graph query augmentation: expand search terms with related entities.
            augmented_query = query
            if self.graph.enabled:
                query_keywords = self._extract_query_keywords(query)
                if query_keywords:
                    neo4j_related = self.graph.get_related_entity_names_sync(
                        query_keywords, depth=2,
                    )
                    # Append related entity names to the query for BM25 matching.
                    extra_terms = neo4j_related - query_keywords
                    if extra_terms:
                        augmented_query = query + " " + " ".join(
                            t.replace("-", " ").replace("_", " ") for t in extra_terms
                        )

            candidates = _local_retrieve(
                events,
                augmented_query,
                top_k=candidate_k,
                recency_half_life_days=half_life,
                include_superseded=wants_superseded,
            )

            # Topic-based fallback: fill remaining slots when BM25 yields few matches.
            bm25_ids = {str(c.get("id", "")) for c in candidates}
            fallback_topics = list(policy.get("fallback_topics", []))
            fallback_types = list(policy.get("fallback_types", []))
            remaining = max(0, candidate_k - len(candidates))
            if remaining > 0 and (fallback_topics or fallback_types):
                fallback = _topic_fallback_retrieve(
                    events,
                    target_topics=fallback_topics,
                    target_memory_types=fallback_types,
                    exclude_ids=bm25_ids,
                    top_k=remaining,
                    base_score=0.25,
                    include_superseded=wants_superseded,
                )
                candidates.extend(fallback)

            # Apply intent-based type boosts and metadata enrichment.
            graph_boost = 0.15 if self.graph.enabled else 0.0
            query_entities = {e.lower() for e in self.extractor._extract_entities(query)}
            graph_entity_names: set[str] = set()
            if graph_boost > 0 and query_entities:
                # Collect entity names related to query entities from event triples.
                for evt in events:
                    for triple in evt.get("triples") or []:
                        subj = str(triple.get("subject", "")).lower()
                        obj = str(triple.get("object", "")).lower()
                        if subj in query_entities:
                            graph_entity_names.add(obj)
                        elif obj in query_entities:
                            graph_entity_names.add(subj)
                # Augment with Neo4j graph neighbors when available.
                neo4j_related = self.graph.get_related_entity_names_sync(
                    query_entities, depth=2,
                )
                graph_entity_names |= neo4j_related

            for item in candidates:
                memory_type = self._memory_type_for_item(item)
                item["memory_type"] = memory_type
                # Promote metadata fields to top level for downstream consumers.
                meta = item.get("metadata", {})
                if not item.get("topic"):
                    item["topic"] = str(meta.get("topic", "")).strip()
                if not item.get("stability"):
                    item["stability"] = str(meta.get("stability", "medium")).strip()
                base_score = float(item.get("retrieval_reason", {}).get("score", 0.0))
                type_boost = float(policy.get("type_boost", {}).get(memory_type, 0.0))
                stability = str(item.get("stability", "medium")).lower()
                stability_boost = {"high": 0.03, "medium": 0.01, "low": -0.02}.get(stability, 0.0)
                # Graph expansion boost: boost events that mention entities
                # related to query entities via the knowledge graph.
                g_boost = 0.0
                if graph_entity_names:
                    item_entities = {
                        e.lower() for e in (item.get("entities") or []) if isinstance(e, str)
                    }
                    if item_entities & graph_entity_names:
                        g_boost = graph_boost
                item["score"] = base_score + type_boost + stability_boost + g_boost
            candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            results = candidates[:top_k]
            self._record_metric("retrieval_queries", 1)
            if results:
                self._record_metric("retrieval_hits", 1)
            self._record_metric("retrieval_candidates", len(results))
            bind_trace().debug(
                "Memory retrieve source=bm25 results={} duration_ms={:.0f}",
                len(results),
                (time.monotonic() - t0) * 1000,
            )
            return results

        mode = str(self.rollout.get("memory_rollout_mode", "enabled")).strip().lower()
        if mode not in self.ROLLOUT_MODES:
            mode = "enabled"
        type_separation_enabled = bool(self.rollout.get("memory_type_separation_enabled", True))
        router_enabled = bool(self.rollout.get("memory_router_enabled", True))
        reflection_enabled = bool(self.rollout.get("memory_reflection_enabled", True))
        if mode == "disabled":
            type_separation_enabled = False
            router_enabled = False
            reflection_enabled = False
        if mode == "shadow":
            router_enabled = False

        final, stats = self._retrieve_core(
            query=query,
            top_k=top_k,
            router_enabled=router_enabled,
            type_separation_enabled=type_separation_enabled,
            reflection_enabled=reflection_enabled,
        )
        self._record_metric("retrieval_queries", 1)
        self._record_metric(f"retrieval_intent_{stats['intent']}", 1)
        self._record_metric("retrieval_candidates", int(stats["retrieved_count"]))
        if int(stats["retrieved_count"]) > 0:
            self._record_metric("retrieval_hits", 1)
        self._record_metrics(stats["counts"])

        shadow_enabled = bool(self.rollout.get("memory_shadow_mode", False))
        shadow_rate = float(self.rollout.get("memory_shadow_sample_rate", 0.2) or 0.0)
        if shadow_enabled and shadow_rate > 0 and mode != "disabled":
            shadow_should_run = shadow_rate >= 1.0 or (hash(f"{query}|{top_k}") % 1000) < int(
                shadow_rate * 1000
            )
            if shadow_should_run:
                shadow_router_enabled = not router_enabled
                shadow_final, _ = self._retrieve_core(
                    query=query,
                    top_k=top_k,
                    router_enabled=shadow_router_enabled,
                    type_separation_enabled=type_separation_enabled,
                    reflection_enabled=reflection_enabled,
                )
                primary_ids = [
                    str(item.get("id", "")) for item in final if str(item.get("id", "")).strip()
                ]
                shadow_ids = [
                    str(item.get("id", ""))
                    for item in shadow_final
                    if str(item.get("id", "")).strip()
                ]
                overlap = 0.0
                if primary_ids or shadow_ids:
                    overlap = len(set(primary_ids) & set(shadow_ids)) / max(
                        len(set(primary_ids) | set(shadow_ids)), 1
                    )
                self._record_metrics(
                    {
                        "retrieval_shadow_runs": 1,
                        "retrieval_shadow_overlap_count": 1,
                        "retrieval_shadow_overlap_sum": int(round(overlap * 1000)),
                    }
                )
        bind_trace().debug(
            "Memory retrieve source=mem0 results={} intent={} duration_ms={:.0f}",
            len(final),
            stats["intent"],
            (time.monotonic() - t0) * 1000,
        )
        return final

    def _retrieve_core(
        self,
        *,
        query: str,
        top_k: int,
        router_enabled: bool,
        type_separation_enabled: bool,
        reflection_enabled: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        intent = self._infer_retrieval_intent(query) if router_enabled else "fact_lookup"
        policy = self._retrieval_policy(intent)
        candidate_multiplier = (
            max(int(policy.get("candidate_multiplier", 3)), 1) if router_enabled else 1
        )
        candidate_k = max(1, min(max(top_k, top_k * candidate_multiplier), 60))
        allowed_sources = {
            str(item).strip().lower()
            for item in self.rollout.get("memory_fallback_allowed_sources", [])
            if str(item).strip()
        }
        max_summary_chars = int(self.rollout.get("memory_fallback_max_summary_chars", 280) or 280)

        # Compute graph-expanded terms (used for supplementary BM25 pass below).
        graph_extra_terms: set[str] = set()
        if self.graph.enabled:
            query_keywords = self._extract_query_keywords(query)
            if query_keywords:
                neo4j_related = self.graph.get_related_entity_names_sync(
                    query_keywords, depth=2,
                )
                graph_extra_terms = neo4j_related - query_keywords

        search_result = self.mem0.search(
            query,
            top_k=candidate_k,
            allow_get_all_fallback=True,
            allow_history_fallback=bool(self.rollout.get("memory_history_fallback_enabled", False)),
            allowed_sources=allowed_sources,
            max_summary_chars=max_summary_chars,
            reject_blob_like=True,
            return_stats=True,
        )
        if isinstance(search_result, tuple) and len(search_result) == 2:
            retrieved, source_stats = search_result
        else:
            retrieved = search_result if isinstance(search_result, list) else []
            source_stats = {
                "source_vector": 0,
                "source_get_all": 0,
                "source_history": 0,
                "rejected_blob_like": 0,
            }
        if intent == "rollout_status":
            retrieved.append(
                {
                    "id": "rollout_status_snapshot",
                    "timestamp": self._utc_now_iso(),
                    "type": "fact",
                    "summary": (
                        "Memory rollout status: "
                        f"mode={self.rollout.get('memory_rollout_mode')}, "
                        f"router={self.rollout.get('memory_router_enabled')}, "
                        f"shadow={self.rollout.get('memory_shadow_mode')}, "
                        f"reflection={self.rollout.get('memory_reflection_enabled')}, "
                        f"type_separation={self.rollout.get('memory_type_separation_enabled')}."
                    ),
                    "entities": [],
                    "score": 0.95,
                    "memory_type": "semantic",
                    "topic": "rollout",
                    "stability": "high",
                    "source": "config",
                    "confidence": 1.0,
                    "evidence_refs": [],
                    "retrieval_reason": {
                        "provider": "nanobot",
                        "backend": "synthetic_rollout",
                        "semantic": 0.95,
                        "recency": 0.0,
                    },
                    "provenance": {"canonical_id": "rollout_status_snapshot", "source_span": None},
                }
            )

        # Supplementary BM25 pass: pull in events matching graph-related entities
        # that mem0 vector search may have missed.
        if graph_extra_terms and retrieved is not None:
            retrieved_ids = {str(r.get("id", "")) for r in retrieved}
            graph_query = query + " " + " ".join(
                t.replace("-", " ").replace("_", " ") for t in graph_extra_terms
            )
            events = self.read_events()
            bm25_supplement = _local_retrieve(
                events,
                graph_query,
                top_k=candidate_k,
                recency_half_life_days=float(policy.get("half_life_days", 60.0)),
                include_superseded=False,
            )
            for item in bm25_supplement:
                eid = str(item.get("id", ""))
                if eid and eid not in retrieved_ids:
                    # Mark source as graph-augmented BM25
                    reason = item.get("retrieval_reason", {})
                    if not isinstance(reason, dict):
                        reason = {}
                    reason["provider"] = "bm25_graph"
                    item["retrieval_reason"] = reason
                    retrieved.append(item)
                    retrieved_ids.add(eid)

        if not retrieved:
            return [], {
                "intent": intent,
                "retrieved_count": 0,
                "counts": {
                    "retrieval_returned": 0,
                    "retrieval_source_vector_count": int(source_stats.get("source_vector", 0)),
                    "retrieval_source_get_all_count": int(source_stats.get("source_get_all", 0)),
                    "retrieval_source_history_count": int(source_stats.get("source_history", 0)),
                    "retrieval_rejected_blob_count": int(source_stats.get("rejected_blob_like", 0)),
                },
            }

        profile = self.read_profile()
        conflicts = (
            profile.get("conflicts", []) if isinstance(profile.get("conflicts"), list) else []
        )

        field_by_event_type = {
            "preference": "preferences",
            "fact": "stable_facts",
            "relationship": "relationships",
            "constraint": "constraints",
            "task": "active_projects",
            "decision": "active_projects",
        }
        resolved_keep_new_old: dict[str, set[str]] = {key: set() for key in self.PROFILE_KEYS}
        resolved_keep_new_new: dict[str, set[str]] = {key: set() for key in self.PROFILE_KEYS}
        for conflict in conflicts:
            if not isinstance(conflict, dict):
                continue
            if str(conflict.get("status", "")).lower() != "resolved":
                continue
            if str(conflict.get("resolution", "")).lower() != "keep_new":
                continue
            field = str(conflict.get("field", ""))
            if field not in resolved_keep_new_old:
                continue
            old_value = str(conflict.get("old", "")).strip()
            new_value = str(conflict.get("new", "")).strip()
            if old_value:
                resolved_keep_new_old[field].add(self._norm_text(old_value))
            if new_value:
                resolved_keep_new_new[field].add(self._norm_text(new_value))

        def _contains_norm_phrase(text: str, phrase_norm: str) -> bool:
            if not phrase_norm:
                return False
            text_norm = self._norm_text(text)
            if not text_norm:
                return False
            return phrase_norm in text_norm

        adjusted: list[dict[str, Any]] = []
        reflection_filtered_non_reflection_intent = 0
        reflection_filtered_no_evidence = 0
        routing_hints = self._query_routing_hints(query)
        for item in retrieved:
            event_type = str(item.get("type", "fact"))
            memory_type = self._memory_type_for_item(item)
            item["memory_type"] = memory_type

            topic = str(item.get("topic", "")).strip().lower()
            summary = str(item.get("summary", ""))
            event_status = str(item.get("status", "")).strip().lower()
            task_or_decision_like = event_type in {"task", "decision", "relationship"} or topic in {
                "task_progress",
                "project",
                "planning",
                "relationship",
            }
            planning_like = task_or_decision_like or self._contains_any(
                summary, ("plan", "next step", "roadmap", "milestone")
            )
            architecture_like = (
                "architecture" in topic
                or self._contains_any(
                    summary, ("architecture", "design decision", "memory architecture")
                )
                or event_type == "decision"
            )
            if (
                routing_hints["focus_task_decision"]
                and not task_or_decision_like
                and intent != "debug_history"
            ):
                continue
            if routing_hints["focus_planning"] and not planning_like:
                continue
            if routing_hints["focus_architecture"] and not architecture_like:
                continue
            if not self._status_matches_query_hint(
                status=event_status,
                summary=summary,
                requires_open=bool(routing_hints["requires_open"]),
                # debug_history needs the full timeline (failures + resolutions).
                requires_resolved=(
                    bool(routing_hints["requires_resolved"]) and intent != "debug_history"
                ),
            ):
                continue
            if intent == "constraints_lookup":
                if memory_type != "semantic":
                    continue
                if "constraint" not in topic and not self._contains_any(
                    summary, ("must", "cannot", "constraint", "should not")
                ):
                    continue
            if intent == "debug_history":
                if memory_type != "episodic" and topic not in {
                    "infra",
                    "task_progress",
                    "incident",
                }:
                    continue
            if intent == "conflict_review":
                if not self._contains_any(
                    summary, ("conflict", "needs_user", "resolved", "keep_new", "decision")
                ):
                    continue
            if intent == "rollout_status":
                if not self._contains_any(
                    summary, ("rollout", "router", "shadow", "reflection", "type_separation")
                ):
                    continue

            if reflection_enabled:
                if (
                    memory_type == "reflection"
                    and type_separation_enabled
                    and intent != "reflection"
                ):
                    reflection_filtered_non_reflection_intent += 1
                    continue
                evidence_refs = item.get("evidence_refs")
                if memory_type == "reflection" and not (
                    isinstance(evidence_refs, list) and len(evidence_refs) > 0
                ):
                    reflection_filtered_no_evidence += 1
                    continue
            elif memory_type == "reflection":
                reflection_filtered_non_reflection_intent += 1
                continue

            field = field_by_event_type.get(event_type)  # type: ignore[assignment]
            summary = str(item.get("summary", ""))
            score = float(item.get("score", 0.0))
            adjustment = 0.0
            adjustment_reasons: list[str] = []
            if field:
                for old_norm in resolved_keep_new_old.get(field, set()):
                    if _contains_norm_phrase(summary, old_norm):
                        adjustment -= 0.18
                        adjustment_reasons.append("resolved_keep_new_old_penalty")
                        break
                for new_norm in resolved_keep_new_new.get(field, set()):
                    if _contains_norm_phrase(summary, new_norm):
                        adjustment += 0.12
                        adjustment_reasons.append("resolved_keep_new_new_boost")
                        break
                section_meta = self._meta_section(profile, field)
                if isinstance(section_meta, dict):
                    for norm_key, meta in section_meta.items():
                        if not isinstance(meta, dict):
                            continue
                        if not _contains_norm_phrase(summary, str(norm_key)):
                            continue
                        status = str(meta.get("status", "")).lower()
                        pinned = bool(meta.get("pinned"))
                        if status == self.PROFILE_STATUS_STALE and not pinned:
                            adjustment -= 0.08
                            adjustment_reasons.append("stale_profile_penalty")
                            break
                        if status == self.PROFILE_STATUS_CONFLICTED:
                            adjustment -= 0.05
                            adjustment_reasons.append("conflicted_profile_penalty")
                            break
            if memory_type == "semantic":
                if (
                    event_status == "superseded"
                    or str(item.get("superseded_by_event_id", "")).strip()
                ):
                    adjustment -= 0.2
                    adjustment_reasons.append("semantic_superseded_penalty")

            reason = item.get("retrieval_reason")
            if not isinstance(reason, dict):
                reason = {}
                item["retrieval_reason"] = reason
            if adjustment_reasons:
                reason["profile_adjustment"] = round(adjustment, 4)
                reason["profile_adjustment_reasons"] = adjustment_reasons

            recency = self._recency_signal(
                str(item.get("timestamp", "")),
                half_life_days=float(policy.get("half_life_days", 60.0)),
            )
            type_boost = (
                float(policy.get("type_boost", {}).get(memory_type, 0.0))
                if type_separation_enabled
                else 0.0
            )
            stability = str(item.get("stability", "medium")).strip().lower()
            stability_boost = {"high": 0.03, "medium": 0.01, "low": -0.02}.get(stability, 0.0)
            reflection_penalty = -0.06 if memory_type == "reflection" else 0.0
            if not router_enabled:
                recency = 0.0
                stability_boost = 0.0
                reflection_penalty = 0.0
                type_boost = 0.0
            elif reflection_penalty:
                adjustment_reasons.append("reflection_default_penalty")
            intent_bonus = type_boost + (0.08 * recency) + stability_boost + reflection_penalty
            item["score"] = score + adjustment + intent_bonus
            reason["recency"] = round(recency, 4)
            reason["intent"] = intent
            reason["type_boost"] = round(type_boost, 4)
            reason["stability_boost"] = round(stability_boost, 4)
            if reflection_penalty:
                reason["reflection_penalty"] = round(reflection_penalty, 4)
            adjusted.append(item)

        # ------------------------------------------------------------------
        # Cross-encoder re-ranking (Step 7)
        # ------------------------------------------------------------------
        reranker_mode = str(self.rollout.get("reranker_mode", "disabled")).strip().lower()
        if reranker_mode in ("enabled", "shadow") and adjusted and self._reranker.available:
            if reranker_mode == "enabled":
                adjusted = self._reranker.rerank(query, adjusted)
                self._record_metric("reranker_runs", 1)
            else:
                # Shadow: compute re-ranked order but keep heuristic order.
                import copy

                shadow_items = copy.deepcopy(adjusted)
                shadow_items = self._reranker.rerank(query, shadow_items)
                heuristic_ids = [str(it.get("id", "")) for it in adjusted]
                reranked_ids = [str(it.get("id", "")) for it in shadow_items]
                delta = self._reranker.compute_rank_delta(heuristic_ids, reranked_ids)
                self._record_metrics(
                    {
                        "reranker_shadow_runs": 1,
                        "reranker_shadow_rank_delta_sum": int(round(delta * 1000)),
                        "reranker_shadow_rank_delta_count": 1,
                    }
                )

        adjusted.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        final = adjusted[: max(1, top_k)]
        counts = {
            "retrieval_returned": len(final),
            "retrieval_filtered_out": max(len(retrieved) - len(final), 0),
            "retrieval_source_vector_count": int(source_stats.get("source_vector", 0)),
            "retrieval_source_get_all_count": int(source_stats.get("source_get_all", 0)),
            "retrieval_source_history_count": int(source_stats.get("source_history", 0)),
            "retrieval_rejected_blob_count": int(source_stats.get("rejected_blob_like", 0)),
            "reflection_filtered_non_reflection_intent": reflection_filtered_non_reflection_intent,
            "reflection_filtered_no_evidence": reflection_filtered_no_evidence,
            "retrieval_returned_semantic": 0,
            "retrieval_returned_episodic": 0,
            "retrieval_returned_reflection": 0,
            "retrieval_returned_unknown": 0,
        }
        for item in final:
            memory_type = str(item.get("memory_type", "")).strip().lower()
            if memory_type == "semantic":
                counts["retrieval_returned_semantic"] += 1
            elif memory_type == "episodic":
                counts["retrieval_returned_episodic"] += 1
            elif memory_type == "reflection":
                counts["retrieval_returned_reflection"] += 1
            else:
                counts["retrieval_returned_unknown"] += 1
        return final, {"intent": intent, "retrieved_count": len(retrieved), "counts": counts}

    # ------------------------------------------------------------------
    # Query entity extraction via entity-index lookup
    # ------------------------------------------------------------------

    def _build_entity_index(self, events: list[dict[str, Any]]) -> set[str]:
        """Collect all unique entity strings from events into a lowercase set."""
        index: set[str] = set()
        for evt in events:
            for e in evt.get("entities") or []:
                if isinstance(e, str) and e.strip():
                    index.add(e.strip().lower())
        return index

    def _extract_query_entities(
        self, query: str, entity_index: set[str],
    ) -> set[str]:
        """Extract entities from a query by matching tokens against known entities.

        Complements the capitalization-based ``_extract_entities`` by handling
        lowercase queries like "who are alice and bob".  Matches unigrams and
        bigrams against the entity index built from events.
        """
        words = re.findall(r"[a-z0-9][\w-]*", query.lower())
        matched: set[str] = set()
        for w in words:
            if w in entity_index:
                matched.add(w)
        # Also check bigrams (e.g. "github actions", "knowledge graph")
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i + 1]}"
            if bigram in entity_index:
                matched.add(bigram)
        return matched

    def _build_graph_context_lines(
        self,
        query: str,
        retrieved: list[dict[str, Any]],
        max_tokens: int = 100,
    ) -> list[str]:
        """Build entity relationship summary lines from Neo4j and local event triples.

        Queries the knowledge graph first (when available), then falls back to
        scanning triples stored in local events.
        """
        query_entities = {e.lower() for e in self.extractor._extract_entities(query)}

        # Also extract entities via index lookup (handles lowercase queries).
        events = self.read_events(limit=200)
        entity_index = self._build_entity_index(events)
        query_entities |= self._extract_query_entities(query, entity_index)

        for item in retrieved:
            for e in item.get("entities") or []:
                if isinstance(e, str) and e.strip():
                    query_entities.add(e.strip().lower())

        if not query_entities:
            return []

        # Collect relevant triples — Neo4j first, then local event fallback.
        rel_triples: list[tuple[str, str, str]] = []

        if self.graph.enabled:
            rel_triples.extend(
                self.graph.get_triples_for_entities_sync(query_entities)
            )

        # Supplement with local event triples (may add context Neo4j lacks).
        for evt in events:
            for triple in evt.get("triples") or []:
                subj = str(triple.get("subject", "")).strip()
                pred = str(triple.get("predicate", "")).strip()
                obj = str(triple.get("object", "")).strip()
                if not subj or not pred or not obj:
                    continue
                if subj.lower() in query_entities or obj.lower() in query_entities:
                    rel_triples.append((subj, pred, obj))

        if not rel_triples:
            return []

        # Deduplicate and format as compact lines, respecting token budget.
        # Annotate entities with ontology types to help the LLM disambiguate.
        from .ontology import classify_entity_type

        seen: set[tuple[str, str, str]] = set()
        graph_lines: list[str] = []
        total_chars = 0
        max_chars = max_tokens * 4

        for subj, pred, obj in rel_triples:
            key = (subj.lower(), pred, obj.lower())
            if key in seen:
                continue
            seen.add(key)
            s_type = classify_entity_type(subj).value
            o_type = classify_entity_type(obj).value
            s_label = f"{subj} [{s_type}]" if s_type != "unknown" else subj
            o_label = f"{obj} [{o_type}]" if o_type != "unknown" else obj
            line = f"- {s_label} → {pred} → {o_label}"
            if total_chars + len(line) > max_chars:
                break
            graph_lines.append(line)
            total_chars += len(line)

        return graph_lines

    def _profile_section_lines(
        self, profile: dict[str, Any], max_items_per_section: int = 6
    ) -> list[str]:
        lines: list[str] = []
        title_map = {
            "preferences": "Preferences",
            "stable_facts": "Stable Facts",
            "active_projects": "Active Projects",
            "relationships": "Relationships",
            "constraints": "Constraints",
        }
        for key in self.PROFILE_KEYS:
            values = self._to_str_list(profile.get(key))
            if not values:
                continue
            section_meta = self._meta_section(profile, key)
            scored_values: list[tuple[str, float, int]] = []
            for value in values:
                meta = (
                    section_meta.get(self._norm_text(value), {})
                    if isinstance(section_meta, dict)
                    else {}
                )
                status = meta.get("status") if isinstance(meta, dict) else None
                pinned = bool(meta.get("pinned")) if isinstance(meta, dict) else False
                if status == self.PROFILE_STATUS_STALE and not pinned:
                    continue
                conf = self._safe_float(
                    meta.get("confidence") if isinstance(meta, dict) else None, 0.65
                )
                pin_rank = 1 if pinned else 0
                scored_values.append((value, conf, pin_rank))
            scored_values.sort(key=lambda item: (item[2], item[1]), reverse=True)
            if not scored_values:
                continue
            lines.append(f"### {title_map[key]}")
            for item, confidence, pin_rank in scored_values[:max_items_per_section]:
                pin_suffix = " 📌" if pin_rank else ""
                lines.append(f"- {item} (conf={confidence:.2f}){pin_suffix}")
            lines.append("")
        return lines

    @staticmethod
    def _is_resolved_task_or_decision(summary: str) -> bool:
        text = summary.lower()
        resolved_markers = (
            "done",
            "completed",
            "resolved",
            "closed",
            "finished",
            "cancelled",
            "canceled",
        )
        return any(marker in text for marker in resolved_markers)

    def _recent_unresolved(
        self, events: list[dict[str, Any]], max_items: int = 8
    ) -> list[dict[str, Any]]:
        unresolved: list[dict[str, Any]] = []
        for event in reversed(events):
            event_type = str(event.get("type", ""))
            if event_type not in {"task", "decision"}:
                continue
            status = str(event.get("status", "")).strip().lower()
            if status == self.EPISODIC_STATUS_RESOLVED:
                continue
            summary = str(event.get("summary", "")).strip()
            if not summary or self._is_resolved_task_or_decision(summary):
                continue
            unresolved.append(event)
            if len(unresolved) >= max_items:
                break
        unresolved.reverse()
        return unresolved

    @staticmethod
    def _memory_item_line(item: dict[str, Any]) -> str:
        timestamp = str(item.get("timestamp", ""))[:16]
        event_type = item.get("type", "fact")
        summary = item.get("summary", "")
        reason = item.get("retrieval_reason", {})
        return (
            f"- [{timestamp}] ({event_type}) {summary} "
            f"[sem={reason.get('semantic', 0):.2f}, rec={reason.get('recency', 0):.2f}, src={reason.get('provider', 'mem0')}]"
        )

    # ------------------------------------------------------------------
    # MEMORY.md capping (Step 5)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_md_sections(text: str) -> list[tuple[str, str]]:
        """Split markdown text into (heading, body) pairs.

        Sections are delimited by ``## `` headings.  Text before the first
        heading is returned with heading ``""``.
        """
        import re

        parts = re.split(r"(?m)^(## .+)$", text)
        sections: list[tuple[str, str]] = []
        if parts and not parts[0].startswith("## "):
            preamble = parts.pop(0).strip()
            if preamble:
                sections.append(("", preamble))
        while parts:
            heading = parts.pop(0).strip()
            body = parts.pop(0).strip() if parts else ""
            sections.append((heading, body))
        return sections

    def _cap_long_term_text(
        self,
        long_term_text: str,
        token_cap: int,
        query: str,
    ) -> str:
        """Return *long_term_text* capped to *token_cap* tokens.

        When the full text exceeds the cap, sections are ranked by a simple
        keyword-overlap score against *query* and the top sections that fit
        within the budget are selected (most relevant first).
        """
        if token_cap <= 0 or not long_term_text:
            return long_term_text

        if self._estimate_tokens(long_term_text) <= token_cap:
            return long_term_text

        sections = self._split_md_sections(long_term_text)
        if not sections:
            # No headings — hard-truncate
            chars = token_cap * 4
            return long_term_text[:chars].rsplit("\n", 1)[0] + "\n(long-term memory truncated)"

        # Score each section by keyword overlap with the query
        query_words = set(query.lower().split()) if query else set()

        def _score(heading: str, body: str) -> float:
            text_words = set((heading + " " + body).lower().split())
            overlap = len(query_words & text_words)
            # Boost: shorter sections cost less budget and are proportionally more valuable
            brevity = 1.0 / max(1, self._estimate_tokens(body) / 100)
            return overlap + brevity * 0.5

        scored = sorted(
            sections,
            key=lambda s: _score(s[0], s[1]),
            reverse=True,
        )

        selected: list[tuple[str, str]] = []
        used = 0
        for heading, body in scored:
            section_text = f"{heading}\n{body}" if heading else body
            section_tokens = self._estimate_tokens(section_text)
            if used + section_tokens > token_cap and selected:
                break
            selected.append((heading, body))
            used += section_tokens

        # Preserve original ordering
        original_order = {id(s): i for i, s in enumerate(sections)}
        selected.sort(key=lambda s: original_order.get(id(s), 0))

        out_parts = []
        for heading, body in selected:
            if heading:
                out_parts.append(f"{heading}\n{body}")
            else:
                out_parts.append(body)

        result = "\n\n".join(out_parts)
        if len(selected) < len(sections):
            result += "\n(some long-term memory sections omitted to fit context budget)"
        return result

    def _fit_lines_to_token_cap(self, lines: list[str], *, token_cap: int) -> list[str]:
        if token_cap <= 0 or not lines:
            return []
        out: list[str] = []
        used = 0
        for line in lines:
            line_tokens = self._estimate_tokens(line)
            if out and used + line_tokens > token_cap:
                out.append("- ... (section truncated to token budget)")
                break
            out.append(line)
            used += line_tokens
        return out

    # ------------------------------------------------------------------
    # Budget-aware context section allocation
    # ------------------------------------------------------------------

    # Intent → per-section priority weights.  Higher weight means the
    # section receives a larger share of the total token budget.  Weights
    # are relative — they're normalised to sum to 1.0 during allocation.
    _SECTION_PRIORITY_WEIGHTS: dict[str, dict[str, float]] = {
        "fact_lookup": {
            "long_term": 0.28,
            "profile": 0.23,
            "semantic": 0.20,
            "episodic": 0.05,
            "reflection": 0.00,
            "graph": 0.19,
            "unresolved": 0.05,
        },
        "debug_history": {
            "long_term": 0.15,
            "profile": 0.10,
            "semantic": 0.10,
            "episodic": 0.35,
            "reflection": 0.05,
            "graph": 0.15,
            "unresolved": 0.10,
        },
        "planning": {
            "long_term": 0.15,
            "profile": 0.15,
            "semantic": 0.20,
            "episodic": 0.20,
            "reflection": 0.05,
            "graph": 0.15,
            "unresolved": 0.10,
        },
        "reflection": {
            "long_term": 0.15,
            "profile": 0.10,
            "semantic": 0.15,
            "episodic": 0.10,
            "reflection": 0.25,
            "graph": 0.15,
            "unresolved": 0.10,
        },
        "constraints_lookup": {
            "long_term": 0.19,
            "profile": 0.28,
            "semantic": 0.24,
            "episodic": 0.05,
            "reflection": 0.00,
            "graph": 0.19,
            "unresolved": 0.05,
        },
        "rollout_status": {
            "long_term": 0.25,
            "profile": 0.15,
            "semantic": 0.30,
            "episodic": 0.00,
            "reflection": 0.00,
            "graph": 0.20,
            "unresolved": 0.10,
        },
        "conflict_review": {
            "long_term": 0.15,
            "profile": 0.20,
            "semantic": 0.20,
            "episodic": 0.15,
            "reflection": 0.00,
            "graph": 0.20,
            "unresolved": 0.10,
        },
    }

    # Minimum token allocation per section — ensures every section gets at
    # least this much budget regardless of priority weight, as long as the
    # section has content.  A section with zero weight or no content gets 0.
    _SECTION_MIN_TOKENS = 40

    @classmethod
    def _allocate_section_budgets(
        cls,
        total_budget: int,
        intent: str,
        section_sizes: dict[str, int],
    ) -> dict[str, int]:
        """Distribute *total_budget* tokens across named sections.

        Uses a two-pass proportional allocation:

        1. **Priority pass** — each section gets a share proportional to its
           intent-specific weight, capped at its actual content size.
        2. **Redistribution pass** — tokens freed by sections that are
           smaller than their share are redistributed to sections that need
           more space, again proportionally by weight.

        Parameters
        ----------
        total_budget:
            Total token budget for the combined memory context.
        intent:
            Query intent string (drives prioritisation weights).
        section_sizes:
            Mapping of section name → estimated token count of the **full**
            (untruncated) content for that section.  Sections missing from
            the map or with size 0 receive no allocation.

        Returns
        -------
        dict mapping section name → allocated token budget.
        """
        weights = cls._SECTION_PRIORITY_WEIGHTS.get(
            intent,
            cls._SECTION_PRIORITY_WEIGHTS["fact_lookup"],
        )

        # Filter to sections that actually have content *and* non-zero weight.
        active: dict[str, float] = {}
        for name, weight in weights.items():
            size = section_sizes.get(name, 0)
            if size > 0 and weight > 0:
                active[name] = weight

        if not active:
            return {name: 0 for name in weights}

        total_weight = sum(active.values())
        allocations: dict[str, int] = {name: 0 for name in weights}

        # Pass 1: proportional allocation capped at actual size.
        surplus = 0
        uncapped: dict[str, float] = {}
        for name, weight in active.items():
            share = int(total_budget * (weight / total_weight))
            actual_size = section_sizes.get(name, 0)
            if share >= actual_size:
                # Section fits entirely — cap and reclaim the surplus.
                allocations[name] = actual_size
                surplus += share - actual_size
            else:
                # Section needs more than its share.
                allocations[name] = max(share, cls._SECTION_MIN_TOKENS)
                uncapped[name] = weight

        # Pass 2: redistribute surplus to sections that couldn't fit.
        if surplus > 0 and uncapped:
            uncapped_total = sum(uncapped.values())
            for name, weight in uncapped.items():
                extra = int(surplus * (weight / uncapped_total))
                actual_size = section_sizes.get(name, 0)
                allocations[name] = min(allocations[name] + extra, actual_size)

        return allocations

    def get_memory_context(
        self,
        *,
        query: str | None = None,
        retrieval_k: int = 6,
        token_budget: int = 900,
        memory_md_token_cap: int = 1500,
        mode: str | None = None,
        recency_half_life_days: float | None = None,
        embedding_provider: str | None = None,
    ) -> str:
        intent = self._infer_retrieval_intent(query or "")
        long_term = self.read_long_term()

        profile = self.read_profile()
        try:
            retrieved = self.retrieve(
                query or "",
                top_k=retrieval_k,
                recency_half_life_days=recency_half_life_days,
                embedding_provider=embedding_provider,
            )
        except Exception:  # crash-barrier: multi-subsystem retrieval pipeline
            logger.warning("Memory retrieval failed; continuing with local data only")
            retrieved = []

        budget = max(token_budget, 200)

        # Determine which sections to include based on intent.
        # Episodic is always included now (soft gating via budget weight),
        # but gets higher weight for debug/planning/reflection/conflict intents.
        include_episodic = True
        include_reflection = intent == "reflection"

        # ── Phase 1: build raw (untruncated) content for every section ──

        long_term_text = long_term.strip() if long_term else ""
        if long_term_text and memory_md_token_cap > 0:
            long_term_text = self._cap_long_term_text(
                long_term_text, memory_md_token_cap, query or ""
            )

        profile_lines = self._profile_section_lines(profile)
        profile_text = "\n".join(profile_lines).strip() if profile_lines else ""

        semantic_items = [
            item for item in retrieved if self._memory_type_for_item(item) == "semantic"
        ]
        episodic_items = [
            item for item in retrieved if self._memory_type_for_item(item) == "episodic"
        ]
        reflection_items = [
            item for item in retrieved if self._memory_type_for_item(item) == "reflection"
        ]

        raw_semantic = [self._memory_item_line(item) for item in semantic_items]
        raw_episodic = [self._memory_item_line(item) for item in episodic_items]
        raw_reflection = [self._memory_item_line(item) for item in reflection_items]

        raw_graph: list[str] = []
        if query:
            raw_graph = self._build_graph_context_lines(
                query, retrieved, max_tokens=budget,
            )

        unresolved = self._recent_unresolved(self.read_events(limit=60), max_items=6)
        raw_unresolved: list[str] = []
        if include_episodic and unresolved:
            for item in unresolved:
                ts = str(item.get("timestamp", ""))[:16]
                raw_unresolved.append(
                    f"- [{ts}] ({item.get('type', 'task')}) {item.get('summary', '')}"
                )

        # ── Phase 2: measure raw sizes and allocate budget ──

        section_sizes: dict[str, int] = {
            "long_term": self._estimate_tokens(long_term_text),
            "profile": self._estimate_tokens(profile_text),
            "semantic": self._estimate_tokens("\n".join(raw_semantic)),
            "episodic": self._estimate_tokens("\n".join(raw_episodic)) if include_episodic else 0,
            "reflection": (
                self._estimate_tokens("\n".join(raw_reflection)) if include_reflection else 0
            ),
            "graph": self._estimate_tokens("\n".join(raw_graph)),
            "unresolved": self._estimate_tokens("\n".join(raw_unresolved)),
        }

        alloc = self._allocate_section_budgets(budget, intent, section_sizes)

        # ── Phase 3: fit each section to its allocated budget ──

        if long_term_text and alloc["long_term"] > 0:
            long_term_text = self._cap_long_term_text(
                long_term_text, alloc["long_term"], query or ""
            )

        semantic_lines = self._fit_lines_to_token_cap(
            raw_semantic, token_cap=alloc["semantic"],
        )
        episodic_lines = self._fit_lines_to_token_cap(
            raw_episodic, token_cap=alloc["episodic"],
        )
        reflection_lines = self._fit_lines_to_token_cap(
            raw_reflection, token_cap=alloc["reflection"],
        )
        graph_lines = self._fit_lines_to_token_cap(
            raw_graph, token_cap=alloc["graph"],
        )
        unresolved_lines = self._fit_lines_to_token_cap(
            raw_unresolved, token_cap=alloc["unresolved"],
        )
        fitted_profile_lines = self._fit_lines_to_token_cap(
            profile_lines, token_cap=alloc["profile"],
        )

        # ── Phase 4: assemble in logical presentation order ──

        lines: list[str] = []

        if long_term_text:
            lines.append("## Long-term Memory (project-specific — cite these verbatim)")
            lines.append(long_term_text)

        if fitted_profile_lines:
            lines.append("## Profile Memory")
            lines.append("User-specific facts, preferences, and constraints:")
            lines.extend(fitted_profile_lines)

        if semantic_lines:
            lines.append("## Relevant Semantic Memories")
            lines.append("Retrieved factual knowledge (use these exact terms when answering):")
            lines.extend(semantic_lines)

        if graph_lines:
            lines.append("## Entity Graph")
            lines.append("Verified entity relationships:")
            lines.extend(graph_lines)

        if episodic_lines:
            lines.append("## Relevant Episodic Memories")
            lines.append("Past events and interactions (cite specific details):")
            lines.extend(episodic_lines)

        if include_reflection and reflection_lines:
            lines.append("## Relevant Reflection Memories")
            lines.extend(reflection_lines)

        if unresolved_lines:
            lines.append("## Recent Unresolved Tasks/Decisions")
            lines.extend(unresolved_lines)

        text = "\n".join(lines).strip()

        # Final safety net — should rarely trigger now that every section
        # is individually budget-capped, but guards against heading overhead.
        max_chars = budget * 4
        if len(text) > max_chars:
            text = (
                text[:max_chars].rsplit("\n", 1)[0]
                + "\n- ... (memory context truncated to token budget)"
            )

        est_tokens = max(1, len(text) // 4) if text else 0
        self._metrics.record_many(
            {
                "memory_context_calls": 1,
                "memory_context_tokens_total": est_tokens,
                "memory_context_tokens_long_term_total": self._estimate_tokens(long_term_text),
                "memory_context_tokens_profile_total": self._estimate_tokens(
                    "\n".join(fitted_profile_lines)
                ),
                "memory_context_tokens_semantic_total": self._estimate_tokens(
                    "\n".join(semantic_lines)
                ),
                "memory_context_tokens_episodic_total": self._estimate_tokens(
                    "\n".join(episodic_lines)
                ),
                "memory_context_tokens_reflection_total": self._estimate_tokens(
                    "\n".join(reflection_lines if include_reflection else [])
                ),
                f"memory_context_intent_{intent}": 1,
            }
        )
        self._metrics.set_max("memory_context_tokens_max", est_tokens)
        return text

    def _conflict_pair(self, old_value: str, new_value: str) -> bool:
        old_n = self._norm_text(old_value)
        new_n = self._norm_text(new_value)
        if not old_n or not new_n or old_n == new_n:
            return False
        old_has_not = " not " in f" {old_n} " or "n't" in old_n
        new_has_not = " not " in f" {new_n} " or "n't" in new_n
        if old_has_not == new_has_not:
            return False
        old_tokens = self._tokenize(old_n.replace("not", ""))
        new_tokens = self._tokenize(new_n.replace("not", ""))
        if not old_tokens or not new_tokens:
            return False
        overlap = len(old_tokens & new_tokens) / max(len(old_tokens | new_tokens), 1)
        return overlap >= 0.55

    def _apply_profile_updates(
        self,
        profile: dict[str, Any],
        updates: dict[str, list[str]],
        *,
        enable_contradiction_check: bool,
    ) -> tuple[int, int, int]:
        added = 0
        conflicts = 0
        touched = 0
        profile.setdefault("conflicts", [])

        for key in self.PROFILE_KEYS:
            values = self._to_str_list(profile.get(key))
            seen = {self._norm_text(v) for v in values}
            for candidate in self._to_str_list(updates.get(key)):
                normalized = self._norm_text(candidate)
                if not normalized:
                    continue

                if normalized in seen:
                    entry = self._meta_entry(profile, key, candidate)
                    self._touch_meta_entry(
                        entry, confidence_delta=0.03, status=self.PROFILE_STATUS_ACTIVE
                    )
                    touched += 1
                    continue

                has_conflict = False
                if enable_contradiction_check:
                    for existing in values:
                        if self._conflict_pair(existing, candidate):
                            has_conflict = True
                            old_entry = self._meta_entry(profile, key, existing)
                            self._touch_meta_entry(
                                old_entry,
                                confidence_delta=-0.12,
                                status=self.PROFILE_STATUS_CONFLICTED,
                            )
                            new_entry = self._meta_entry(profile, key, candidate)
                            self._touch_meta_entry(
                                new_entry,
                                confidence_delta=-0.2,
                                min_confidence=0.35,
                                status=self.PROFILE_STATUS_CONFLICTED,
                            )
                            profile["conflicts"].append(
                                {
                                    "timestamp": self._utc_now_iso(),
                                    "field": key,
                                    "old": existing,
                                    "new": candidate,
                                    "old_memory_id": self._find_mem0_id_for_text(existing),
                                    "new_memory_id": self._find_mem0_id_for_text(candidate),
                                    "status": self.CONFLICT_STATUS_OPEN,
                                    "old_confidence": old_entry.get("confidence"),
                                    "new_confidence": new_entry.get("confidence"),
                                }
                            )
                            conflicts += 1
                            touched += 2
                            break

                values.append(candidate)
                seen.add(normalized)
                entry = self._meta_entry(profile, key, candidate)
                if not has_conflict:
                    self._touch_meta_entry(
                        entry, confidence_delta=0.1, status=self.PROFILE_STATUS_ACTIVE
                    )
                    touched += 1
                added += 1

            profile[key] = values

        if conflicts > 0:
            self._record_metric("conflicts_detected", conflicts)
        if added > 0:
            self._record_metric("profile_updates_applied", added)
        return added, conflicts, touched

    def _has_open_conflict(
        self, profile: dict[str, Any], *, field: str, old_value: str, new_value: str
    ) -> bool:
        old_norm = self._norm_text(old_value)
        new_norm = self._norm_text(new_value)
        for item in profile.get("conflicts", []):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            if status not in {self.CONFLICT_STATUS_OPEN, self.CONFLICT_STATUS_NEEDS_USER}:
                continue
            if item.get("field") != field:
                continue
            if self._norm_text(str(item.get("old", ""))) != old_norm:
                continue
            if self._norm_text(str(item.get("new", ""))) != new_norm:
                continue
            return True
        return False

    def _find_mem0_id_for_text(self, text: str, *, top_k: int = 8) -> str | None:
        target = self._norm_text(text)
        if not target or not self.mem0.enabled:
            return None
        search_result = self.mem0.search(text, top_k=top_k)
        if isinstance(search_result, tuple) and len(search_result) == 2:
            rows = search_result[0]
        else:
            rows = search_result if isinstance(search_result, list) else []
        if not rows:
            return None

        for row in rows:
            summary = self._norm_text(str(row.get("summary", "")))
            if summary and (summary == target or target in summary or summary in target):
                value = str(row.get("id", "")).strip()
                if value:
                    return value
        value = str(rows[0].get("id", "")).strip()
        return value or None

    def apply_live_user_correction(
        self,
        content: str,
        *,
        channel: str = "",
        chat_id: str = "",
        enable_contradiction_check: bool = True,
    ) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        preference_corrections = self.extractor.extract_explicit_preference_corrections(text)
        fact_corrections = self.extractor.extract_explicit_fact_corrections(text)
        if not preference_corrections and not fact_corrections:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        self._record_metric("user_corrections", len(preference_corrections) + len(fact_corrections))

        profile = self.read_profile()
        profile.setdefault("conflicts", [])
        applied = 0
        conflicts = 0
        events: list[dict[str, Any]] = []

        def _apply_field_corrections(
            *,
            field: str,
            event_type: str,
            correction_label: str,
            correction_pairs: list[tuple[str, str]],
        ) -> tuple[int, int]:
            local_applied = 0
            local_conflicts = 0
            values = self._to_str_list(profile.get(field))
            by_norm = {self._norm_text(v): v for v in values}

            for new_value, old_value in correction_pairs:
                old_norm = self._norm_text(old_value)
                new_norm = self._norm_text(new_value)
                if not new_norm:
                    continue

                if new_norm not in by_norm:
                    values.append(new_value)
                    by_norm[new_norm] = new_value
                    local_applied += 1

                new_entry = self._meta_entry(profile, field, by_norm[new_norm])
                self._touch_meta_entry(
                    new_entry, confidence_delta=0.08, status=self.PROFILE_STATUS_ACTIVE
                )

                if (
                    enable_contradiction_check
                    and old_norm in by_norm
                    and not self._has_open_conflict(
                        profile,
                        field=field,
                        old_value=by_norm[old_norm],
                        new_value=by_norm[new_norm],
                    )
                ):
                    old_entry = self._meta_entry(profile, field, by_norm[old_norm])
                    self._touch_meta_entry(
                        old_entry,
                        confidence_delta=-0.2,
                        min_confidence=0.35,
                        status=self.PROFILE_STATUS_CONFLICTED,
                    )
                    self._touch_meta_entry(
                        new_entry,
                        confidence_delta=-0.08,
                        min_confidence=0.35,
                        status=self.PROFILE_STATUS_CONFLICTED,
                    )
                    profile["conflicts"].append(
                        {
                            "timestamp": self._utc_now_iso(),
                            "field": field,
                            "old": by_norm[old_norm],
                            "new": by_norm[new_norm],
                            "old_memory_id": self._find_mem0_id_for_text(by_norm[old_norm]),
                            "new_memory_id": self._find_mem0_id_for_text(by_norm[new_norm]),
                            "status": self.CONFLICT_STATUS_OPEN,
                            "old_confidence": old_entry.get("confidence"),
                            "new_confidence": new_entry.get("confidence"),
                            "source": "live_correction",
                        }
                    )
                    local_conflicts += 1

                event = self._coerce_event(
                    {
                        "timestamp": self._utc_now_iso(),
                        "type": event_type,
                        "summary": f"User corrected {correction_label}: {new_value} (not {old_value}).",
                        "entities": [new_value, old_value],
                        "salience": 0.85,
                        "confidence": 0.9,
                        "ttl_days": 365,
                    },
                    source_span=[0, 0],
                    channel=channel,
                    chat_id=chat_id,
                )
                if event:
                    events.append(event)

            profile[field] = values
            return local_applied, local_conflicts

        pref_applied, pref_conflicts = _apply_field_corrections(
            field="preferences",
            event_type="preference",
            correction_label="preference",
            correction_pairs=preference_corrections,
        )
        fact_applied, fact_conflicts = _apply_field_corrections(
            field="stable_facts",
            event_type="fact",
            correction_label="fact",
            correction_pairs=fact_corrections,
        )
        applied += pref_applied + fact_applied
        conflicts += pref_conflicts + fact_conflicts

        if not applied and not conflicts:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        profile["last_verified_at"] = self._utc_now_iso()
        self.write_profile(profile)

        events_written = self.append_events(events)
        if events_written > 0:
            self._record_metric("events_extracted", events_written)

        if applied > 0:
            self._record_metric("profile_updates_applied", applied)
        if conflicts > 0:
            self._record_metric("conflicts_detected", conflicts)

        needs_user = 0
        question: str | None = None
        if conflicts > 0:
            resolution = self.auto_resolve_conflicts(max_items=10)
            needs_user = int(resolution.get("needs_user", 0))
            if needs_user > 0:
                question = self.ask_user_for_conflict()

        if self.mem0.enabled:
            correction_meta, _ = self._normalize_memory_metadata(
                {"topic": "user_correction", "memory_type": "episodic", "stability": "medium"},
                event_type="fact",
                summary=text,
                source="chat",
            )
            correction_meta.update(
                {
                    "event_type": "user_correction",
                    "timestamp": self._utc_now_iso(),
                    "channel": channel,
                    "chat_id": chat_id,
                }
            )
            correction_text = self._sanitize_mem0_text(text, allow_archival=False)
            correction_meta = self._sanitize_mem0_metadata(correction_meta)
            if (
                self.mem0.add_text(
                    correction_text,
                    metadata=correction_meta,
                )
                if correction_text
                else False
            ):
                self._record_mem0_write_metric(str(correction_meta.get("memory_type", "episodic")))
            else:
                self._record_metric("memory_write_failures", 1)

        # Keep LLM-managed MEMORY.md content stable; snapshot can be generated on-demand.
        self.rebuild_memory_snapshot(write=False)
        return {
            "applied": applied,
            "conflicts": conflicts,
            "events": events_written,
            "needs_user": needs_user,
            "question": question,
        }

    def read_long_term(self) -> str:
        return self.persistence.read_text(self.memory_file)

    def write_long_term(self, content: str) -> None:
        self.persistence.write_text(self.memory_file, content)

    def append_history(self, entry: str) -> None:
        self.persistence.append_text(self.history_file, entry.rstrip() + "\n\n")

    def rebuild_memory_snapshot(self, *, max_events: int = 30, write: bool = True) -> str:
        profile = self.read_profile()
        events = self.read_events(limit=max_events)

        parts = ["# Memory", ""]
        section_lines = self._profile_section_lines(profile, max_items_per_section=8)
        if section_lines:
            parts.extend(section_lines)

        unresolved = self._recent_unresolved(events, max_items=6)
        if unresolved:
            parts.append("## Open Tasks & Decisions")
            for event in unresolved:
                ts = str(event.get("timestamp", ""))[:16]
                parts.append(f"- [{ts}] ({event.get('type', 'task')}) {event.get('summary', '')}")
            parts.append("")

        if events:
            parts.append("## Recent Episodic Highlights")
            for event in events[-max_events:]:
                ts = str(event.get("timestamp", ""))[:16]
                parts.append(f"- [{ts}] ({event.get('type', 'fact')}) {event.get('summary', '')}")
        snapshot = "\n".join(parts).strip() + "\n"
        if write:
            self.write_long_term(snapshot)
        return snapshot

    def verify_memory(
        self, *, stale_days: int = 90, update_profile: bool = False
    ) -> dict[str, Any]:
        profile = self.read_profile()
        events = self.read_events()
        now = datetime.now(timezone.utc)
        stale = 0
        total_ttl = 0
        for event in events:
            ttl_days = event.get("ttl_days")
            timestamp = self._to_datetime(str(event.get("timestamp", "")))
            if not timestamp:
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            age_days = (now - timestamp).total_seconds() / 86400.0
            if isinstance(ttl_days, int) and ttl_days > 0:
                total_ttl += 1
                if age_days > ttl_days:
                    stale += 1
            elif age_days > stale_days:
                stale += 1

        stale_profile_items = 0
        profile_touched = False
        for key in self.PROFILE_KEYS:
            section_meta = self._meta_section(profile, key)
            for _, entry in section_meta.items():
                if not isinstance(entry, dict):
                    continue
                last_seen = self._to_datetime(str(entry.get("last_seen_at", "")))
                if not last_seen:
                    continue
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                age_days = max((now - last_seen).total_seconds() / 86400.0, 0.0)
                if age_days > stale_days:
                    stale_profile_items += 1
                    if update_profile and entry.get("status") != self.PROFILE_STATUS_STALE:
                        entry["status"] = self.PROFILE_STATUS_STALE
                        profile_touched = True

        if update_profile:
            profile["last_verified_at"] = self._utc_now_iso()
            profile_touched = True
            if profile_touched:
                self.write_profile(profile)

        open_conflicts = [
            c
            for c in profile.get("conflicts", [])
            if isinstance(c, dict)
            and str(c.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            in {self.CONFLICT_STATUS_OPEN, self.CONFLICT_STATUS_NEEDS_USER}
        ]
        report = {
            "events": len(events),
            "profile_items": sum(len(self._to_str_list(profile.get(k))) for k in self.PROFILE_KEYS),
            "open_conflicts": len(open_conflicts),
            "stale_events": stale,
            "stale_profile_items": stale_profile_items,
            "ttl_tracked_events": total_ttl,
            "last_verified_at": profile.get("last_verified_at"),
        }
        return report

    def _select_messages_for_consolidation(
        self,
        session: Session,
        *,
        archive_all: bool,
        memory_window: int,
    ) -> tuple[list[dict[str, Any]], int, int] | None:
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            source_start = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
            return old_messages, keep_count, source_start

        keep_count = memory_window // 2
        if len(session.messages) <= keep_count:
            return None
        if len(session.messages) - session.last_consolidated <= 0:
            return None
        old_messages = session.messages[session.last_consolidated : -keep_count]
        source_start = session.last_consolidated
        if not old_messages:
            return None
        logger.info(
            "Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count
        )
        return old_messages, keep_count, source_start

    @staticmethod
    def _format_conversation_lines(old_messages: list[dict[str, Any]]) -> list[str]:
        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(
                f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}"
            )
        return lines

    @staticmethod
    def _build_consolidation_prompt(current_memory: str, lines: list[str]) -> str:
        return f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

    def _record_consolidation_input_metrics(self, old_messages: list[dict[str, Any]]) -> None:
        user_messages = [m for m in old_messages if str(m.get("role", "")).lower() == "user"]
        user_corrections = self.extractor.count_user_corrections(old_messages)
        self._record_metrics(
            {
                "messages_processed": len(old_messages),
                "user_messages_processed": len(user_messages),
                "user_corrections": user_corrections,
            }
        )

    def _apply_save_memory_tool_result(self, *, args: dict[str, Any], current_memory: str) -> None:
        if entry := args.get("history_entry"):
            if not isinstance(entry, str):
                entry = json.dumps(entry, ensure_ascii=False)
            self.append_history(entry)
        if update := args.get("memory_update"):
            if not isinstance(update, str):
                update = json.dumps(update, ensure_ascii=False)
            if update != current_memory:
                self.write_long_term(update)

    def _finalize_consolidation(
        self, session: Session, *, archive_all: bool, keep_count: int
    ) -> None:
        session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
        self._record_metric("consolidations", 1)
        # Flush metrics to disk at this natural checkpoint
        self._metrics.flush_sync()
        logger.debug("Memory KPI snapshot: {}", self.get_observability_report().get("kpis", {}))
        logger.info(
            "Memory consolidation done: {} messages, last_consolidated={}",
            len(session.messages),
            session.last_consolidated,
        )

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
        memory_mode: str | None = None,
        enable_contradiction_check: bool = True,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

        Returns True on success (including no-op), False on failure.
        """
        t0 = time.monotonic()
        selection = self._select_messages_for_consolidation(
            session,
            archive_all=archive_all,
            memory_window=memory_window,
        )
        if selection is None:
            return True
        old_messages, keep_count, source_start = selection

        lines = self._format_conversation_lines(old_messages)

        current_memory = self.read_long_term()
        prompt = self._build_consolidation_prompt(current_memory, lines)

        try:
            self._record_consolidation_input_metrics(old_messages)

            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation.",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = self.extractor.parse_tool_args(response.tool_calls[0].arguments)
            if not args:
                logger.warning(
                    "Memory consolidation: unexpected arguments type {}", type(args).__name__
                )
                return False

            self._apply_save_memory_tool_result(args=args, current_memory=current_memory)

            profile = self.read_profile()
            events, profile_updates = await self.extractor.extract_structured_memory(
                provider,
                model,
                profile,
                lines,
                old_messages,
                source_start=source_start,
            )
            events_written = self.append_events(events)
            await self._ingest_graph_triples(events)
            profile_added, _, profile_touched = self._apply_profile_updates(
                profile,
                profile_updates,
                enable_contradiction_check=enable_contradiction_check,
            )
            if events_written > 0 or profile_added > 0 or profile_touched > 0:
                profile["last_verified_at"] = self._utc_now_iso()
                self.write_profile(profile)
                self._record_metric("events_extracted", events_written)

            # Track extraction source and per-type distribution
            source = self.extractor.last_extraction_source
            if source:
                self._record_metric(f"extraction_source_{source}", 1)
            for evt in events:
                etype = str(evt.get("type", "fact"))
                key = f"extraction_events_{etype}"
                if key in self._default_metrics():
                    self._record_metric(key, 1)

            if profile_added > 0:
                self.auto_resolve_conflicts(max_items=10)

            # Keep LLM-managed MEMORY.md content stable; snapshot can be generated on-demand.
            self.rebuild_memory_snapshot(write=False)

            if self.mem0.enabled:
                for m in old_messages:
                    role = str(m.get("role", "user")).strip().lower() or "user"
                    content = str(m.get("content", "")).strip()
                    if not content:
                        continue
                    memory_type = "episodic"
                    if role == "user":
                        memory_type = (
                            "semantic"
                            if self._contains_any(
                                content,
                                (
                                    "prefer",
                                    "always",
                                    "never",
                                    "must",
                                    "cannot",
                                    "my setup",
                                    "i use",
                                ),
                            )
                            else "episodic"
                        )
                    turn_meta, _ = self._normalize_memory_metadata(
                        {
                            "topic": "conversation_turn",
                            "memory_type": memory_type,
                            "stability": "medium",
                        },
                        event_type="fact",
                        summary=content,
                        source="chat",
                    )
                    turn_meta.update(
                        {
                            "event_type": "conversation_turn",
                            "role": role,
                            "timestamp": str(m.get("timestamp", "")),
                            "session": session.key,
                        }
                    )
                    clean_content = self._sanitize_mem0_text(content, allow_archival=False)
                    turn_meta = self._sanitize_mem0_metadata(turn_meta)
                    if (
                        self.mem0.add_text(
                            clean_content,
                            metadata=turn_meta,
                        )
                        if clean_content
                        else False
                    ):
                        self._record_mem0_write_metric(
                            str(turn_meta.get("memory_type", "episodic"))
                        )
                    else:
                        self._record_metric("memory_write_failures", 1)

            self._finalize_consolidation(
                session,
                archive_all=archive_all,
                keep_count=keep_count,
            )
            bind_trace().debug(
                "Memory consolidate events={} duration_ms={:.0f}",
                events_written,
                (time.monotonic() - t0) * 1000,
            )
            return True
        except Exception:  # crash-barrier: multi-stage consolidation must not crash
            logger.exception("Memory consolidation failed")
            return False
