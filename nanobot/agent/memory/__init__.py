"""Memory system for persistent agent memory.

This package decomposes the monolithic memory module into focused sub-modules
while preserving backward-compatible imports::

    from nanobot.agent.memory import MemoryStore      # primary public API
    from nanobot.agent.memory import MemoryExtractor   # event extraction
    from nanobot.agent.memory import MemoryPersistence  # file I/O
    from nanobot.agent.memory import _Mem0Adapter      # internal, used by tests

Architecture
------------
- **store.py** — ``MemoryStore``: orchestrates retrieval, consolidation,
  and persistence.  Uses mem0 as primary vector store with local keyword
  fallback.
- **retrieval.py** — Local keyword-based scoring used when mem0 is
  unavailable or as a candidate generator for re-ranking.
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
from .context_assembler import ContextAssembler
from .eval import EvalRunner
from .event import BeliefRecord, KnowledgeTriple, MemoryEvent
from .extractor import MemoryExtractor
from .graph import KnowledgeGraph
from .ingester import EventIngester
from .mem0_adapter import _Mem0Adapter, _Mem0RuntimeInfo
from .onnx_reranker import OnnxCrossEncoderReranker
from .onnx_reranker import OnnxCrossEncoderReranker as CrossEncoderReranker  # backward-compat
from .ontology import (
    AGENT_NATIVE_TYPES,
    AGENT_RELATION_TYPES,
    RELATION_RULES,
    Entity,
    EntityType,
    Relationship,
    RelationType,
    Triple,
    TripleValidation,
    classify_entity_type,
    validate_triple_types,
)
from .persistence import MemoryPersistence
from .profile import ProfileManager
from .reranker import CompositeReranker, Reranker
from .retrieval_planner import RetrievalPlan, RetrievalPlanner
from .retriever import MemoryRetriever
from .rollout import RolloutConfig
from .store import MemoryStore

__all__ = [
    "BeliefRecord",
    "ConflictManager",
    "ContextAssembler",
    "EventIngester",
    "EvalRunner",
    "KnowledgeTriple",
    "MemoryEvent",
    "MemoryRetriever",
    "MemoryStore",
    "RetrievalPlan",
    "RetrievalPlanner",
    "RolloutConfig",
    "ProfileManager",
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
