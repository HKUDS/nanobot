"""Memory store facade — coordinates subsystem modules.

``MemoryStore`` is a thin facade that composes focused subsystem modules:

- ``EventIngester`` — event write path (classify, dedup, merge, append)
- ``MemoryRetriever`` — retrieval read path (mem0, BM25, reranking)
- ``ConsolidationPipeline`` — LLM-driven memory consolidation
- ``MemoryMaintenance`` — reindex, seed, health checks
- ``MemorySnapshot`` — rebuild and verify MEMORY.md
- ``RolloutConfig`` — feature flag management

Cross-cutting coordination (``get_memory_context``) stays on ``MemoryStore``.
Callers access subsystems directly for specific operations:
``store.ingester.append_events(...)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .conflicts import (
    CONFLICT_STATUS_NEEDS_USER,
    CONFLICT_STATUS_OPEN,
    CONFLICT_STATUS_RESOLVED,
    ConflictManager,
)
from .consolidation_pipeline import ConsolidationPipeline
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
from .profile_io import ProfileStore
from .reranker import CompositeReranker, Reranker
from .retrieval_planner import RetrievalPlanner
from .retriever import MemoryRetriever
from .rollout import RolloutConfig
from .snapshot import MemorySnapshot
from .token_budget import DEFAULT_SECTION_WEIGHTS, TokenBudgetAllocator

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
        # Subsystem references (_extractor, _ingester, _conflict_mgr, _snapshot)
        # are wired after all subsystems are constructed (see below).
        self.profile_mgr = ProfileStore(self.persistence, self.profile_file, self.mem0)

        # Retrieval planner (LAN-207) — intent classification + policy + routing.
        self._planner = RetrievalPlanner()

        # TODO: pass config.memory_section_weights when MemoryStore receives config
        self._budget_allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)

        # Context assembler (LAN-210) — prompt rendering extracted from MemoryStore.
        self._assembler = ContextAssembler(
            profile_mgr=self.profile_mgr,
            retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
            persistence=self.persistence,
            planner=self._planner,
            read_events_fn=lambda **kw: self.ingester.read_events(**kw),
            read_long_term_fn=lambda: self.persistence.read_text(self.memory_file),
            build_graph_context_lines_fn=lambda *a, **kw: self.retriever._build_graph_context_lines(
                *a, **kw
            ),
            budget_allocator=self._budget_allocator,
        )

        # MemoryMaintenance: reindex, seed, health checks, backend stats.
        self.maintenance = MemoryMaintenance(
            mem0=self.mem0,
            persistence=self.persistence,
            rollout=self.rollout,
        )
        # Wire reindex callback so health check can trigger reindex.
        self.maintenance._reindex_fn = lambda: self.maintenance.reindex_from_structured_memory(
            read_profile_fn=self.profile_mgr.read_profile,
            read_events_fn=self.ingester.read_events,
            ingester=self.ingester,
            profile_keys=self.PROFILE_KEYS,
            vector_points_count_fn=self.maintenance._vector_points_count,
            mem0_get_all_rows_fn=self.maintenance._mem0_get_all_rows,
        )

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

        # Conflict manager (LAN-203) — now that ingester is built, wire callables.
        self.conflict_mgr = ConflictManager(
            self.profile_mgr,
            self.mem0,
            sanitize_mem0_text_fn=self.ingester._sanitize_mem0_text,
            normalize_metadata_fn=self.ingester._normalize_memory_metadata,
            sanitize_metadata_fn=EventIngester._sanitize_mem0_metadata,
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
        self.eval_runner = EvalRunner(
            retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
            persistence=self.persistence,
            workspace=self.workspace,
            get_rollout_status_fn=lambda: self._rollout_config.get_status(),
            get_rollout_fn=lambda: self.rollout,
            get_backend_stats_fn=lambda: self.maintenance._backend_stats_for_eval(),
        )

        # MemorySnapshot: rebuild MEMORY.md + verify memory integrity.
        self.snapshot = MemorySnapshot(
            profile_mgr=self.profile_mgr,
            persistence=self.persistence,
            read_events_fn=lambda **kw: self.ingester.read_events(**kw),
            profile_section_lines_fn=lambda profile, **kw: self._assembler._profile_section_lines(
                profile, **kw
            ),
            recent_unresolved_fn=lambda events, **kw: self._assembler._recent_unresolved(
                events, **kw
            ),
            read_long_term_fn=lambda: self.persistence.read_text(self.memory_file),
            write_long_term_fn=lambda content: self.persistence.write_text(
                self.memory_file, content
            ),
            verify_beliefs_fn=lambda: self.profile_mgr.verify_beliefs(),
            write_profile_fn=lambda profile: self.profile_mgr.write_profile(profile),
            profile_keys=self.PROFILE_KEYS,
        )

        # Wire profile_mgr subsystem dependencies (must happen after all are built).
        from .profile_correction import CorrectionOrchestrator as _CorrectionOrchestrator

        self.profile_mgr._conflict_mgr = self.conflict_mgr  # keep — used by delegate wrappers
        self.profile_mgr._corrector = _CorrectionOrchestrator(
            profile_store=self.profile_mgr,
            extractor=self.extractor,
            ingester=self.ingester,
            conflict_mgr=self.conflict_mgr,
            snapshot=self.snapshot,
        )

        # ConsolidationPipeline: full consolidate workflow (LAN-215).
        self._consolidation = ConsolidationPipeline(
            persistence=self.persistence,
            extractor=self.extractor,
            ingester=self.ingester,
            profile_mgr=self.profile_mgr,
            conflict_mgr=self.conflict_mgr,
            snapshot=self.snapshot,
            mem0=self.mem0,
            mem0_raw_turn_ingestion=self._mem0_raw_turn_ingestion,
            memory_file=self.memory_file,
            history_file=self.history_file,
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
    _contains_any = staticmethod(_contains_any)

    # Keep class-level constants as aliases so test code referencing
    # MemoryStore._SECTION_PRIORITY_WEIGHTS / ._SECTION_MIN_TOKENS still works.
    _SECTION_PRIORITY_WEIGHTS = DEFAULT_SECTION_WEIGHTS
    _SECTION_MIN_TOKENS = ContextAssembler._SECTION_MIN_TOKENS
    _MAX_EVIDENCE_REFS = 10  # Cap evidence_event_ids to avoid unbounded growth.
    _CORRECTION_MARKERS = ConflictManager._CORRECTION_MARKERS

    # ------------------------------------------------------------------
    # get_memory_context — facade method (lazy assembler init)
    # ------------------------------------------------------------------

    def _ensure_assembler(self) -> ContextAssembler:
        """Return a ``ContextAssembler``, creating it lazily if needed.

        Lazy creation supports test code that constructs ``MemoryStore`` via
        ``__new__`` (bypassing ``__init__``) and then monkeypatches methods
        before calling ``get_memory_context``.
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
            retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
            persistence=persistence,  # type: ignore[arg-type]
            planner=planner,
            read_events_fn=lambda **kw: self.ingester.read_events(**kw),
            read_long_term_fn=lambda: self.persistence.read_text(self.memory_file),
            build_graph_context_lines_fn=lambda *a, **kw: self.retriever._build_graph_context_lines(
                *a, **kw
            ),
            budget_allocator=getattr(self, "_budget_allocator", None),
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

    # ------------------------------------------------------------------
    # Consolidation pipeline — delegated to ConsolidationPipeline
    # ------------------------------------------------------------------

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
        return await self._consolidation.consolidate(
            session,
            provider,
            model,
            archive_all=archive_all,
            memory_window=memory_window,
            memory_mode=memory_mode,
            enable_contradiction_check=enable_contradiction_check,
        )
