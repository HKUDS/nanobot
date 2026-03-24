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
- **event.py**      — MemoryEvent Pydantic model + shared classifiers
- **constants.py**  — Shared constants and tool schemas
- **_text.py**      — Text normalization, timestamp, and coercion helpers
- **rollout.py**    — Feature flag management
- **maintenance.py** — Reindex, seed, health checks
- **consolidation_pipeline.py** — Consolidation orchestration

Internal types (graph, ranking, read, write, persistence) should be
imported from their owning subpackages, not from this top-level package.

Evaluation (moved to nanobot/eval/):
    memory_eval.py          EvalRunner — retrieval benchmarks + observability
"""

from __future__ import annotations

from .embedder import Embedder, HashEmbedder, LocalEmbedder, OpenAIEmbedder
from .event import MemoryEvent
from .store import MemoryStore
from .unified_db import UnifiedMemoryDB

__all__ = [
    "Embedder",
    "HashEmbedder",
    "LocalEmbedder",
    "MemoryEvent",
    "MemoryStore",
    "OpenAIEmbedder",
    "UnifiedMemoryDB",
]
