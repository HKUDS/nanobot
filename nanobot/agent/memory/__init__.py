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

Storage:
    mem0_adapter.py         mem0 vector store adapter
    persistence.py          File I/O (events.jsonl, MEMORY.md)

Profile:
    profile_io.py           Profile CRUD + belief verification
    profile_correction.py   LLM-driven profile correction

Knowledge graph:
    graph.py                Knowledge graph (networkx)
    ontology_types.py       Entity/relation type definitions
    ontology_rules.py       Relation constraint rules
    entity_classifier.py    Entity type classification
    entity_linker.py        Entity linking + resolution

Lifecycle:
    consolidation_pipeline.py  Consolidation pipeline
    maintenance.py          Reindex, seed, health checks
    snapshot.py             MEMORY.md rebuild
    conflicts.py            Memory conflict detection/resolution

Infrastructure:
    event.py                MemoryEvent Pydantic model
    constants.py            Shared constants + tool schemas
    helpers.py              Utility functions
    rollout.py              Feature rollout gates

Public API:
    store.py                MemoryStore — the sole external interface

Evaluation (moved to nanobot/eval/):
    memory_eval.py          EvalRunner — retrieval benchmarks + observability
"""

from __future__ import annotations

from .conflicts import ConflictManager
from .consolidation_pipeline import ConsolidationPipeline
from .context_assembler import ContextAssembler
from .entity_classifier import classify_entity_type
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
