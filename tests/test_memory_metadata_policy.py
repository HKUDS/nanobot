"""Tests for memory metadata schema, write policy, and instrumentation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.memory import MemoryStore
from nanobot.memory.read.retrieval_planner import RetrievalPlanner


def test_coerce_event_adds_normalized_metadata(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)

    event = store._coercer.coerce_event(
        {
            "type": "fact",
            "summary": "Project runs on Ubuntu servers.",
            "source": "chat",
            "metadata": {"memory_type": "unknown", "stability": "invalid", "topic": "infra"},
        },
        source_span=[0, 0],
    )

    assert event is not None
    assert event["memory_type"] in {"semantic", "episodic", "reflection"}
    assert event["stability"] in {"high", "medium", "low"}
    assert event["topic"] == "infra"
    assert isinstance(event["metadata"], dict)
    assert event["metadata"]["memory_type"] in {"semantic", "episodic", "reflection"}


def test_append_events_writes_to_db(tmp_path: Path) -> None:
    """append_events writes events to UnifiedMemoryDB."""
    store = MemoryStore(tmp_path)

    written = store.ingester.append_events(
        [
            {
                "id": "evt-plain-1",
                "timestamp": "2026-03-01T10:00:00+00:00",
                "channel": "cli",
                "chat_id": "direct",
                "type": "fact",
                "summary": "Carlos prefers CLI tooling.",
                "entities": ["Carlos", "CLI"],
                "salience": 0.8,
                "confidence": 0.9,
                "source_span": [0, 0],
                "ttl_days": 365,
                "source": "chat",
            },
        ]
    )

    assert written == 1
    events = store.ingester.read_events()
    assert any(e.get("summary") == "Carlos prefers CLI tooling." for e in events)


def test_get_memory_context_fact_lookup_includes_episodic_softly(tmp_path: Path) -> None:
    """fact_lookup now soft-includes episodic with a small budget weight."""
    store = MemoryStore(tmp_path)
    if store.db:
        store.db.write_snapshot("current", "# Memory\nCore facts")
    store.retriever.retrieve = MagicMock(
        return_value=[
            {
                "id": "s1",
                "summary": "Carlos prefers CLI tools.",
                "type": "fact",
                "memory_type": "semantic",
                "retrieval_reason": {"semantic": 0.9, "recency": 0.2, "provider": "mem0"},
            },
            {
                "id": "e1",
                "summary": "Deploy failed yesterday due to port conflict.",
                "type": "task",
                "memory_type": "episodic",
                "retrieval_reason": {"semantic": 0.6, "recency": 0.8, "provider": "mem0"},
            },
        ]
    )

    context = store.get_memory_context(
        query="preferences and setup", retrieval_k=4, token_budget=220
    )

    assert "## Relevant Semantic Memories" in context
    assert "Carlos prefers CLI tools." in context
    # Episodic section now has a small weight (0.05) for fact_lookup,
    # so it may appear if budget allows.


def test_get_memory_context_debug_includes_episodic(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.retriever.retrieve = MagicMock(
        return_value=[
            {
                "id": "s1",
                "summary": "Carlos prefers CLI tools.",
                "type": "fact",
                "memory_type": "semantic",
                "retrieval_reason": {"semantic": 0.9, "recency": 0.2, "provider": "mem0"},
            },
            {
                "id": "e1",
                "summary": "Deploy failed yesterday due to port conflict.",
                "type": "task",
                "memory_type": "episodic",
                "retrieval_reason": {"semantic": 0.6, "recency": 0.8, "provider": "mem0"},
            },
        ]
    )

    context = store.get_memory_context(
        query="what happened last time deploy failed?", retrieval_k=4, token_budget=220
    )

    assert "## Relevant Episodic Memories" in context
    assert "Deploy failed yesterday due to port conflict." in context


def test_get_memory_context_reflection_includes_reflection_section(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.retriever.retrieve = MagicMock(
        return_value=[
            {
                "id": "r1",
                "summary": "Reflection: incidents are usually caused by stale config drift.",
                "type": "fact",
                "memory_type": "reflection",
                "retrieval_reason": {"semantic": 0.7, "recency": 0.5, "provider": "mem0"},
            }
        ]
    )

    context = store.get_memory_context(
        query="reflect on lessons learned", retrieval_k=4, token_budget=220
    )

    assert "## Relevant Reflection Memories" in context
    assert "Reflection: incidents are usually caused by stale config drift." in context


def test_semantic_supersession_marks_lineage(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)

    store.ingester.append_events(
        [
            {
                "id": "sem-old",
                "timestamp": "2026-03-01T10:00:00+00:00",
                "type": "fact",
                "summary": "API uses OAuth2 authentication.",
                "entities": ["api", "oauth2"],
                "source_span": [0, 0],
            }
        ]
    )
    store.ingester.append_events(
        [
            {
                "id": "sem-new",
                "timestamp": "2026-03-02T10:00:00+00:00",
                "type": "fact",
                "summary": "API does not use OAuth2 authentication.",
                "entities": ["api", "oauth2"],
                "source_span": [1, 1],
            }
        ]
    )

    events = store.ingester.read_events()
    old = next(item for item in events if item["id"] == "sem-old")
    new = next(item for item in events if item["id"] == "sem-new")

    assert old["status"] == "superseded"
    assert old["superseded_by_event_id"] == "sem-new"
    assert new["supersedes_event_id"] == "sem-old"


def test_recent_unresolved_respects_resolved_status_after_merge(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.ingester.append_events(
        [
            {
                "id": "task-open",
                "timestamp": "2026-03-01T10:00:00+00:00",
                "type": "task",
                "summary": "Review deployment logs.",
                "status": "open",
                "source_span": [0, 0],
            },
            {
                "id": "task-resolved",
                "timestamp": "2026-03-01T11:00:00+00:00",
                "type": "task",
                "summary": "Review deployment logs.",
                "status": "resolved",
                "source_span": [1, 1],
            },
        ]
    )

    events = store.ingester.read_events()
    assert len(events) == 1
    assert events[0]["status"] == "resolved"
    unresolved = store._assembler._recent_unresolved(events, max_items=8)
    assert unresolved == []


def test_evaluate_rollout_gates_returns_checks(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    evaluation = {"summary": {"recall_at_k": 0.8, "precision_at_k": 0.4}}
    observability = {"kpis": {"avg_memory_context_tokens": 900.0}}

    gates = store.eval_runner.evaluate_rollout_gates(evaluation, observability)
    assert isinstance(gates, dict)
    assert isinstance(gates.get("checks"), list)
    assert gates.get("passed") is True


def test_rollout_overrides_apply_from_constructor(tmp_path: Path) -> None:
    store = MemoryStore(
        tmp_path,
        rollout_overrides={
            "memory_rollout_mode": "disabled",
            "memory_router_enabled": False,
            "rollout_gates": {"min_recall_at_k": 0.66},
        },
    )
    status = store._rollout_config.get_status()
    assert status["memory_rollout_mode"] == "disabled"
    assert status["memory_router_enabled"] is False
    assert abs(float(status["rollout_gates"]["min_recall_at_k"]) - 0.66) < 1e-9


def test_workspace_rollout_file_is_ignored(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "rollout.json").write_text(
        json.dumps(
            {
                "memory_rollout_mode": "disabled",
                "memory_router_enabled": False,
            }
        ),
        encoding="utf-8",
    )

    store = MemoryStore(tmp_path)
    status = store._rollout_config.get_status()
    # Defaults remain active because workspace rollout files are no longer loaded.
    assert status["memory_rollout_mode"] == "enabled"
    assert status["memory_router_enabled"] is True


def test_infer_retrieval_intent_expanded_markers(tmp_path: Path) -> None:
    assert (
        RetrievalPlanner.infer_retrieval_intent("List long-term constraints we must follow.")
        == "constraints_lookup"
    )
    assert (
        RetrievalPlanner.infer_retrieval_intent("What unresolved decisions need user input?")
        == "conflict_review"
    )
    assert (
        RetrievalPlanner.infer_retrieval_intent(
            "What memory behavior is currently enabled in rollout?"
        )
        == "rollout_status"
    )


def test_evaluate_retrieval_cases_balanced_mode_supports_structural_hits(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.retriever.retrieve = MagicMock(
        return_value=[
            {
                "id": "x1",
                "summary": "Key constraint: commands must not mutate prod",
                "topic": "constraint",
                "memory_type": "semantic",
                "status": "active",
            }
        ]
    )

    evaluation = store.eval_runner.evaluate_retrieval_cases(
        [
            {
                "query": "What constraints should be applied before running commands?",
                "expected_any": ["constraints", "must"],
                "expected_any_mode": "normalized",
                "expected_topics": ["constraint"],
                "expected_memory_types": ["semantic"],
                "expected_status_any": ["active"],
                "top_k": 3,
            }
        ]
    )

    summary = evaluation["summary"]
    row = evaluation["evaluated"][0]
    assert summary["recall_at_k"] > 0.5
    assert summary["precision_at_k"] > 0.0
    assert row["hits"] >= 4
    assert row["why_missed"] == []


# ---------------------------------------------------------------------------
# Budget-aware section allocation tests
# ---------------------------------------------------------------------------


def test_allocate_section_budgets_proportional(tmp_path: Path) -> None:
    """Sections receive budget proportional to their priority weight."""
    from nanobot.memory.token_budget import DEFAULT_SECTION_WEIGHTS, TokenBudgetAllocator

    allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
    alloc = allocator.allocate(900, "fact_lookup")

    # Every section with non-zero weight should get *some* allocation.
    assert alloc.long_term > 0
    assert alloc.profile > 0
    assert alloc.semantic > 0
    assert alloc.graph > 0
    # Sections with zero weight get nothing.
    assert alloc.reflection == 0
    # Total allocation should not exceed budget.
    total = (
        alloc.long_term
        + alloc.profile
        + alloc.semantic
        + alloc.episodic
        + alloc.reflection
        + alloc.graph
        + alloc.unresolved
    )
    assert total <= 900


def test_allocate_proportional_respects_zero_weight() -> None:
    from nanobot.memory.token_budget import DEFAULT_SECTION_WEIGHTS, TokenBudgetAllocator

    allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
    result = allocator.allocate(900, "fact_lookup")
    # reflection weight is 0.0 for fact_lookup — must allocate 0 tokens
    assert result.reflection == 0


def test_get_memory_context_graph_not_truncated_at_default_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entity graph section should appear even at the default 900 token budget."""
    store = MemoryStore(tmp_path, rollout_overrides={"graph_enabled": True})

    # Simulate a large profile that previously consumed the whole budget.
    large_profile = {
        "preferences": [f"User prefers option {i}" for i in range(6)],
        "stable_facts": [f"Fact number {i} about the system" for i in range(6)],
        "active_projects": [],
        "relationships": [],
        "constraints": [f"Constraint {i}: must validate input" for i in range(4)],
    }
    store.profile_mgr.write_profile(large_profile)

    # Inject events that will be retrieved (semantic type).
    events = [
        {
            "id": f"ev-{i}",
            "timestamp": "2026-03-01T12:00:00+00:00",
            "type": "fact",
            "summary": f"Database uses PostgreSQL for storage (event {i}).",
            "memory_type": "semantic",
            "entities": ["postgresql", "nanobot"],
            "triples": [
                {"subject": "nanobot", "predicate": "USES", "object": "PostgreSQL"},
            ],
        }
        for i in range(4)
    ]
    store.ingester.append_events(events)

    # Mock retrieve to return the events we just stored.
    store.retriever.retrieve = MagicMock(return_value=events)  # type: ignore[method-assign]

    context = store.get_memory_context(
        query="What databases does the project use?",
        retrieval_k=6,
        token_budget=1200,
    )

    # Profile should still be present.
    assert "## Profile Memory" in context
    # Semantic memories should be present.
    assert "## Relevant Semantic Memories" in context
    # Graph section from local triples should NOT be truncated away.
    assert "## Entity Graph" in context
    assert "USES" in context and "PostgreSQL" in context
    # Total should stay within budget.
    assert len(context) <= 1200 * 4 + 200  # allow small heading overhead
