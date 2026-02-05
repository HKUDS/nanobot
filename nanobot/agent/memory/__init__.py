"""Memory module for persistent and vector-based memory storage."""

# Import file-based memory store (manual notes)
from nanobot.agent.memory_store import (
    MemoryStore,
    MAX_CONTEXT_TOKENS,
    CHARS_PER_TOKEN,
    MAX_CONTEXT_CHARS,
    DEFAULT_MEMORY_DAYS,
)

# Import vector-based memory components
from nanobot.agent.memory.store import VectorMemoryStore, EmbeddingService, MemoryItem
from nanobot.agent.memory.extractor import MemoryExtractor, ExtractedFact, extract_facts_from_messages, FACT_KEYWORDS
from nanobot.agent.memory.consolidator import (
    MemoryConsolidator,
    ConsolidationResult,
    Operation,
)

__all__ = [
    # File-based memory (manual notes)
    "MemoryStore",
    "MAX_CONTEXT_TOKENS",
    "CHARS_PER_TOKEN",
    "MAX_CONTEXT_CHARS",
    "DEFAULT_MEMORY_DAYS",
    # Vector store
    "VectorMemoryStore",
    "EmbeddingService",
    "MemoryItem",
    # Extractor
    "MemoryExtractor",
    "ExtractedFact",
    "extract_facts_from_messages",
    "FACT_KEYWORDS",
    # Consolidator
    "MemoryConsolidator",
    "ConsolidationResult",
    "Operation",
]
