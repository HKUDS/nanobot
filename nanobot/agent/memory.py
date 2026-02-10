"""
Backward-compatible shim for the memory system.

The real implementation has moved to nanobot.memory package.
This module re-exports FileMemoryStore as MemoryStore for any
code that still imports from nanobot.agent.memory.
"""

from nanobot.memory.file_store import FileMemoryStore as MemoryStore

__all__ = ["MemoryStore"]
