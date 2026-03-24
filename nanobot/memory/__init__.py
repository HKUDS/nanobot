"""Memory subsystem — persistent memory with hybrid retrieval.

Write path:
    extractor.py            LLM + heuristic event extraction
    ingester.py             Event ingestion pipeline
    persistence.py          JSONL/file I/O primitives

Read path:
    retriever.py            Memory retrieval orchestrator
    keyword_search.py       Local keyword/BM25 search
    retrieval_planner.py    Retrieval strategy planning
    reranker.py             Cross-encoder re-ranking interface
    onnx_reranker.py        ONNX Runtime re-ranker implementation
    context_assembler.py    Memory context assembly for prompts
    token_budget.py         Token budget management

Architecture
------------
- **store.py** — ``MemoryStore``: thin facade composing subsystem modules;
  owns cross-cutting coordination (consolidate, get_memory_context).
- **ingester.py** — ``EventIngester``: event write path (classify, dedup,
  merge, append).
- **retriever.py** — ``MemoryRetriever``: retrieval read path (vector +
  FTS5 via UnifiedMemoryDB, with BM25 fallback).
- **maintenance.py** — ``MemoryMaintenance``: reindex, seed, health checks.
- **snapshot.py** — ``MemorySnapshot``: rebuild and verify MEMORY.md.
- **rollout.py** — ``RolloutConfig``: feature flag management.
- **extractor.py** — ``MemoryExtractor``: LLM + heuristic pipeline that
  converts raw conversation turns into structured memory events.
- **unified_db.py** — ``UnifiedMemoryDB``: single SQLite database for all
  memory storage (events, profile, snapshots, vectors via sqlite-vec).
- **embedder.py** — ``Embedder`` protocol, ``OpenAIEmbedder``, and
  ``LocalEmbedder`` for vector embedding generation.
- **reranker.py** — ``Reranker`` protocol and ``CompositeReranker``
  (zero-dependency lightweight alternative).
- **onnx_reranker.py** — ``OnnxCrossEncoderReranker`` (ONNX Runtime-based
  cross-encoder, replaces the old sentence-transformers implementation).
- **constants.py** — Shared constants and tool schemas.

Evaluation (moved to nanobot/eval/):
    memory_eval.py          EvalRunner — retrieval benchmarks + observability
"""

from __future__ import annotations

from .conflicts import ConflictManager
from .consolidation_pipeline import ConsolidationPipeline
from .context_assembler import ContextAssembler
from .embedder import Embedder, HashEmbedder, LocalEmbedder, OpenAIEmbedder
from .entity_classifier import classify_entity_type
from .event import BeliefRecord, KnowledgeTriple, MemoryEvent
from .extractor import MemoryExtractor
from .graph import KnowledgeGraph
from .ingester import EventIngester
from .maintenance import MemoryMaintenance
from .onnx_reranker import OnnxCrossEncoderReranker
from .onnx_reranker import OnnxCrossEncoderReranker as CrossEncoderReranker  # backward-compat
from .ontology_rules import RELATION_RULES, TripleValidation, validate_triple_types
from .ontology_types import (
    AGENT_NATIVE_TYPES,
    AGENT_RELATION_TYPES,
    Entity,
    EntityType,
    Relationship,
    RelationType,
    Triple,
)
from .profile_io import ProfileStore
from .profile_io import ProfileStore as ProfileManager
from .reranker import CompositeReranker, Reranker
from .retrieval_planner import RetrievalPlan, RetrievalPlanner
from .retriever import MemoryRetriever
from .rollout import RolloutConfig
from .snapshot import MemorySnapshot
from .store import MemoryStore
from .unified_db import UnifiedMemoryDB

__all__ = [
    "BeliefRecord",
    "ConflictManager",
    "ConsolidationPipeline",
    "ContextAssembler",
    "Embedder",
    "HashEmbedder",
    "EventIngester",
    "KnowledgeTriple",
    "LocalEmbedder",
    "MemoryEvent",
    "MemoryMaintenance",
    "MemoryRetriever",
    "MemorySnapshot",
    "MemoryStore",
    "OpenAIEmbedder",
    "RetrievalPlan",
    "RetrievalPlanner",
    "RolloutConfig",
    "ProfileManager",
    "ProfileStore",
    "MemoryExtractor",
    "UnifiedMemoryDB",
    "CompositeReranker",
    "CrossEncoderReranker",
    "OnnxCrossEncoderReranker",
    "Reranker",
    "KnowledgeGraph",
    "Entity",
    "EntityType",
    "RelationType",
    "Relationship",
    "Triple",
    "TripleValidation",
    "classify_entity_type",
    "validate_triple_types",
    "RELATION_RULES",
    "AGENT_NATIVE_TYPES",
    "AGENT_RELATION_TYPES",
]
