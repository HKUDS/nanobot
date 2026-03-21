"""Contract tests for the MemoryStore public interface.

These tests verify that:
1. ``MemoryStore`` can be instantiated with a workspace path.
2. Core operations (append, retrieve, profile read/write) work correctly.
3. Roundtrip consistency: written data can be retrieved.
"""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.memory import MemoryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> MemoryStore:
    """Create a MemoryStore with deterministic (non-ML) settings."""
    return MemoryStore(tmp_path, embedding_provider="hash")


def _sample_events() -> list[dict]:
    """Return a minimal set of events for testing."""
    return [
        {
            "id": "evt-001",
            "type": "preference",
            "summary": "User prefers dark mode in all editors.",
            "timestamp": "2026-03-01T12:00:00+00:00",
            "source": "test",
        },
        {
            "id": "evt-002",
            "type": "fact",
            "summary": "User's primary language is Python.",
            "timestamp": "2026-03-01T12:01:00+00:00",
            "source": "test",
        },
    ]


# ---------------------------------------------------------------------------
# Contract: Instantiation
# ---------------------------------------------------------------------------


class TestMemoryStoreInstantiation:
    """MemoryStore must initialise cleanly with a workspace path."""

    def test_creates_memory_directory(self, tmp_path: Path):
        store = _make_store(tmp_path)
        assert store.memory_dir.exists()
        assert store.memory_dir.is_dir()

    def test_has_persistence(self, tmp_path: Path):
        store = _make_store(tmp_path)
        assert store.persistence is not None

    def test_has_extractor(self, tmp_path: Path):
        store = _make_store(tmp_path)
        assert store.extractor is not None


# ---------------------------------------------------------------------------
# Contract: append_events
# ---------------------------------------------------------------------------


class TestAppendEventsContract:
    """append_events must accept a list of event dicts and return count written."""

    def test_append_returns_count(self, tmp_path: Path):
        store = _make_store(tmp_path)
        count = store.ingester.append_events(_sample_events())
        assert isinstance(count, int)
        assert count >= 1

    def test_append_empty_list(self, tmp_path: Path):
        store = _make_store(tmp_path)
        count = store.ingester.append_events([])
        assert count == 0

    def test_events_persist_to_disk(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.ingester.append_events(_sample_events())
        assert store.events_file.exists()
        content = store.events_file.read_text(encoding="utf-8")
        assert "dark mode" in content


# ---------------------------------------------------------------------------
# Contract: retrieve
# ---------------------------------------------------------------------------


class TestRetrieveContract:
    """retrieve must accept a query string and return a list of result dicts."""

    def test_returns_list(self, tmp_path: Path):
        store = _make_store(tmp_path)
        results = store.retriever.retrieve("anything", top_k=5)
        assert isinstance(results, list)

    def test_retrieves_stored_events(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.ingester.append_events(_sample_events())
        results = store.retriever.retrieve("dark mode", top_k=5)
        assert isinstance(results, list)
        summaries = [r.get("summary", "").lower() for r in results]
        assert any("dark mode" in s for s in summaries), (
            f"Expected 'dark mode' in retrieved results: {summaries}"
        )

    def test_top_k_limits_results(self, tmp_path: Path):
        store = _make_store(tmp_path)
        # Append many events
        events = [
            {
                "id": f"evt-{i:03d}",
                "type": "fact",
                "summary": f"Fact number {i} about testing.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            }
            for i in range(20)
        ]
        store.ingester.append_events(events)
        results = store.retriever.retrieve("fact testing", top_k=3)
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# Contract: Profile read/write roundtrip
# ---------------------------------------------------------------------------


class TestProfileContract:
    """read_profile / write_profile must roundtrip consistently."""

    def test_read_profile_returns_dict(self, tmp_path: Path):
        store = _make_store(tmp_path)
        profile = store.profile_mgr.read_profile()
        assert isinstance(profile, dict)

    def test_write_then_read_profile(self, tmp_path: Path):
        store = _make_store(tmp_path)
        # Write a minimal valid profile matching the expected schema
        profile = {
            "preferences": [
                {
                    "text": "dark mode",
                    "status": "active",
                    "last_updated": "2026-03-01T12:00:00+00:00",
                }
            ],
            "stable_facts": [],
            "active_projects": [],
        }
        store.profile_mgr.write_profile(profile)

        # Re-read and verify
        reloaded = store.profile_mgr.read_profile()
        assert "preferences" in reloaded
        assert isinstance(reloaded["preferences"], list)
        assert len(reloaded["preferences"]) >= 1
        assert reloaded["preferences"][0]["text"] == "dark mode"


# ---------------------------------------------------------------------------
# Contract: Roundtrip consistency
# ---------------------------------------------------------------------------


class TestRoundtripConsistency:
    """Data written through append_events must be retrievable via retrieve."""

    def test_preference_roundtrip(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.ingester.append_events(
            [
                {
                    "id": "evt-pref-1",
                    "type": "preference",
                    "summary": "User always wants TypeScript over JavaScript.",
                    "timestamp": "2026-03-01T12:00:00+00:00",
                    "source": "test",
                }
            ]
        )
        results = store.retriever.retrieve("TypeScript preference", top_k=5)
        summaries = " ".join(r.get("summary", "") for r in results).lower()
        assert "typescript" in summaries

    def test_fact_roundtrip(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.ingester.append_events(
            [
                {
                    "id": "evt-fact-1",
                    "type": "fact",
                    "summary": "User works at Acme Corp since 2024.",
                    "timestamp": "2026-03-01T12:00:00+00:00",
                    "source": "test",
                }
            ]
        )
        results = store.retriever.retrieve("where does user work", top_k=5)
        summaries = " ".join(r.get("summary", "") for r in results).lower()
        assert "acme" in summaries
