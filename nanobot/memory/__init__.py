"""Memory subsystem — persistent memory with hybrid retrieval.

Organized into subdirectories by concern:

- **write/**        — Event extraction, ingestion, conflict detection
- **read/**         — Retrieval, query planning, context assembly
- **ranking/**      — Cross-encoder re-ranking (ONNX Runtime)
- **persistence/**  — Profile I/O, snapshot management
- **graph/**        — Knowledge graph, entity classification, ontology

Top-level modules:
- **store.py**      — MemoryStore facade (composes all subsystems)
- **unified_db.py** — SQLite + FTS5 + sqlite-vec storage backend
- **embedder.py**   — Embedding protocol and implementations
- **event.py**      — MemoryEvent Pydantic model
- **constants.py**  — Shared constants and tool schemas
- **helpers.py**    — Utility functions
- **rollout.py**    — Feature flag management
- **maintenance.py** — Reindex, seed, health checks
- **consolidation_pipeline.py** — Consolidation orchestration

Evaluation (moved to nanobot/eval/):
    memory_eval.py          EvalRunner — retrieval benchmarks + observability
"""

from __future__ import annotations

from .consolidation_pipeline import ConsolidationPipeline
from .embedder import Embedder, HashEmbedder, LocalEmbedder, OpenAIEmbedder
from .event import BeliefRecord, KnowledgeTriple, MemoryEvent
from .graph.entity_classifier import classify_entity_type
from .graph.graph import KnowledgeGraph
from .graph.ontology_rules import RELATION_RULES, TripleValidation, validate_triple_types
from .graph.ontology_types import (
    AGENT_NATIVE_TYPES,
    AGENT_RELATION_TYPES,
    Entity,
    EntityType,
    Relationship,
    RelationType,
    Triple,
)
from .maintenance import MemoryMaintenance
from .persistence.profile_io import ProfileStore
from .persistence.profile_io import ProfileStore as ProfileManager
from .persistence.snapshot import MemorySnapshot
from .ranking.onnx_reranker import OnnxCrossEncoderReranker
from .ranking.onnx_reranker import OnnxCrossEncoderReranker as CrossEncoderReranker
from .ranking.reranker import CompositeReranker, Reranker
from .read.context_assembler import ContextAssembler
from .read.retrieval_planner import RetrievalPlan, RetrievalPlanner
from .read.retriever import MemoryRetriever
from .rollout import RolloutConfig
from .store import MemoryStore
from .unified_db import UnifiedMemoryDB
from .write.conflicts import ConflictManager
from .write.extractor import MemoryExtractor
from .write.ingester import EventIngester

__all__ = [
    "AGENT_NATIVE_TYPES",
    "AGENT_RELATION_TYPES",
    "BeliefRecord",
    "CompositeReranker",
    "ConflictManager",
    "ConsolidationPipeline",
    "ContextAssembler",
    "CrossEncoderReranker",
    "Embedder",
    "Entity",
    "EntityType",
    "EventIngester",
    "HashEmbedder",
    "KnowledgeGraph",
    "KnowledgeTriple",
    "LocalEmbedder",
    "MemoryEvent",
    "MemoryExtractor",
    "MemoryMaintenance",
    "MemoryRetriever",
    "MemorySnapshot",
    "MemoryStore",
    "OnnxCrossEncoderReranker",
    "OpenAIEmbedder",
    "ProfileManager",
    "ProfileStore",
    "RELATION_RULES",
    "Reranker",
    "RelationType",
    "Relationship",
    "RetrievalPlan",
    "RetrievalPlanner",
    "RolloutConfig",
    "Triple",
    "TripleValidation",
    "UnifiedMemoryDB",
    "classify_entity_type",
    "validate_triple_types",
]
