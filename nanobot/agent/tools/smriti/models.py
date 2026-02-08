# nanobot/agent/tools/memory_box/models.py
"""
memory_box.models

IMPORTANT: do NOT name this file `types.py`.
If you ever run python with CWD inside this folder, `types.py` shadows stdlib
`types` and breaks imports (MappingProxyType error).

Conventions:
- All types are immutable (frozen=True).
- tags/people are stored as normalized whitespace-padded strings:
    " tag1 tag2 "
  so membership can be checked via substring:
    f" {tag} " in tags
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryValue:
    """One stored memory record (active or trash)."""
    id: str
    ts: str          # ISO-8601 timestamp (e.g. "2026-02-07T22:10:03-06:00")
    day: str         # YYYY-MM-DD
    time: str        # HH:MM:SS
    scope: str       # "daily" | "long"
    kind: str        # "fact" | "pref" | "decision" | "todo" | "note"
    text: str
    tags: str        # normalized: " tag1 tag2 "
    people: str      # normalized: " person1 person2 "
    source: str      # file path / origin


@dataclass(frozen=True)
class MemoryQuery:
    """Parameters for retrieving memories."""
    q: str = ""                         # free-text portion only
    kind: str | None = None
    scope: str | None = None            # "daily" | "long"
    tags_any: tuple[str, ...] = ()
    people_any: tuple[str, ...] = ()
    ids_any: tuple[str, ...] = ()       # exact id filter (^<10-hex>)
    limit: int = 8
    include_trash: bool = False


@dataclass(frozen=True)
class MemoryHit:
    """Ranked match returned by recall/search."""
    id: str
    day: str
    time: str
    kind: str
    scope: str
    snippet: str
    score: float
