"""Tests for targeted SQL dedup — verifies the new algorithm finds
duplicates and supersessions across the full event store."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.memory.event import MemoryEvent
from nanobot.memory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path, embedding_provider="hash")


class TestExactIdDedup:
    def test_duplicate_id_merges(self, store: MemoryStore) -> None:
        store.ingester.append_events([MemoryEvent(id="e1", summary="version 1", type="fact")])
        store.ingester.append_events(
            [MemoryEvent(id="e1", summary="version 1 updated", type="fact")]
        )
        events = store.ingester.read_events(limit=100)
        assert sum(1 for e in events if e["id"] == "e1") == 1

    def test_duplicate_id_beyond_100_events(self, store: MemoryStore) -> None:
        """Regression: old algorithm only checked latest 100 events."""
        for i in range(150):
            store.ingester.append_events(
                [
                    MemoryEvent(
                        id=f"seed-{i}",
                        summary=f"Seed event number {i}",
                        type="fact",
                        timestamp=f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00Z",
                    )
                ]
            )
        # Try to add duplicate of OLDEST event
        store.ingester.append_events(
            [MemoryEvent(id="seed-0", summary="Seed event number 0 updated", type="fact")]
        )
        all_events = store.ingester.read_events(limit=200)
        ids = [e["id"] for e in all_events]
        assert ids.count("seed-0") == 1


class TestSemanticDedup:
    def test_identical_summaries_merge(self, store: MemoryStore) -> None:
        store.ingester.append_events(
            [MemoryEvent(summary="User prefers dark roast coffee every morning", type="preference")]
        )
        store.ingester.append_events(
            [MemoryEvent(summary="User prefers dark roast coffee every morning", type="preference")]
        )
        events = store.ingester.read_events(limit=100)
        prefs = [e for e in events if e["type"] == "preference"]
        assert len(prefs) == 1  # merged via semantic dedup

    def test_different_types_not_merged(self, store: MemoryStore) -> None:
        store.ingester.append_events([MemoryEvent(summary="Deploy the application", type="task")])
        written = store.ingester.append_events(
            [MemoryEvent(summary="Deploy the application", type="fact")]
        )
        assert written == 1  # different type, not merged


class TestNewEventsPassThrough:
    def test_unrelated_events_both_stored(self, store: MemoryStore) -> None:
        store.ingester.append_events([MemoryEvent(summary="User likes coffee", type="preference")])
        written = store.ingester.append_events(
            [MemoryEvent(summary="Meeting scheduled for Friday", type="task")]
        )
        assert written == 1
        events = store.ingester.read_events(limit=100)
        assert len(events) == 2

    def test_empty_input_returns_zero(self, store: MemoryStore) -> None:
        assert store.ingester.append_events([]) == 0
