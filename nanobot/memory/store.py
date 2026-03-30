"""Memory store facade — coordinates subsystem modules.

``MemoryStore`` is a thin facade that composes focused subsystem modules:

- ``EventIngester`` — event write path (classify, dedup, merge, append)
- ``MemoryRetriever`` — retrieval read path (vector, BM25, reranking)
- ``ConsolidationPipeline`` — LLM-driven memory consolidation
- ``MemoryMaintenance`` — reindex, seed, health checks
- ``MemorySnapshot`` — rebuild and verify memory snapshots
Cross-cutting coordination (``get_memory_context``) stays on ``MemoryStore``.
Callers access subsystems directly for specific operations:
``store.ingester.append_events(...)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nanobot.config.memory import MemoryConfig

from ._text import _to_str_list, _utc_now_iso
from .consolidation_pipeline import ConsolidationPipeline
from .constants import PROFILE_KEYS
from .db import MemoryDatabase
from .embedder import HashEmbedder, LocalEmbedder, OpenAIEmbedder
from .graph.graph import KnowledgeGraph
from .maintenance import MemoryMaintenance
from .persistence.profile_io import ProfileStore
from .persistence.snapshot import MemorySnapshot
from .ranking.reranker import CompositeReranker, Reranker
from .read.context_assembler import ContextAssembler
from .read.graph_augmentation import GraphAugmenter
from .read.retrieval_planner import RetrievalPlanner
from .read.retriever import MemoryRetriever
from .read.scoring import RetrievalScorer
from .token_budget import DEFAULT_SECTION_WEIGHTS, TokenBudgetAllocator
from .write.classification import EventClassifier
from .write.coercion import EventCoercer
from .write.conflicts import ConflictManager
from .write.dedup import EventDeduplicator
from .write.extractor import MemoryExtractor
from .write.ingester import EventIngester

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session

    from .embedder import Embedder


class MemoryStore:
    """SQLite-backed memory store with structured profile/events maintenance."""

    def __init__(
        self,
        workspace: Path,
        *,
        memory_config: MemoryConfig | None = None,
        embedding_provider: str | None = None,
        vector_backend: str | None = None,
    ):
        self.workspace = workspace
        self._memory_config: MemoryConfig = memory_config or MemoryConfig()

        # Construct embedder — try OpenAI first, fall back to HashEmbedder.
        # LocalEmbedder (ONNX, ~90MB) is only used when explicitly requested
        # via embedding_provider="local" or "onnx".
        self._embedder: Embedder | None = None
        if embedding_provider in ("local", "onnx"):
            try:
                _local = LocalEmbedder()
                if _local.available:
                    self._embedder = _local
            except Exception:  # crash-barrier: local embedder init failure
                pass
        elif embedding_provider == "hash":
            self._embedder = HashEmbedder()
        else:
            # Default path: try OpenAI, fall back to HashEmbedder.
            try:
                _oai = OpenAIEmbedder()
                if _oai.available:
                    self._embedder = _oai
            except Exception:  # crash-barrier: OpenAI init failure
                pass
        if self._embedder is None:
            self._embedder = HashEmbedder()

        self.memory_dir: Path = workspace / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir: Path = self.memory_dir / "index"

        # Construct unified SQLite database.
        _dims = self._embedder.dims if self._embedder is not None else 384
        self.db: MemoryDatabase = MemoryDatabase(self.memory_dir / "memory.db", dims=_dims)

        self.retriever: MemoryRetriever  # set after graph/ingester init
        # EventIngester is constructed after graph is ready.
        # Deferred until graph is built below; placeholder here for type checkers.
        self.ingester: EventIngester  # set after graph init

        # Classifier and coercer are constructed early so the extractor can use them.
        self._classifier = EventClassifier()
        self._coercer = EventCoercer(self._classifier)

        self.extractor = MemoryExtractor(
            to_str_list=_to_str_list,
            coerce_event=self._coercer.coerce_event,
            utc_now_iso=_utc_now_iso,
        )
        # Profile manager — conflict_mgr and corrector wired after construction
        # (circular dependency: ConflictManager needs ProfileStore and vice versa).
        self.profile_mgr = ProfileStore(db=self.db)

        # Retrieval planner (LAN-207) — intent classification + policy + routing.
        self._planner = RetrievalPlanner()

        # TODO: pass config.memory_section_weights when MemoryStore receives config
        self._budget_allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)

        # MemoryMaintenance: reindex, seed, health checks, backend stats.
        self.maintenance = MemoryMaintenance(
            db=self.db,
            reindex_fn=self._reindex_callback,
        )

        # Cross-encoder re-ranker (Step 7)
        reranker_model = self._memory_config.reranker.model.strip()
        reranker_alpha = self._memory_config.reranker.alpha
        self._reranker: Reranker
        if reranker_model.startswith("onnx:"):
            from .ranking.onnx_reranker import OnnxCrossEncoderReranker

            self._reranker = OnnxCrossEncoderReranker(
                model_name=reranker_model.split(":", 1)[1], alpha=reranker_alpha
            )
        else:
            self._reranker = CompositeReranker(alpha=reranker_alpha)

        # Knowledge graph (SQLite-backed via GraphStore).
        graph_enabled = self._memory_config.graph_enabled
        if graph_enabled:
            self.graph = KnowledgeGraph(db=self.db.graph_store)
        else:
            self.graph = KnowledgeGraph()  # disabled — all methods return empty

        # EventDeduplicator + EventIngester: own the full event write path.
        self._dedup = EventDeduplicator(
            coercer=self._coercer,
            conflict_pair_fn=self.profile_mgr._conflict_pair,
        )
        self.ingester = EventIngester(
            coercer=self._coercer,
            dedup=self._dedup,
            graph=self.graph,
            db=self.db.event_store,
            embedder=self._embedder,
        )

        # Conflict manager — now wire into ProfileStore (circular dep resolved
        # via post-construction wiring instead of lambda callbacks).
        self.conflict_mgr = ConflictManager(
            self.profile_mgr,
            db=self.db,
            memory_config=self._memory_config,
        )
        self.profile_mgr.set_conflict_mgr(self.conflict_mgr)

        # RetrievalScorer + GraphAugmenter + MemoryRetriever: read path.
        self._scorer = RetrievalScorer(
            profile_mgr=self.profile_mgr,
            reranker=self._reranker,
            memory_config=self._memory_config,
        )
        self._graph_aug = GraphAugmenter(
            graph=self.graph,
            extractor=self.extractor,
            read_events_fn=self.ingester.read_events,
        )
        self.retriever = MemoryRetriever(
            scorer=self._scorer,
            graph_aug=self._graph_aug,
            planner=self._planner,
            db=self.db.event_store,
            embedder=self._embedder,
        )

        # Context assembler (LAN-210) — prompt rendering extracted from MemoryStore.
        # Constructed after retriever/ingester/graph_aug so all dependencies
        # are direct references (no lambda callbacks needed).
        self._assembler = ContextAssembler(
            profile_mgr=self.profile_mgr,
            retriever=self.retriever,
            planner=self._planner,
            event_reader=self.ingester,
            graph_augmenter=self._graph_aug,
            budget_allocator=self._budget_allocator,
            db=self.db,
            embedder_available=self._embedder is not None,
        )

        # Evaluation / observability helper (LAN-204)
        from nanobot.eval.memory_eval import EvalRunner

        self.eval_runner = EvalRunner(
            retriever=self.retriever,
            workspace=self.workspace,
            memory_dir=self.memory_dir,
            memory_config=self._memory_config,
            maintenance=self.maintenance,
        )

        # MemorySnapshot: rebuild memory snapshots + verify integrity.
        self.snapshot = MemorySnapshot(
            profile_mgr=self.profile_mgr,
            profile_section_lines_fn=self._assembler._profile_section_lines,
            recent_unresolved_fn=self._assembler._recent_unresolved,
            profile_keys=PROFILE_KEYS,
            db=self.db,
        )

        # CorrectionOrchestrator — wire into ProfileStore (post-construction).
        from .persistence.profile_correction import (
            CorrectionOrchestrator as _CorrectionOrchestrator,
        )

        self._corrector = _CorrectionOrchestrator(
            profile_store=self.profile_mgr,
            extractor=self.extractor,
            ingester=self.ingester,
            coercer=self._coercer,
            conflict_mgr=self.conflict_mgr,
            snapshot=self.snapshot,
        )
        self.profile_mgr.set_corrector(self._corrector)

        # ConsolidationPipeline: full consolidate workflow (LAN-215).
        self._consolidation = ConsolidationPipeline(
            extractor=self.extractor,
            ingester=self.ingester,
            profile_mgr=self.profile_mgr,
            conflict_mgr=self.conflict_mgr,
            snapshot=self.snapshot,
            db=self.db,
        )

    # ------------------------------------------------------------------
    # Computed properties and internal callbacks
    # ------------------------------------------------------------------

    @property
    def memory_config(self) -> MemoryConfig:
        """Typed memory configuration."""
        return self._memory_config

    def _reindex_callback(self) -> None:
        """Void-typed wrapper for MemoryMaintenance.reindex_fn."""
        self.maintenance.reindex_from_structured_memory(
            read_profile_fn=self.profile_mgr.read_profile,
            read_events_fn=self.ingester.read_events,
            ingester=self.ingester,
            profile_keys=PROFILE_KEYS,
        )

    # ------------------------------------------------------------------
    # get_memory_context — facade method
    # ------------------------------------------------------------------

    async def get_memory_context(
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
        return await self._assembler.build(
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
        """Consolidate old messages into SQLite snapshots and history via LLM tool call.

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
