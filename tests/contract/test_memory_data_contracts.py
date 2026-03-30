"""Cross-component data contract tests for the memory subsystem.

These tests verify that data written by one component can be read by another.
They protect against schema drift during refactoring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.memory.constants import EVENT_TYPES, MEMORY_TYPES, PROFILE_KEYS
from nanobot.memory.event import MemoryEvent
from nanobot.memory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    """Create a MemoryStore with HashEmbedder for deterministic tests."""
    return MemoryStore(tmp_path, embedding_provider="hash")


class TestWriteReadEventContract:
    """Events written by ingester are retrievable by retriever."""

    def test_ingested_event_has_required_fields(self, store: MemoryStore) -> None:
        """Every event persisted by ingester contains the fields retriever expects."""
        event = MemoryEvent(
            id="test-001",
            timestamp="2026-03-30T00:00:00Z",
            type="fact",
            summary="Python is a programming language",
            memory_type="semantic",
            stability="high",
            confidence=0.9,
            entities=["Python"],
        )
        store.ingester.append_events([event.to_dict()])

        rows = store.ingester.read_events(limit=10)
        assert len(rows) >= 1
        row = next(r for r in rows if r["id"] == "test-001")

        # Fields the retriever and scorer depend on:
        assert "id" in row
        assert "type" in row
        assert "summary" in row
        assert "timestamp" in row
        assert "status" in row

    def test_event_type_values_match_constants(self, store: MemoryStore) -> None:
        """All event types written by ingester are in EVENT_TYPES."""
        for event_type in EVENT_TYPES:
            event = MemoryEvent(
                id=f"type-{event_type}",
                timestamp="2026-03-30T00:00:00Z",
                type=event_type,  # type: ignore[arg-type]
                summary=f"Test event of type {event_type}",
            )
            store.ingester.append_events([event.to_dict()])

        rows = store.ingester.read_events(limit=100)
        for row in rows:
            if row["id"].startswith("type-"):
                assert row["type"] in EVENT_TYPES


class TestProfileContract:
    """Profile data written by profile_mgr is readable and well-structured."""

    def test_profile_keys_match_constants(self, store: MemoryStore) -> None:
        """Profile sections match PROFILE_KEYS."""
        profile = store.profile_mgr.read_profile()
        for key in PROFILE_KEYS:
            assert key in profile, f"Profile missing section: {key}"


class TestMemoryTypeContract:
    """Memory types flow consistently from write to read path."""

    def test_all_memory_types_are_valid(self) -> None:
        """MemoryEvent accepts all MEMORY_TYPES values."""
        for mt in MEMORY_TYPES:
            event = MemoryEvent(
                summary="test",
                memory_type=mt,  # type: ignore[arg-type]
            )
            assert event.memory_type == mt
