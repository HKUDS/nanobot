"""Contract tests for the MemoryStore public interface.

These tests verify that:
1. ``MemoryStore`` can be instantiated with a workspace path.
2. Core operations (append, retrieve, profile read/write) work correctly.
3. Roundtrip consistency: written data can be retrieved.
4. Behavioral invariants: ordering, dedup, negative queries, salience, context assembly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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

    def test_has_db(self, tmp_path: Path):
        store = _make_store(tmp_path)
        assert store.db is not None

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

    def test_events_persist_to_db(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.ingester.append_events(_sample_events())
        events = store.ingester.read_events(limit=100)
        assert len(events) >= 1
        assert any("dark mode" in str(e.get("summary", "")) for e in events)


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


# ---------------------------------------------------------------------------
# Contract: Behavioral invariants
# ---------------------------------------------------------------------------


def _index_of(results: list[dict[str, Any]], needle: str) -> int | None:
    """Return the index of the first result whose summary contains *needle* (case-insensitive)."""
    needle_lower = needle.lower()
    for i, r in enumerate(results):
        if needle_lower in r.get("summary", "").lower():
            return i
    return None


class TestBehavioralInvariants:
    """Invariant-based tests that remain stable across scoring refactors.

    These verify *relative* ordering, presence/absence, and deduplication —
    never exact scores or absolute positions.
    """

    def test_supersession_ordering(self, tmp_path: Path):
        """Active events must rank above superseded events on the same topic."""
        store = _make_store(tmp_path)
        store.ingester.append_events(
            [
                {
                    "id": "evt-old-coffee",
                    "type": "preference",
                    "summary": "User prefers drip coffee every morning.",
                    "timestamp": "2026-01-01T08:00:00+00:00",
                    "source": "test",
                    "status": "superseded",
                },
                {
                    "id": "evt-new-coffee",
                    "type": "preference",
                    "summary": "User prefers espresso coffee every morning.",
                    "timestamp": "2026-03-01T08:00:00+00:00",
                    "source": "test",
                    "status": "active",
                },
            ]
        )
        results = store.retriever.retrieve("coffee preference morning", top_k=10)
        idx_active = _index_of(results, "espresso")
        idx_superseded = _index_of(results, "drip")
        if idx_active is not None and idx_superseded is not None:
            assert idx_active < idx_superseded, (
                f"Active event (pos {idx_active}) must rank above "
                f"superseded event (pos {idx_superseded})"
            )

    def test_recency_ordering(self, tmp_path: Path):
        """Newer events must rank above older events on the same topic."""
        store = _make_store(tmp_path)
        store.ingester.append_events(
            [
                {
                    "id": "evt-old-project",
                    "type": "task",
                    "summary": "User is working on the Falcon project redesign.",
                    "timestamp": "2026-01-01T10:00:00+00:00",
                    "source": "test",
                },
                {
                    "id": "evt-new-project",
                    "type": "task",
                    "summary": "User is working on the Falcon project deployment.",
                    "timestamp": "2026-01-08T10:00:00+00:00",
                    "source": "test",
                },
            ]
        )
        results = store.retriever.retrieve("Falcon project", top_k=10)
        idx_new = _index_of(results, "deployment")
        idx_old = _index_of(results, "redesign")
        if idx_new is not None and idx_old is not None:
            assert idx_new < idx_old, (
                f"Newer event (pos {idx_new}) must rank above older event (pos {idx_old})"
            )

    def test_negative_query_no_false_matches(self, tmp_path: Path):
        """Querying for an unrelated topic must not return false positives."""
        store = _make_store(tmp_path)
        store.ingester.append_events(
            [
                {
                    "id": "evt-work-1",
                    "type": "fact",
                    "summary": "User works as a backend engineer at Acme Corp.",
                    "timestamp": "2026-03-01T12:00:00+00:00",
                    "source": "test",
                },
                {
                    "id": "evt-work-2",
                    "type": "task",
                    "summary": "User is migrating the database to PostgreSQL.",
                    "timestamp": "2026-03-01T12:05:00+00:00",
                    "source": "test",
                },
            ]
        )
        results = store.retriever.retrieve("favorite color blue", top_k=5)
        for r in results:
            summary = r.get("summary", "").lower()
            assert "color" not in summary and "blue" not in summary, (
                f"False match: '{summary}' should not appear for query 'favorite color blue'"
            )

    def test_high_salience_surfaces_in_top_3(self, tmp_path: Path):
        """A high-salience event must appear in the top 3 results."""
        store = _make_store(tmp_path)
        filler_events = [
            {
                "id": f"evt-filler-{i}",
                "type": "fact",
                "summary": f"Generic filler observation number {i} about routine tasks.",
                "timestamp": f"2026-02-{10 + i:02d}T12:00:00+00:00",
                "source": "test",
                "salience": 0.2,
            }
            for i in range(10)
        ]
        high_salience_event = {
            "id": "evt-critical",
            "type": "decision",
            "summary": "User decided to adopt Kubernetes for all production deployments.",
            "timestamp": "2026-03-01T12:00:00+00:00",
            "source": "test",
            "salience": 0.95,
        }
        store.ingester.append_events(filler_events + [high_salience_event])
        results = store.retriever.retrieve("Kubernetes production deployment", top_k=5)
        idx = _index_of(results, "kubernetes")
        assert idx is not None and idx < 3, (
            f"High-salience event should appear in top 3, got position {idx}. "
            f"Results: {[r.get('summary', '')[:60] for r in results]}"
        )

    def test_dedup_idempotency(self, tmp_path: Path):
        """Appending the same event twice must not produce duplicates."""
        store = _make_store(tmp_path)
        event = {
            "id": "evt-dedup-1",
            "type": "fact",
            "summary": "User has a golden retriever named Max.",
            "timestamp": "2026-03-01T12:00:00+00:00",
            "source": "test",
        }
        store.ingester.append_events([event])
        store.ingester.append_events([event])
        all_events = store.ingester.read_events()
        matching = [e for e in all_events if e.get("id") == "evt-dedup-1"]
        assert len(matching) == 1, (
            f"Expected exactly 1 event with id 'evt-dedup-1', got {len(matching)}"
        )

    def test_type_appropriate_retrieval(self, tmp_path: Path):
        """Intent-based type boosts should affect ranking.

        For a debug/history query (``"what happened"`` trigger), the retrieval
        planner classifies the intent as ``debug_history`` which boosts episodic
        events (+0.22) and penalises semantic events (-0.04).  Given two events
        with comparable BM25 base scores on the same topic, the episodic one
        must rank at or above the semantic one.
        """
        store = _make_store(tmp_path)
        store.ingester.append_events(
            [
                {
                    "id": "evt-semantic-deploy",
                    "type": "fact",
                    "summary": "The deploy pipeline runs nightly on staging.",
                    "timestamp": "2026-03-01T12:00:00+00:00",
                    "source": "test",
                    "memory_type": "semantic",
                },
                {
                    "id": "evt-episodic-deploy",
                    "type": "task",
                    "summary": "The deploy to staging failed last night with timeout.",
                    "timestamp": "2026-03-01T12:05:00+00:00",
                    "source": "test",
                    "memory_type": "episodic",
                },
            ]
        )
        # "what happened" triggers debug_history intent → episodic type boost.
        results = store.retriever.retrieve("what happened with the deploy to staging", top_k=10)
        idx_episodic = _index_of(results, "failed last night")
        idx_semantic = _index_of(results, "runs nightly")
        assert idx_episodic is not None or idx_semantic is not None, (
            "At least one deploy event must appear in results"
        )
        if idx_episodic is not None and idx_semantic is not None:
            assert idx_episodic <= idx_semantic, (
                f"Episodic event (pos {idx_episodic}) must rank at or above "
                f"semantic event (pos {idx_semantic}) for debug_history query"
            )

    def test_context_assembly_completeness(self, tmp_path: Path):
        """get_memory_context must return non-empty context including profile data."""
        store = _make_store(tmp_path)
        profile: dict[str, Any] = {
            "preferences": ["Prefers dark mode"],
            "stable_facts": ["Works at Acme Corp"],
            "active_projects": [],
            "meta": {
                "preferences": {
                    "prefers dark mode": {
                        "status": "active",
                        "last_seen_at": "2026-03-01T12:00:00+00:00",
                        "confidence": 0.9,
                    },
                },
                "stable_facts": {
                    "works at acme corp": {
                        "status": "active",
                        "last_seen_at": "2026-03-01T12:00:00+00:00",
                        "confidence": 0.9,
                    },
                },
            },
        }
        store.profile_mgr.write_profile(profile)
        store.ingester.append_events(
            [
                {
                    "id": "evt-ctx-1",
                    "type": "fact",
                    "summary": "User started learning Rust last week.",
                    "timestamp": "2026-03-01T12:00:00+00:00",
                    "source": "test",
                }
            ]
        )
        context = store.get_memory_context(query="dark mode preference", token_budget=2000)
        assert context, "get_memory_context must return non-empty context"
        assert "dark mode" in context.lower(), (
            f"Profile preference 'dark mode' missing from context:\n{context[:500]}"
        )

    def test_pinned_item_always_included(self, tmp_path: Path):
        """A pinned preference must appear in context even for unrelated queries."""
        store = _make_store(tmp_path)
        profile: dict[str, Any] = {
            "preferences": ["Always use vim keybindings"],
            "stable_facts": [],
            "active_projects": [],
            "meta": {
                "preferences": {
                    "always use vim keybindings": {
                        "pinned": True,
                        "status": "active",
                        "last_seen_at": "2026-03-01T12:00:00+00:00",
                        "confidence": 0.95,
                    },
                },
            },
        }
        store.profile_mgr.write_profile(profile)
        context = store.get_memory_context(query="weather forecast tomorrow", token_budget=2000)
        assert "vim keybindings" in context.lower(), (
            f"Pinned preference 'vim keybindings' missing from context:\n{context[:500]}"
        )
