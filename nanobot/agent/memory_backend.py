"""Minimal boundary for durable memory ingestion and explicit recall."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """One bounded, traceable memory match returned by a backend."""

    id: str
    source: str
    content: str
    timestamp: str | None = None
    session_key: str | None = None


@runtime_checkable
class MemoryBackend(Protocol):
    """Store durable memory material and retrieve it on explicit demand."""

    def ingest(
        self,
        content: str,
        *,
        session_key: str | None = None,
        max_chars: int | None = None,
    ) -> None:
        """Persist one bounded unit of memory material."""
        ...

    def recall(
        self,
        query: str,
        *,
        limit: int,
        session_key: str | None = None,
    ) -> list[MemoryRecord]:
        """Return records visible to ``session_key``; ``None`` is unscoped."""
        ...
