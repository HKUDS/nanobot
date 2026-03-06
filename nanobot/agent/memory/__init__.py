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
  ``metrics.json``.
- **mem0_adapter.py** — ``_Mem0Adapter``: wraps the mem0 SDK with health
  checks and automatic fallback.
- **reranker.py** — ``CrossEncoderReranker``: optional cross-encoder
  re-ranking stage (requires ``sentence-transformers``).
- **constants.py** — Shared constants and tool schemas.
"""

from .extractor import MemoryExtractor
from .mem0_adapter import _Mem0Adapter, _Mem0RuntimeInfo
from .persistence import MemoryPersistence
from .reranker import CrossEncoderReranker
from .store import MemoryStore

__all__ = [
    "MemoryStore",
    "MemoryExtractor",
    "MemoryPersistence",
    "CrossEncoderReranker",
    "_Mem0Adapter",
    "_Mem0RuntimeInfo",
]
