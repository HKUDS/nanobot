"""Optional PostgreSQL/pgvector-backed semantic recall for Nanobot.

The semantic store is a derived, fail-open supplement.  Dream and the workspace
memory files remain the durable source of truth.
"""

from nanobot.semantic_memory.models import MemoryRecord, SemanticHit
from nanobot.semantic_memory.service import SemanticMemoryService

__all__ = ["MemoryRecord", "SemanticHit", "SemanticMemoryService"]
