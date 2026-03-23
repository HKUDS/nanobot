"""Memory system for persistent agent memory.

This package decomposes the memory subsystem into focused modules while
preserving backward-compatible imports::

    from nanobot.agent.memory import MemoryStore      # facade (coordination)
    from nanobot.agent.memory import EventIngester     # write path
    from nanobot.agent.memory import MemoryRetriever   # read path
    from nanobot.agent.memory import MemoryMaintenance # reindex, seed, health
    from nanobot.agent.memory import MemorySnapshot    # MEMORY.md rebuild
    from nanobot.agent.memory import RolloutConfig     # feature flags

Architecture
------------
- **store.py** — ``MemoryStore``: thin facade composing subsystem modules;
  owns cross-cutting coordination (consolidate, get_memory_context).
- **ingester.py** — ``EventIngester``: event write path (classify, dedup,
  merge, append).
- **retriever.py** — ``MemoryRetriever``: retrieval read path (mem0, BM25
  fallback, reranking).
- **maintenance.py** — ``MemoryMaintenance``: reindex, seed, health checks.
- **snapshot.py** — ``MemorySnapshot``: rebuild and verify MEMORY.md.
- **rollout.py** — ``RolloutConfig``: feature flag management.
- **extractor.py** — ``MemoryExtractor``: LLM + heuristic pipeline that
  converts raw conversation turns into structured memory events.
- **persistence.py** — ``MemoryPersistence``: low-level I/O for
  ``events.jsonl`` (append-only), ``profile.json``, ``MEMORY.md``, and
  ``HISTORY.md``.
- **mem0_adapter.py** — ``_Mem0Adapter``: wraps the mem0 SDK with health
  checks and automatic fallback.
- **reranker.py** — ``Reranker`` protocol and ``CompositeReranker``
  (zero-dependency lightweight alternative).
- **onnx_reranker.py** — ``OnnxCrossEncoderReranker`` (ONNX Runtime-based
  cross-encoder, replaces the old sentence-transformers implementation).
- **constants.py** — Shared constants and tool schemas.
"""

from __future__ import annotations

from .conflicts import ConflictManager
from .consolidation_pipeline import ConsolidationPipeline
from .context_assembler import ContextAssembler
from .entity_classifier import classify_entity_type
from .eval import EvalRunner
from .event import BeliefRecord, KnowledgeTriple, MemoryEvent
from .extractor import MemoryExtractor
from .graph import KnowledgeGraph
from .ingester import EventIngester
from .maintenance import MemoryMaintenance
from .mem0_adapter import _Mem0Adapter, _Mem0RuntimeInfo
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
from .persistence import MemoryPersistence
from .profile_io import ProfileStore
from .profile_io import ProfileStore as ProfileManager
from .reranker import CompositeReranker, Reranker
from .retrieval_planner import RetrievalPlan, RetrievalPlanner
from .retriever import MemoryRetriever
from .rollout import RolloutConfig
from .snapshot import MemorySnapshot
from .store import MemoryStore

__all__ = [
    "BeliefRecord",
    "ConflictManager",
    "ConsolidationPipeline",
    "ContextAssembler",
    "EventIngester",
    "EvalRunner",
    "KnowledgeTriple",
    "MemoryEvent",
    "MemoryMaintenance",
    "MemoryRetriever",
    "MemorySnapshot",
    "MemoryStore",
    "RetrievalPlan",
    "RetrievalPlanner",
    "RolloutConfig",
    "ProfileManager",
    "ProfileStore",
    "MemoryExtractor",
    "MemoryPersistence",
    "CompositeReranker",
    "CrossEncoderReranker",
    "OnnxCrossEncoderReranker",
    "Reranker",
    "KnowledgeGraph",
    "_Mem0Adapter",
    "_Mem0RuntimeInfo",
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
