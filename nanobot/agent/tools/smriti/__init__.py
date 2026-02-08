# /memory_box/__init__.py
"""
memory_box

Minimal, durable, queryable memory for Nanobot.

- Canonical append-only Markdown files:
    workspace/memory/YYYY-MM-DD.md
    workspace/memory/MEMORY.md
    workspace/memory/.trash/YYYY-MM-DD.md
- SQLite index + optional FTS5 for fast recall
- Soft delete / restore
- Promote daily -> long-term
- Tag/people extraction: #tags, @people
"""

from .models import MemoryValue, MemoryQuery, MemoryHit
from .store import MemoryStore

__all__ = ["MemoryValue", "MemoryQuery", "MemoryHit", "MemoryStore"]
