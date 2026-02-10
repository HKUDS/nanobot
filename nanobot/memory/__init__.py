"""
Long-term memory system for nanobot.

Provides vector-based memory using Mem0 + ChromaDB, with fallback
to the original file-based memory system.
"""

from nanobot.memory.base import BaseMemoryStore
from nanobot.memory.types import MemoryItem, MemorySearchResult
from nanobot.memory.file_store import FileMemoryStore

__all__ = [
    "BaseMemoryStore",
    "FileMemoryStore",
    "MemoryItem",
    "MemorySearchResult",
    "create_memory_store",
]


def create_memory_store(workspace, config=None):
    """
    Factory: create the appropriate memory store based on config and available deps.

    Args:
        workspace: Path to the workspace directory.
        config: Optional MemoryConfig. If None or backend="file", uses FileMemoryStore.

    Returns:
        A BaseMemoryStore instance.
    """
    from pathlib import Path

    workspace = Path(workspace)

    if config is None:
        return FileMemoryStore(workspace)

    backend = getattr(config, "backend", "file")

    if backend == "vector":
        try:
            from nanobot.memory.vector_store import VectorMemoryStore
            return VectorMemoryStore(workspace, config)
        except ImportError:
            from loguru import logger
            logger.warning(
                "chromadb or mem0ai not installed, falling back to file-based memory. "
                "Install with: pip install chromadb mem0ai"
            )
            return FileMemoryStore(workspace)

    return FileMemoryStore(workspace)
