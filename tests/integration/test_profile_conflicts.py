"""IT-14: Profile updates with contradicting preferences.

Verifies that contradicting preference events are stored and that
the profile remains readable after updates. Does not require LLM API key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.config.memory import MemoryConfig
from nanobot.memory.store import MemoryStore

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(
        tmp_path,
        embedding_provider="hash",
        memory_config=MemoryConfig(graph_enabled=False),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProfileConflicts:
    def test_contradicting_preferences_stored(self, tmp_path: Path) -> None:
        """Both coffee and tea preferences are stored as events."""
        store = _make_store(tmp_path)

        store.ingester.append_events(
            [
                {
                    "type": "preference",
                    "summary": "User prefers coffee over tea.",
                    "timestamp": "2026-03-01T10:00:00+00:00",
                    "source": "test",
                },
                {
                    "type": "preference",
                    "summary": "User prefers tea over coffee.",
                    "timestamp": "2026-03-01T11:00:00+00:00",
                    "source": "test",
                },
            ]
        )

        events = store.ingester.read_events(limit=100)
        summaries = [e.get("summary", "").lower() for e in events]
        has_coffee = any("coffee" in s for s in summaries)
        has_tea = any("tea" in s for s in summaries)

        assert has_coffee, "Coffee preference event should be stored"
        assert has_tea, "Tea preference event should be stored"

    def test_profile_readable_after_preference_updates(self, tmp_path: Path) -> None:
        """Profile can be read without error after preference ingestion."""
        store = _make_store(tmp_path)

        store.ingester.append_events(
            [
                {
                    "type": "preference",
                    "summary": "User likes morning walks.",
                    "timestamp": "2026-03-01T08:00:00+00:00",
                    "source": "test",
                },
            ]
        )

        profile = store.profile_mgr.read_profile()
        assert isinstance(profile, dict), "read_profile should return a dict"

    def test_profile_readable_after_contradictions(self, tmp_path: Path) -> None:
        """Profile remains valid after storing contradicting preferences."""
        store = _make_store(tmp_path)

        store.ingester.append_events(
            [
                {
                    "type": "preference",
                    "summary": "User prefers VS Code for editing.",
                    "timestamp": "2026-03-01T09:00:00+00:00",
                    "source": "test",
                },
                {
                    "type": "preference",
                    "summary": "User prefers Neovim for editing.",
                    "timestamp": "2026-03-01T10:00:00+00:00",
                    "source": "test",
                },
            ]
        )

        profile = store.profile_mgr.read_profile()
        assert isinstance(profile, dict)
        # Profile should be structurally sound regardless of conflicts
        # (conflict resolution is a separate concern)

    def test_events_persist_across_store_instances(self, tmp_path: Path) -> None:
        """Events stored by one MemoryStore are visible to a new instance."""
        store1 = _make_store(tmp_path)
        store1.ingester.append_events(
            [
                {
                    "type": "preference",
                    "summary": "User prefers dark mode.",
                    "timestamp": "2026-03-01T12:00:00+00:00",
                    "source": "test",
                },
            ]
        )

        # New store instance pointing at the same workspace
        store2 = _make_store(tmp_path)
        events = store2.ingester.read_events(limit=100)
        summaries = " ".join(e.get("summary", "").lower() for e in events)
        assert "dark mode" in summaries, "Events should persist across store instances"
