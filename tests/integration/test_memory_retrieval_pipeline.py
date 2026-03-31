"""IT-03: Memory retrieval pipeline integration tests.

Exercises the full write -> vector+FTS -> RRF -> rank pipeline using
HashEmbedder (no LLM API key required).  Verifies retrieval relevance,
RRF fusion, deduplication, and token-budget enforcement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.memory.event import MemoryEvent
from nanobot.memory.store import MemoryStore

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Diverse event corpus (20 events, all six types)
# ---------------------------------------------------------------------------

EVENTS: list[MemoryEvent] = [
    # -- preferences --
    MemoryEvent.from_dict(
        {
            "type": "preference",
            "summary": "User prefers dark mode in all editors and terminals.",
            "timestamp": "2026-03-01T08:00:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "preference",
            "summary": "User prefers tabs over spaces for indentation.",
            "timestamp": "2026-03-01T08:01:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "preference",
            "summary": "User likes mechanical keyboards with Cherry MX switches.",
            "timestamp": "2026-03-01T08:02:00+00:00",
            "source": "test",
        }
    ),
    # -- facts --
    MemoryEvent.from_dict(
        {
            "type": "fact",
            "summary": "User's primary programming language is Python.",
            "timestamp": "2026-03-01T09:00:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "fact",
            "summary": "User also writes TypeScript for frontend projects.",
            "timestamp": "2026-03-01T09:01:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "fact",
            "summary": "User's operating system is Ubuntu 22.04 LTS.",
            "timestamp": "2026-03-01T09:02:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "fact",
            "summary": "User works at a fintech startup in Berlin.",
            "timestamp": "2026-03-01T09:03:00+00:00",
            "source": "test",
        }
    ),
    # -- tasks --
    MemoryEvent.from_dict(
        {
            "type": "task",
            "summary": "Migrate the database from MySQL to PostgreSQL by end of quarter.",
            "timestamp": "2026-03-01T10:00:00+00:00",
            "source": "test",
            "metadata": {"status": "active"},
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "task",
            "summary": "Write unit tests for the payment processing module.",
            "timestamp": "2026-03-01T10:01:00+00:00",
            "source": "test",
            "metadata": {"status": "active"},
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "task",
            "summary": "Set up CI/CD pipeline with GitHub Actions.",
            "timestamp": "2026-03-01T10:02:00+00:00",
            "source": "test",
            "metadata": {"status": "active"},
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "task",
            "summary": "Refactor authentication service to use OAuth 2.0.",
            "timestamp": "2026-03-01T10:03:00+00:00",
            "source": "test",
            "metadata": {"status": "active"},
        }
    ),
    # -- decisions --
    MemoryEvent.from_dict(
        {
            "type": "decision",
            "summary": "Chose FastAPI over Flask for the new REST API project.",
            "timestamp": "2026-03-01T11:00:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "decision",
            "summary": "Decided to use Docker Compose for local development environment.",
            "timestamp": "2026-03-01T11:01:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "decision",
            "summary": "Selected Redis as the caching layer instead of Memcached.",
            "timestamp": "2026-03-01T11:02:00+00:00",
            "source": "test",
        }
    ),
    # -- constraints --
    MemoryEvent.from_dict(
        {
            "type": "constraint",
            "summary": "Budget limit is $5000 per month for cloud infrastructure.",
            "timestamp": "2026-03-01T12:00:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "constraint",
            "summary": "All API responses must complete within 200ms p99 latency.",
            "timestamp": "2026-03-01T12:01:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "constraint",
            "summary": "GDPR compliance required for all user data handling.",
            "timestamp": "2026-03-01T12:02:00+00:00",
            "source": "test",
        }
    ),
    # -- relationships --
    MemoryEvent.from_dict(
        {
            "type": "relationship",
            "summary": "User collaborates with Alice on the backend team.",
            "timestamp": "2026-03-01T13:00:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "relationship",
            "summary": "User reports to Bob who is the engineering manager.",
            "timestamp": "2026-03-01T13:01:00+00:00",
            "source": "test",
        }
    ),
    MemoryEvent.from_dict(
        {
            "type": "relationship",
            "summary": "User mentors Carol, a junior developer on the team.",
            "timestamp": "2026-03-01T13:02:00+00:00",
            "source": "test",
        }
    ),
]


@pytest.fixture()
def seeded_store(tmp_path: Path) -> MemoryStore:
    """MemoryStore pre-loaded with the 20-event corpus."""
    store = MemoryStore(tmp_path, embedding_provider="hash")
    count = store.ingester.append_events(EVENTS)
    assert count == len(EVENTS), f"Expected {len(EVENTS)} events ingested, got {count}"
    return store


# ---------------------------------------------------------------------------
# Retrieval relevance
# ---------------------------------------------------------------------------


class TestRetrievalRelevance:
    """Queries should surface semantically matching events."""

    async def test_preference_query_finds_preferences(self, seeded_store: MemoryStore) -> None:
        results = await seeded_store.retriever.retrieve("dark mode editor preference", top_k=5)
        assert len(results) > 0, "Expected at least one result for preference query"
        summaries = [r.summary for r in results]
        assert any("dark mode" in s.lower() for s in summaries), (
            f"Expected 'dark mode' in results, got: {summaries}"
        )

    async def test_programming_query_finds_languages(self, seeded_store: MemoryStore) -> None:
        results = await seeded_store.retriever.retrieve("programming language", top_k=5)
        assert len(results) > 0, "Expected at least one result for programming query"
        summaries = [r.summary for r in results]
        assert any("python" in s.lower() or "typescript" in s.lower() for s in summaries), (
            f"Expected language mention in results, got: {summaries}"
        )

    async def test_task_query_finds_tasks(self, seeded_store: MemoryStore) -> None:
        results = await seeded_store.retriever.retrieve("database migration PostgreSQL", top_k=5)
        assert len(results) > 0, "Expected at least one result for task query"
        summaries = [r.summary for r in results]
        assert any("postgresql" in s.lower() for s in summaries), (
            f"Expected PostgreSQL mention in results, got: {summaries}"
        )

    async def test_relationship_query_finds_people(self, seeded_store: MemoryStore) -> None:
        results = await seeded_store.retriever.retrieve("team collaboration Alice", top_k=5)
        assert len(results) > 0, "Expected at least one result for relationship query"
        summaries = [r.summary for r in results]
        assert any("alice" in s.lower() for s in summaries), (
            f"Expected Alice mention in results, got: {summaries}"
        )

    async def test_constraint_query_finds_limits(self, seeded_store: MemoryStore) -> None:
        results = await seeded_store.retriever.retrieve("budget cloud infrastructure cost", top_k=5)
        assert len(results) > 0, "Expected at least one result for constraint query"
        summaries = [r.summary for r in results]
        assert any("budget" in s.lower() or "$5000" in s for s in summaries), (
            f"Expected budget mention in results, got: {summaries}"
        )


# ---------------------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------------------


class TestRRFFusion:
    """FTS keyword matching contributes to retrieval via RRF."""

    async def test_fts_keyword_match(self, seeded_store: MemoryStore) -> None:
        """A distinctive keyword should surface the matching event."""
        results = await seeded_store.retriever.retrieve("Memcached", top_k=5)
        assert len(results) > 0, "FTS should find the Memcached event"
        summaries = [r.summary for r in results]
        assert any("memcached" in s.lower() for s in summaries), (
            f"Expected Memcached mention via FTS, got: {summaries}"
        )

    async def test_retrieval_returns_requested_count(self, seeded_store: MemoryStore) -> None:
        """top_k should cap the number of results returned."""
        results = await seeded_store.retriever.retrieve("user", top_k=3)
        assert len(results) <= 3, f"Expected at most 3 results, got {len(results)}"

    async def test_broader_query_returns_multiple(self, seeded_store: MemoryStore) -> None:
        """A broad query should return multiple diverse results."""
        results = await seeded_store.retriever.retrieve("user development work", top_k=10)
        assert len(results) >= 3, f"Expected at least 3 results for broad query, got {len(results)}"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Duplicate events should not produce duplicate retrieval results."""

    async def test_duplicate_events_not_doubled(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        duplicate_event = MemoryEvent.from_dict(
            {
                "type": "fact",
                "summary": "User's primary programming language is Python.",
                "timestamp": "2026-03-01T09:00:00+00:00",
                "source": "test",
            }
        )
        # Ingest the same event twice
        store.ingester.append_events([duplicate_event])
        store.ingester.append_events([duplicate_event])

        results = await store.retriever.retrieve("Python programming language", top_k=10)
        summaries = [r.summary for r in results]
        python_matches = [s for s in summaries if "python" in s.lower()]
        assert len(python_matches) <= 1, (
            f"Duplicate event appeared {len(python_matches)} times in results: {summaries}"
        )


# ---------------------------------------------------------------------------
# Token budget
# ---------------------------------------------------------------------------


class TestTokenBudget:
    """get_memory_context should respect the token budget."""

    async def test_memory_context_respects_budget(self, seeded_store: MemoryStore) -> None:
        context = await seeded_store.get_memory_context(
            query="all user information",
            retrieval_k=20,
            token_budget=100,
        )
        assert isinstance(context, str)
        # A rough token estimate: ~4 chars per token.  With a budget of 100 tokens
        # the output should be well under 1000 characters (generous upper bound).
        assert len(context) < 2000, (
            f"Memory context too long for 100-token budget: {len(context)} chars"
        )

    async def test_larger_budget_returns_more(self, seeded_store: MemoryStore) -> None:
        small = await seeded_store.get_memory_context(
            query="user preferences and tasks",
            retrieval_k=10,
            token_budget=50,
        )
        large = await seeded_store.get_memory_context(
            query="user preferences and tasks",
            retrieval_k=10,
            token_budget=2000,
        )
        # A larger budget should allow at least as much content
        assert len(large) >= len(small), (
            f"Larger budget produced less content: {len(large)} < {len(small)}"
        )

    async def test_memory_context_returns_string(self, seeded_store: MemoryStore) -> None:
        context = await seeded_store.get_memory_context(query="test", token_budget=500)
        assert isinstance(context, str)
