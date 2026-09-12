"""Data transfer objects used by semantic memory adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryRecord:
    source_type: str
    source_key: str
    content: str
    content_hash: str
    embedding: list[float]
    source_timestamp: str | None = None
    session_key: str | None = None
    kind: str = "episodic"
    importance: float = 0.5
    confidence: float = 0.8
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticHit:
    source_type: str
    source_key: str
    content: str
    source_timestamp: str | None
    session_key: str | None
    kind: str
    score: float
    importance: float = 0.5
    confidence: float = 0.8
