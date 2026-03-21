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

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.prompt_loader import prompts
from nanobot.agent.tracing import bind_trace

from .conflicts import (
    CONFLICT_STATUS_NEEDS_USER,
    CONFLICT_STATUS_OPEN,
    CONFLICT_STATUS_RESOLVED,
    ConflictManager,
)
from .constants import _SAVE_MEMORY_TOOL
from .context_assembler import ContextAssembler
from .eval import EvalRunner
from .extractor import MemoryExtractor
from .graph import KnowledgeGraph
from .helpers import (
    _GRAPH_QUERY_STOPWORDS,
    _contains_any,
    _estimate_tokens,
    _extract_query_keywords,
    _norm_text,
    _safe_float,
    _to_datetime,
    _to_str_list,
    _tokenize,
    _utc_now_iso,
)
from .ingester import EventIngester
from .maintenance import MemoryMaintenance
from .mem0_adapter import _Mem0Adapter
from .persistence import MemoryPersistence
from .profile import ProfileManager
from .reranker import CompositeReranker, Reranker
from .retrieval_planner import RetrievalPlanner
from .retriever import MemoryRetriever
from .rollout import RolloutConfig

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
    CONFLICT_STATUS_OPEN = CONFLICT_STATUS_OPEN
    CONFLICT_STATUS_NEEDS_USER = CONFLICT_STATUS_NEEDS_USER
    CONFLICT_STATUS_RESOLVED = CONFLICT_STATUS_RESOLVED
    EPISODIC_STATUS_OPEN = "open"
    EPISODIC_STATUS_RESOLVED = "resolved"
    ROLLOUT_MODES = RolloutConfig.ROLLOUT_MODES  # backward compat alias

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
        self.index_dir: Path = self.memory_dir / "index"
        self.retriever: MemoryRetriever  # set after graph/ingester init
        # EventIngester is constructed after persistence/mem0/graph are ready.
        # Deferred until graph is built below; placeholder here for type checkers.
        self.ingester: EventIngester  # set after graph init

        self.extractor = MemoryExtractor(
            to_str_list=_to_str_list,
            coerce_event=lambda raw, **kw: self.ingester._coerce_event(raw, **kw),
            utc_now_iso=_utc_now_iso,
        )
        self._rollout_config = RolloutConfig(overrides=rollout_overrides)
        self.rollout = self._rollout_config.rollout  # backward compat dict reference
        self.mem0 = _Mem0Adapter(
            workspace=workspace,
            user_id=str(self.rollout.get("mem0_user_id", "nanobot")),
            add_debug=bool(self.rollout.get("mem0_add_debug", False)),
            verify_write=bool(self.rollout.get("mem0_verify_write", True)),
            force_infer_true=bool(self.rollout.get("mem0_force_infer_true", False)),
        )

        # Profile manager (LAN-202) — delegates profile CRUD to ProfileManager.
        self.profile_mgr = ProfileManager(self.persistence, self.profile_file, self.mem0)
        self.profile_mgr._store = self

        # Conflict manager (LAN-203) — delegates conflict resolution to ConflictManager.
        self.conflict_mgr = ConflictManager(self.profile_mgr, self.mem0)
        self.conflict_mgr._store = self

        # Retrieval planner (LAN-207) — intent classification + policy + routing.
        self._planner = RetrievalPlanner()

        # Context assembler (LAN-210) — prompt rendering extracted from MemoryStore.
        self._assembler = ContextAssembler(
            profile_mgr=self.profile_mgr,
            retrieve_fn=lambda *a, **kw: self.retrieve(*a, **kw),
            persistence=self.persistence,
            planner=self._planner,
            read_events_fn=lambda **kw: self.ingester.read_events(**kw),
            read_long_term_fn=lambda: self.read_long_term(),
            build_graph_context_lines_fn=lambda *a, **kw: self.retriever._build_graph_context_lines(
                *a, **kw
            ),
        )

        # MemoryMaintenance: reindex, seed, health checks, backend stats.
        self.maintenance = MemoryMaintenance(
            mem0=self.mem0,
            persistence=self.persistence,
            rollout=self.rollout,
        )
        # Wire reindex callback so health check can trigger reindex.
        self.maintenance._reindex_fn = lambda: self.reindex_from_structured_memory()

        # Cross-encoder re-ranker (Step 7)
        reranker_model = str(
            self.rollout.get("reranker_model", "onnx:ms-marco-MiniLM-L-6-v2")
        ).strip()
        reranker_alpha = float(self.rollout.get("reranker_alpha", 0.5))
        self._reranker: Reranker
        if reranker_model.startswith("onnx:"):
            from .onnx_reranker import OnnxCrossEncoderReranker

            self._reranker = OnnxCrossEncoderReranker(
                model_name=reranker_model.split(":", 1)[1], alpha=reranker_alpha
            )
        else:
            self._reranker = CompositeReranker(alpha=reranker_alpha)

        # Knowledge graph (networkx + JSON persistence).
        graph_enabled = self.rollout.get("graph_enabled", False)
        if graph_enabled:
            self.graph = KnowledgeGraph(workspace=workspace)
        else:
            self.graph = KnowledgeGraph()  # disabled — all methods return empty

        # EventIngester: owns the full event write path.
        self.ingester = EventIngester(
            persistence=self.persistence,
            mem0=self.mem0,
            graph=self.graph,
            rollout=self.rollout,
            conflict_pair_fn=lambda old, new: self.profile_mgr._conflict_pair(old, new),
        )

        # MemoryRetriever: owns the full retrieval read path.
        self.retriever = MemoryRetriever(
            mem0=self.mem0,
            graph=self.graph,
            planner=self._planner,
            reranker=self._reranker,
            profile_mgr=self.profile_mgr,
            rollout=self.rollout,
            read_events_fn=self.ingester.read_events,
            extractor=self.extractor,
        )

        # LAN-208: gate raw conversation turn ingestion into mem0.
        # When disabled, only structured events (from extractor) are synced to mem0,
        # clarifying mem0's role as a semantic index rather than a raw transcript store.
        self._mem0_raw_turn_ingestion: bool = bool(
            self.rollout.get("mem0_raw_turn_ingestion", True)
        )

        # Configurable auto-resolve confidence gap threshold.
        self.conflict_auto_resolve_gap: float = float(
            self.rollout.get("conflict_auto_resolve_gap", 0.25)
        )
        self.conflict_mgr.conflict_auto_resolve_gap = self.conflict_auto_resolve_gap

        # P-01/P-02: mtime-based cache for events.jsonl — avoids re-reading the
        # file on every BM25 retrieval call within the same turn.
        self._events_cache: list[dict[str, Any]] | None = None
        self._events_cache_mtime: float = -1.0

        # Evaluation / observability helper (LAN-204)
        # Use lambdas so that test-time MagicMock patches on the instance are honoured.
        self._eval = EvalRunner(
            retrieve_fn=lambda *a, **kw: self.retrieve(*a, **kw),
            persistence=self.persistence,
            workspace=self.workspace,
            get_rollout_status_fn=lambda: self.get_rollout_status(),
            get_rollout_fn=lambda: self.rollout,
            get_backend_stats_fn=lambda: self._backend_stats_for_eval(),
        )

    # -- Shared helpers imported from .helpers --------------------------------
    # Kept as class attributes for backward compatibility with any external
    # callers that use ``MemoryStore._utc_now_iso()`` etc.
    _utc_now_iso = staticmethod(_utc_now_iso)
    _safe_float = staticmethod(_safe_float)
    _norm_text = staticmethod(_norm_text)
    _tokenize = staticmethod(_tokenize)
    _GRAPH_QUERY_STOPWORDS = _GRAPH_QUERY_STOPWORDS
    _extract_query_keywords = staticmethod(_extract_query_keywords)  # type: ignore[assignment]
    _to_str_list = staticmethod(_to_str_list)
    _to_datetime = staticmethod(_to_datetime)
    _estimate_tokens = staticmethod(_estimate_tokens)

    def get_rollout_status(self) -> dict[str, Any]:
        """Return a snapshot of the current rollout config (delegates to RolloutConfig)."""
        return self._rollout_config.get_status()

    _contains_any = staticmethod(_contains_any)

    # ── Thin wrappers delegating to RetrievalPlanner (LAN-207) ──────────

    @staticmethod
    def _infer_retrieval_intent(query: str) -> str:
        return RetrievalPlanner.infer_retrieval_intent(query)

    @staticmethod
    def _retrieval_policy(intent: str) -> dict[str, Any]:
        return RetrievalPlanner.retrieval_policy(intent)

    @staticmethod
    def _query_routing_hints(query: str) -> dict[str, Any]:
        return RetrievalPlanner.query_routing_hints(query)

    def _status_matches_query_hint(
        self,
        *,
        status: str,
        summary: str,
        requires_open: bool,
        requires_resolved: bool,
    ) -> bool:
        return RetrievalPlanner.status_matches_query_hint(
            status=status,
            summary=summary,
            requires_open=requires_open,
            requires_resolved=requires_resolved,
        )

    def _memory_type_for_item(self, item: dict[str, Any]) -> str:
        return RetrievalPlanner.memory_type_for_item(item)

    def _recency_signal(self, timestamp: str, *, half_life_days: float) -> float:
        return RetrievalPlanner.recency_signal(timestamp, half_life_days=half_life_days)

    # Temporary aliases — will be removed in Task 7
    def _default_topic_for_event_type(self, event_type: str) -> str:
        return self.ingester._default_topic_for_event_type(event_type)

    def _classify_memory_type(
        self, *, event_type: str, summary: str, source: str
    ) -> tuple[str, str, bool]:
        return self.ingester._classify_memory_type(
            event_type=event_type, summary=summary, source=source
        )

    def _distill_semantic_summary(self, summary: str) -> str:
        return self.ingester._distill_semantic_summary(summary)

    def _normalize_memory_metadata(
        self,
        metadata: dict[str, Any] | None,
        *,
        event_type: str,
        summary: str,
        source: str,
    ) -> tuple[dict[str, Any], bool]:
        return self.ingester._normalize_memory_metadata(
            metadata, event_type=event_type, summary=summary, source=source
        )

    def _event_mem0_write_plan(self, event: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return self.ingester._event_mem0_write_plan(event)

    @staticmethod
    def _looks_blob_like_summary(summary: str) -> bool:
        return EventIngester._looks_blob_like_summary(summary)

    @staticmethod
    def _sanitize_mem0_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        return EventIngester._sanitize_mem0_metadata(metadata)

    def _sanitize_mem0_text(self, text: str, *, allow_archival: bool = False) -> str:
        return self.ingester._sanitize_mem0_text(text, allow_archival=allow_archival)

    def _mem0_get_all_rows(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return self.maintenance._mem0_get_all_rows(limit=limit)

    def _vector_points_count(self) -> int:
        return self.maintenance._vector_points_count()

    def _history_row_count(self) -> int:
        return self.maintenance._history_row_count()

    def _backend_stats_for_eval(self) -> dict[str, Any]:
        return self.maintenance._backend_stats_for_eval()

    def _event_compaction_key(self, event: dict[str, Any]) -> tuple[str, str, str, str]:
        return MemoryMaintenance._event_compaction_key(event)

    def _compact_events_for_reindex(
        self, events: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        return MemoryMaintenance._compact_events_for_reindex(events)

    def reindex_from_structured_memory(
        self,
        *,
        max_events: int | None = None,
        reset_existing: bool = False,
        compact: bool = False,
    ) -> dict[str, Any]:
        return self.maintenance.reindex_from_structured_memory(
            max_events=max_events,
            reset_existing=reset_existing,
            compact=compact,
            read_profile_fn=self.read_profile,
            read_events_fn=self.ingester.read_events,
            ingester=self.ingester,
            profile_keys=self.PROFILE_KEYS,
            vector_points_count_fn=self._vector_points_count,
            mem0_get_all_rows_fn=self._mem0_get_all_rows,
        )

    def seed_structured_corpus(self, *, profile_path: Path, events_path: Path) -> dict[str, Any]:
        return self.maintenance.seed_structured_corpus(
            profile_path=profile_path,
            events_path=events_path,
            read_profile_fn=self.read_profile,
            write_profile_fn=self.write_profile,
            read_events_fn=self.ingester.read_events,
            ingester=self.ingester,
            profile_keys=self.PROFILE_KEYS,
            vector_points_count_fn=self._vector_points_count,
            mem0_get_all_rows_fn=self._mem0_get_all_rows,
        )

    async def ensure_health(self) -> None:
        """Run vector health check asynchronously (non-blocking)."""
        import asyncio

        await asyncio.to_thread(self._ensure_vector_health)

    def _ensure_vector_health(self) -> None:
        """Backward-compat wrapper that calls store-level aliases.

        Cannot simply delegate to ``maintenance._ensure_vector_health``
        because existing callers/tests patch ``_history_row_count``,
        ``_vector_points_count``, etc. on the store instance.
        """
        if not bool(self.rollout.get("memory_vector_health_enabled", True)):
            return
        if not self.mem0.enabled:
            return
        vector_rows = len(self._mem0_get_all_rows(limit=25))
        vector_points = self._vector_points_count()
        history_rows = self._history_row_count()
        _probe_result = self.mem0.search("__health__", top_k=1, allow_history_fallback=False)
        degraded = history_rows > 0 and vector_rows == 0 and vector_points == 0
        if not degraded:
            return
        if not bool(self.rollout.get("memory_auto_reindex_on_empty_vector", True)):
            return
        self.reindex_from_structured_memory()

    def get_observability_report(self) -> dict[str, Any]:
        """Return backend health and rollout status.

        Legacy per-counter metrics have been removed in favour of Langfuse.
        The ``metrics`` and ``kpis`` keys are kept empty for backward
        compatibility with callers that destructure the return value.
        """
        return self._eval.get_observability_report()

    def evaluate_retrieval_cases(
        self,
        cases: list[dict[str, Any]],
        *,
        default_top_k: int = 6,
        recency_half_life_days: float | None = None,
        embedding_provider: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate retrieval quality using labeled cases."""
        return self._eval.evaluate_retrieval_cases(
            cases,
            default_top_k=default_top_k,
            recency_half_life_days=recency_half_life_days,
            embedding_provider=embedding_provider,
        )

    def save_evaluation_report(
        self,
        evaluation: dict[str, Any],
        observability: dict[str, Any],
        *,
        rollout: dict[str, Any] | None = None,
        output_file: str | None = None,
    ) -> Path:
        """Persist evaluation + observability report to disk and return the file path."""
        return self._eval.save_evaluation_report(
            evaluation,
            observability,
            rollout=rollout,
            output_file=output_file,
        )

    def evaluate_rollout_gates(
        self,
        evaluation: dict[str, Any],
        observability: dict[str, Any],
    ) -> dict[str, Any]:
        return self._eval.evaluate_rollout_gates(evaluation, observability)

    # Temporary aliases — will be removed in Task 7
    def read_events(self, **kw: Any) -> list[dict[str, Any]]:
        return self.ingester.read_events(**kw)

    @staticmethod
    def _merge_source_span(base: list[int] | Any, incoming: list[int] | Any) -> list[int]:
        return EventIngester._merge_source_span(base, incoming)

    def _ensure_event_provenance(self, event: dict[str, Any]) -> dict[str, Any]:
        return self.ingester._ensure_event_provenance(event)

    def _event_similarity(self, left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
        return self.ingester._event_similarity(left, right)

    def _find_semantic_duplicate(
        self,
        candidate: dict[str, Any],
        existing_events: list[dict[str, Any]],
    ) -> tuple[int | None, float]:
        return self.ingester._find_semantic_duplicate(candidate, existing_events)

    def _find_semantic_supersession(
        self,
        candidate: dict[str, Any],
        existing_events: list[dict[str, Any]],
    ) -> int | None:
        return self.ingester._find_semantic_supersession(candidate, existing_events)

    def _merge_events(
        self,
        base: dict[str, Any],
        incoming: dict[str, Any],
        *,
        similarity: float,
    ) -> dict[str, Any]:
        return self.ingester._merge_events(base, incoming, similarity=similarity)

    def append_events(self, events: list[dict[str, Any]]) -> int:
        return self.ingester.append_events(events)

    # Temporary alias — will be removed in Task 7
    async def _ingest_graph_triples(self, events: list[dict[str, Any]]) -> int:
        return await self.ingester._ingest_graph_triples(events)

    def read_profile(self) -> dict[str, Any]:
        return self.profile_mgr.read_profile()

    def _meta_section(self, profile: dict[str, Any], key: str) -> dict[str, Any]:
        return self.profile_mgr._meta_section(profile, key)

    @staticmethod
    def _generate_belief_id(section: str, norm_text: str, created_at: str) -> str:
        """Generate a deterministic stable ID for a profile item."""
        return ProfileManager._generate_belief_id(section, norm_text, created_at)

    def _meta_entry(self, profile: dict[str, Any], key: str, text: str) -> dict[str, Any]:
        return self.profile_mgr._meta_entry(profile, key, text)

    _MAX_EVIDENCE_REFS = 10  # Cap evidence_event_ids to avoid unbounded growth.

    def _touch_meta_entry(
        self,
        entry: dict[str, Any],
        *,
        confidence_delta: float,
        min_confidence: float = 0.05,
        max_confidence: float = 0.99,
        status: str | None = None,
        evidence_event_id: str | None = None,
    ) -> None:
        self.profile_mgr._touch_meta_entry(
            entry,
            confidence_delta=confidence_delta,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            status=status,
            evidence_event_id=evidence_event_id,
        )

    def _validate_profile_field(self, field: str) -> str:
        return self.profile_mgr._validate_profile_field(field)

    def set_item_pin(self, field: str, text: str, *, pinned: bool) -> bool:
        return self.profile_mgr.set_item_pin(field, text, pinned=pinned)

    def mark_item_outdated(self, field: str, text: str) -> bool:
        return self.profile_mgr.mark_item_outdated(field, text)

    def list_conflicts(self, *, include_closed: bool = False) -> list[dict[str, Any]]:
        return self.conflict_mgr.list_conflicts(include_closed=include_closed)

    @staticmethod
    def _parse_conflict_user_action(text: str) -> str | None:
        return ConflictManager._parse_conflict_user_action(text)

    # Language patterns indicating a correction (new value supersedes old).
    _CORRECTION_MARKERS = ConflictManager._CORRECTION_MARKERS

    def _auto_resolution_action(self, conflict: dict[str, Any]) -> str | None:
        return self.conflict_mgr._auto_resolution_action(conflict)

    def auto_resolve_conflicts(self, *, max_items: int = 10) -> dict[str, int]:
        return self.conflict_mgr.auto_resolve_conflicts(max_items=max_items)

    def get_next_user_conflict(self) -> dict[str, Any] | None:
        return self.conflict_mgr.get_next_user_conflict()

    def _conflict_relevant_to(self, conflict: dict[str, Any], user_message: str) -> bool:
        return self.conflict_mgr._conflict_relevant_to(conflict, user_message)

    def ask_user_for_conflict(
        self,
        *,
        include_already_asked: bool = False,
        user_message: str = "",
    ) -> str | None:
        return self.conflict_mgr.ask_user_for_conflict(
            include_already_asked=include_already_asked,
            user_message=user_message,
        )

    def handle_user_conflict_reply(self, text: str) -> dict[str, Any]:
        return self.conflict_mgr.handle_user_conflict_reply(text)

    def resolve_conflict_details(self, index: int, action: str) -> dict[str, Any]:
        return self.conflict_mgr.resolve_conflict_details(index, action)

    def resolve_conflict(self, index: int, action: str) -> bool:
        return self.conflict_mgr.resolve_conflict(index, action)

    def write_profile(self, profile: dict[str, Any]) -> None:
        self.profile_mgr.write_profile(profile)

    def _build_event_id(self, event_type: str, summary: str, timestamp: str) -> str:
        return self.ingester._build_event_id(event_type, summary, timestamp)

    def _infer_episodic_status(
        self, *, event_type: str, summary: str, raw_status: Any = None
    ) -> str | None:
        return self.ingester._infer_episodic_status(
            event_type=event_type, summary=summary, raw_status=raw_status
        )

    def _coerce_event(
        self,
        raw: dict[str, Any],
        *,
        source_span: list[int],
        channel: str = "",
        chat_id: str = "",
    ) -> dict[str, Any] | None:
        return self.ingester._coerce_event(
            raw, source_span=source_span, channel=channel, chat_id=chat_id
        )

    # Temporary backward-compat alias — will be removed in Task 7
    def retrieve(self, *a: Any, **kw: Any) -> list[dict[str, Any]]:
        return self.retriever.retrieve(*a, **kw)

    # Temporary backward-compat aliases — will be removed in Task 7
    def _build_entity_index(self, events: list[dict[str, Any]]) -> set[str]:
        return self.retriever._build_entity_index(events)

    def _extract_query_entities(self, query: str, entity_index: set[str]) -> set[str]:
        return self.retriever._extract_query_entities(query, entity_index)

    def _build_graph_context_lines(
        self,
        query: str,
        retrieved: list[dict[str, Any]],
        max_tokens: int = 100,
    ) -> list[str]:
        return self.retriever._build_graph_context_lines(query, retrieved, max_tokens)

    def _profile_section_lines(
        self, profile: dict[str, Any], max_items_per_section: int = 6
    ) -> list[str]:
        return self._assembler._profile_section_lines(profile, max_items_per_section)

    @staticmethod
    def _is_resolved_task_or_decision(summary: str) -> bool:
        return ContextAssembler._is_resolved_task_or_decision(summary)

    def _recent_unresolved(
        self, events: list[dict[str, Any]], max_items: int = 8
    ) -> list[dict[str, Any]]:
        return self._assembler._recent_unresolved(events, max_items)

    @staticmethod
    def _memory_item_line(item: dict[str, Any]) -> str:
        return ContextAssembler._memory_item_line(item)

    # ------------------------------------------------------------------
    # MEMORY.md capping (Step 5) — delegates to ContextAssembler (LAN-210)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_md_sections(text: str) -> list[tuple[str, str]]:
        """Split markdown text into (heading, body) pairs.

        Sections are delimited by ``## `` headings.  Text before the first
        heading is returned with heading ``""``.
        """
        return ContextAssembler._split_md_sections(text)

    def _cap_long_term_text(
        self,
        long_term_text: str,
        token_cap: int,
        query: str,
    ) -> str:
        """Return *long_term_text* capped to *token_cap* tokens."""
        return self._assembler._cap_long_term_text(long_term_text, token_cap, query)

    def _fit_lines_to_token_cap(self, lines: list[str], *, token_cap: int) -> list[str]:
        return self._assembler._fit_lines_to_token_cap(lines, token_cap=token_cap)

    # ------------------------------------------------------------------
    # Budget-aware context section allocation — delegates to ContextAssembler
    # ------------------------------------------------------------------

    # Keep class-level constants as aliases so test code referencing
    # MemoryStore._SECTION_PRIORITY_WEIGHTS / ._SECTION_MIN_TOKENS still works.
    _SECTION_PRIORITY_WEIGHTS = ContextAssembler._SECTION_PRIORITY_WEIGHTS
    _SECTION_MIN_TOKENS = ContextAssembler._SECTION_MIN_TOKENS

    @classmethod
    def _allocate_section_budgets(
        cls,
        total_budget: int,
        intent: str,
        section_sizes: dict[str, int],
    ) -> dict[str, int]:
        """Distribute *total_budget* tokens across named sections."""
        return ContextAssembler._allocate_section_budgets(total_budget, intent, section_sizes)

    def _ensure_assembler(self) -> ContextAssembler:
        """Return a ``ContextAssembler``, creating it lazily if needed.

        Lazy creation supports test code that constructs ``MemoryStore`` via
        ``__new__`` (bypassing ``__init__``) and then monkeypatches methods
        before calling ``get_memory_context``.

        All patchable helper methods are routed through lambdas that capture
        ``self``, so monkeypatches applied to the store instance are always
        honoured — even when applied after the assembler is first created.
        """
        # Fast path: already initialised (either by __init__ or a previous call).
        assembler = getattr(self, "_assembler", None)
        if isinstance(assembler, ContextAssembler):
            return assembler

        # Use getattr for attrs that may be missing when __init__ was bypassed
        # (e.g. test code using MemoryStore.__new__).
        profile_mgr = getattr(self, "profile_mgr", None)
        persistence = getattr(self, "persistence", None)
        planner = getattr(self, "_planner", None) or RetrievalPlanner()

        self._assembler = ContextAssembler(
            profile_mgr=profile_mgr,  # type: ignore[arg-type]
            retrieve_fn=lambda *a, **kw: self.retrieve(*a, **kw),
            persistence=persistence,  # type: ignore[arg-type]
            planner=planner,
            read_events_fn=lambda **kw: self.read_events(**kw),
            read_long_term_fn=lambda: self.read_long_term(),
            build_graph_context_lines_fn=lambda *a, **kw: self._build_graph_context_lines(*a, **kw),
            cap_long_term_text_fn=lambda text, cap, query: self._cap_long_term_text(
                text, cap, query
            ),
            profile_section_lines_fn=lambda profile, *a: self._profile_section_lines(profile, *a),
            read_profile_fn=lambda: self.read_profile(),
        )
        return self._assembler

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
        return self._ensure_assembler().build(
            query=query,
            retrieval_k=retrieval_k,
            token_budget=token_budget,
            memory_md_token_cap=memory_md_token_cap,
            mode=mode,
            recency_half_life_days=recency_half_life_days,
            embedding_provider=embedding_provider,
        )

    def _conflict_pair(self, old_value: str, new_value: str) -> bool:
        return self.profile_mgr._conflict_pair(old_value, new_value)

    def _apply_profile_updates(
        self,
        profile: dict[str, Any],
        updates: dict[str, list[str]],
        *,
        enable_contradiction_check: bool,
        source_event_ids: list[str] | None = None,
    ) -> tuple[int, int, int]:
        return self.profile_mgr._apply_profile_updates(
            profile,
            updates,
            enable_contradiction_check=enable_contradiction_check,
            source_event_ids=source_event_ids,
        )

    def _has_open_conflict(
        self, profile: dict[str, Any], *, field: str, old_value: str, new_value: str
    ) -> bool:
        return self.profile_mgr._has_open_conflict(
            profile, field=field, old_value=old_value, new_value=new_value
        )

    def _find_mem0_id_for_text(self, text: str, *, top_k: int = 8) -> str | None:
        return self.profile_mgr._find_mem0_id_for_text(text, top_k=top_k)

    def apply_live_user_correction(
        self,
        content: str,
        *,
        channel: str = "",
        chat_id: str = "",
        enable_contradiction_check: bool = True,
    ) -> dict[str, Any]:
        return self.profile_mgr.apply_live_user_correction(
            content,
            channel=channel,
            chat_id=chat_id,
            enable_contradiction_check=enable_contradiction_check,
        )

    def read_long_term(self) -> str:
        return self.persistence.read_text(self.memory_file)

    def write_long_term(self, content: str) -> None:
        self.persistence.write_text(self.memory_file, content)

    def append_history(self, entry: str) -> None:
        self.persistence.append_text(self.history_file, entry.rstrip() + "\n\n")

    def rebuild_memory_snapshot(self, *, max_events: int = 30, write: bool = True) -> str:
        profile = self.read_profile()
        events = self.ingester.read_events(limit=max_events)

        # Preserve user-pinned sections across rebuilds (LAN-199 / LAN-206).
        existing_memory = self.read_long_term()
        pinned = self._extract_pinned_section(existing_memory) if existing_memory else None

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

        if pinned:
            snapshot = self._restore_pinned_section(snapshot, pinned)

        if write:
            self.write_long_term(snapshot)
        return snapshot

    def verify_memory(
        self, *, stale_days: int = 90, update_profile: bool = False
    ) -> dict[str, Any]:
        profile = self.read_profile()
        events = self.ingester.read_events()
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
        belief_quality = self.verify_beliefs()

        report = {
            "events": len(events),
            "profile_items": sum(len(self._to_str_list(profile.get(k))) for k in self.PROFILE_KEYS),
            "open_conflicts": len(open_conflicts),
            "stale_events": stale,
            "stale_profile_items": stale_profile_items,
            "ttl_tracked_events": total_ttl,
            "last_verified_at": profile.get("last_verified_at"),
            "belief_quality": belief_quality["summary"],
        }
        return report

    def verify_beliefs(self) -> dict[str, Any]:
        """Assess belief health based on evidence quality, not just timestamps.

        Delegates to ``ProfileManager.verify_beliefs`` — see LAN-209.
        """
        return self.profile_mgr.verify_beliefs()

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
        return f"""Process this conversation and call the save_memory tool with a history_entry summarizing key events, decisions, and topics.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

    _PINNED_START = "<!-- user-pinned -->"
    _PINNED_END = "<!-- end-user-pinned -->"

    @classmethod
    def _extract_pinned_section(cls, text: str) -> str | None:
        """Extract user-pinned content from MEMORY.md, if present."""
        start = text.find(cls._PINNED_START)
        end = text.find(cls._PINNED_END)
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start : end + len(cls._PINNED_END)]

    @classmethod
    def _restore_pinned_section(cls, new_text: str, pinned: str) -> str:
        """Re-insert a pinned section into new MEMORY.md content.

        If the new text already contains a pinned fence, replace it.
        Otherwise insert the pinned block after the first heading.
        """
        existing = cls._extract_pinned_section(new_text)
        if existing:
            return new_text.replace(existing, pinned)
        # Insert after the first heading line (or at the top).
        lines = new_text.split("\n")
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith("#"):
                insert_at = i + 1
                break
        lines.insert(insert_at, pinned)
        return "\n".join(lines)

    def _apply_save_memory_tool_result(self, *, args: dict[str, Any], current_memory: str) -> None:
        if entry := args.get("history_entry"):
            if not isinstance(entry, str):
                entry = json.dumps(entry, ensure_ascii=False)
            self.append_history(entry)
        # memory_update is intentionally ignored (LAN-206): MEMORY.md is now a
        # pure projection rebuilt deterministically via rebuild_memory_snapshot().

    def _finalize_consolidation(
        self, session: Session, *, archive_all: bool, keep_count: int
    ) -> None:
        session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
        logger.info(
            "Memory consolidation done: {} messages, last_consolidated={}",
            len(session.messages),
            session.last_consolidated,
        )

    # Temporary alias — will be removed in Task 7
    def _sync_events_to_mem0(self, events: list[dict[str, Any]]) -> int:
        return self.ingester._sync_events_to_mem0(events)

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
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": prompts.get("consolidation"),
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
            events_written = self.ingester.append_events(events)
            await self.ingester._ingest_graph_triples(events)
            # Thread event IDs into profile updates for evidence linking (LAN-197).
            event_ids = [e.get("id", "") for e in events if e.get("id")]
            profile_added, _, profile_touched = self._apply_profile_updates(
                profile,
                profile_updates,
                enable_contradiction_check=enable_contradiction_check,
                source_event_ids=event_ids,
            )
            if events_written > 0 or profile_added > 0 or profile_touched > 0:
                profile["last_verified_at"] = self._utc_now_iso()
                self.write_profile(profile)

            # Track extraction source and per-type distribution

            if profile_added > 0:
                self.auto_resolve_conflicts(max_items=10)

            # MEMORY.md is a pure projection from profile + events (LAN-206).
            self.rebuild_memory_snapshot(write=True)

            # LAN-208: sync structured events to mem0 as the primary indexing
            # path — mem0 is a semantic index, not a raw transcript store.
            if self.mem0.enabled and events:
                self.ingester._sync_events_to_mem0(events)

            # LAN-208: raw conversation turn ingestion — legacy behaviour, gated
            # behind _mem0_raw_turn_ingestion (default True for backward compat).
            if self.mem0.enabled and self._mem0_raw_turn_ingestion:
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
                    turn_meta, _ = self.ingester._normalize_memory_metadata(
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
                    clean_content = self.ingester._sanitize_mem0_text(content, allow_archival=False)
                    turn_meta = self.ingester._sanitize_mem0_metadata(turn_meta)
                    if clean_content:
                        self.mem0.add_text(
                            clean_content,
                            metadata=turn_meta,
                        )

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
