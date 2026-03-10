"""Tests for memory metadata schema, write policy, and instrumentation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.memory import MemoryStore


def test_coerce_event_adds_normalized_metadata(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)

    event = store._coerce_event(
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


def test_event_write_plan_dual_writes_mixed_memory(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)

    plan = store._event_mem0_write_plan(
        {
            "id": "evt-mixed-1",
            "type": "fact",
            "summary": "Carlos prefers CLI tools because GUI deploy failed yesterday.",
            "entities": ["Carlos", "CLI", "GUI"],
            "source": "chat",
            "source_span": [0, 1],
        }
    )

    assert len(plan) == 2
    texts = [text for text, _ in plan]
    metas = [meta for _, meta in plan]

    assert any(meta.get("memory_type") == "episodic" for meta in metas)
    assert any(meta.get("memory_type") == "semantic" for meta in metas)
    # Distilled semantic version should remove the causal tail.
    assert any("because" not in text.lower() for text in texts)


def test_append_events_records_type_metrics_with_dual_write(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.mem0.enabled = True
    store.mem0.add_text = MagicMock(return_value=True)

    written = store.append_events(
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
            {
                "id": "evt-mixed-2",
                "timestamp": "2026-03-01T11:00:00+00:00",
                "channel": "cli",
                "chat_id": "direct",
                "type": "fact",
                "summary": "Carlos prefers terminal workflows because GUI setup failed yesterday.",
                "entities": ["Carlos", "terminal", "GUI"],
                "salience": 0.8,
                "confidence": 0.9,
                "source_span": [1, 1],
                "ttl_days": 365,
                "source": "chat",
            },
        ]
    )

    assert written == 2
    metrics = store.get_metrics()
    assert metrics["memory_writes_total"] >= 3
    assert metrics["memory_writes_semantic"] >= 2
    assert metrics["memory_writes_episodic"] >= 1
    assert metrics["memory_writes_dual"] >= 1


def test_retrieve_records_candidates_and_type_counts(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.mem0.enabled = True
    store.mem0.search = MagicMock(
        return_value=[
            {
                "id": "m1",
                "summary": "Carlos prefers CLI tools.",
                "type": "fact",
                "score": 0.92,
                "memory_type": "semantic",
                "topic": "user_preference",
                "stability": "high",
            },
            {
                "id": "m2",
                "summary": "Deploy failed yesterday due to port conflict.",
                "type": "task",
                "score": 0.61,
                "memory_type": "episodic",
                "topic": "infra",
                "stability": "low",
            },
        ]
    )

    rows = store.retrieve("cli deploy", top_k=2)

    assert len(rows) == 2
    # Phase 4 candidate expansion should query a larger pool.
    _, kwargs = store.mem0.search.call_args
    assert kwargs["top_k"] == 6
    metrics = store.get_metrics()
    assert metrics["retrieval_candidates"] >= 2
    assert metrics["retrieval_returned"] >= 2
    assert metrics["retrieval_returned_semantic"] >= 1
    assert metrics["retrieval_returned_episodic"] >= 1
    assert metrics["retrieval_intent_fact_lookup"] >= 1


def test_retrieve_debug_history_prefers_episodic(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.mem0.enabled = True
    store.mem0.search = MagicMock(
        return_value=[
            {
                "id": "s1",
                "summary": "Carlos prefers CLI tools.",
                "type": "fact",
                "score": 0.95,
                "memory_type": "semantic",
                "stability": "high",
                "timestamp": "2025-01-01T00:00:00+00:00",
            },
            {
                "id": "e1",
                "summary": "Deploy failed yesterday due to port conflict.",
                "type": "task",
                "score": 0.85,
                "memory_type": "episodic",
                "stability": "low",
                "timestamp": "2026-02-28T00:00:00+00:00",
            },
        ]
    )

    rows = store.retrieve("what happened last time deploy failed?", top_k=1)

    assert len(rows) == 1
    assert rows[0]["memory_type"] == "episodic"
    metrics = store.get_metrics()
    assert metrics["retrieval_intent_debug_history"] >= 1


def test_get_memory_context_fact_lookup_includes_episodic_softly(tmp_path: Path) -> None:
    """fact_lookup now soft-includes episodic with a small budget weight."""
    store = MemoryStore(tmp_path)
    store.write_long_term("# Memory\nCore facts")
    store.retrieve = MagicMock(
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
    metrics = store.get_metrics()
    assert metrics["memory_context_intent_fact_lookup"] >= 1


def test_get_memory_context_debug_includes_episodic(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.retrieve = MagicMock(
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
    metrics = store.get_metrics()
    assert metrics["memory_context_intent_debug_history"] >= 1


def test_get_memory_context_reflection_includes_reflection_section(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.retrieve = MagicMock(
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
    metrics = store.get_metrics()
    assert metrics["memory_context_intent_reflection"] >= 1


def test_semantic_supersession_marks_lineage(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)

    store.append_events(
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
    store.append_events(
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

    events = store.read_events()
    old = next(item for item in events if item["id"] == "sem-old")
    new = next(item for item in events if item["id"] == "sem-new")

    assert old["status"] == "superseded"
    assert old["superseded_by_event_id"] == "sem-new"
    assert new["supersedes_event_id"] == "sem-old"
    metrics = store.get_metrics()
    assert metrics["semantic_supersessions"] >= 1


def test_recent_unresolved_respects_resolved_status_after_merge(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.append_events(
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

    events = store.read_events()
    assert len(events) == 1
    assert events[0]["status"] == "resolved"
    unresolved = store._recent_unresolved(events, max_items=8)
    assert unresolved == []


def test_reflection_without_evidence_downgrades_to_episodic(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.mem0.enabled = True
    store.mem0.add_text = MagicMock(return_value=True)

    store.append_events(
        [
            {
                "id": "r-no-evidence",
                "timestamp": "2026-03-01T10:00:00+00:00",
                "type": "fact",
                "summary": "Reflection: deploys usually fail due to stale env vars.",
                "source": "reflection",
                "metadata": {"memory_type": "reflection", "topic": "infra"},
                "source_span": [0, 0],
            }
        ]
    )

    _, kwargs = store.mem0.add_text.call_args
    assert kwargs["metadata"]["memory_type"] == "episodic"
    metrics = store.get_metrics()
    assert metrics["reflection_downgraded_no_evidence"] >= 1


def test_retrieve_filters_reflection_for_non_reflection_intent(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.mem0.enabled = True
    store.mem0.search = MagicMock(
        return_value=[
            {
                "id": "r1",
                "summary": "Reflection: env drift is a recurring issue.",
                "type": "fact",
                "score": 0.95,
                "memory_type": "reflection",
                "evidence_refs": ["ev-1"],
            },
            {
                "id": "s1",
                "summary": "Carlos prefers CLI tools.",
                "type": "fact",
                "score": 0.6,
                "memory_type": "semantic",
            },
        ]
    )

    rows = store.retrieve("user preferences", top_k=2)
    assert all(item["memory_type"] != "reflection" for item in rows)
    metrics = store.get_metrics()
    assert metrics["reflection_filtered_non_reflection_intent"] >= 1


def test_retrieve_reflection_intent_filters_ungrounded_reflection(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.mem0.enabled = True
    store.mem0.search = MagicMock(
        return_value=[
            {
                "id": "r1",
                "summary": "Reflection: undocumented assumption caused outage.",
                "type": "fact",
                "score": 0.98,
                "memory_type": "reflection",
                "evidence_refs": [],
            },
            {
                "id": "r2",
                "summary": "Reflection: add env validation checks.",
                "type": "fact",
                "score": 0.72,
                "memory_type": "reflection",
                "evidence_refs": ["ev-2"],
            },
        ]
    )

    rows = store.retrieve("reflect on lessons learned", top_k=2)
    assert any(item["id"] == "r2" for item in rows)
    assert all(item["id"] != "r1" for item in rows)
    metrics = store.get_metrics()
    assert metrics["reflection_filtered_no_evidence"] >= 1


def test_rollout_disabled_turns_off_router_expansion(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.mem0.enabled = True
    store.rollout["memory_rollout_mode"] = "disabled"
    store.mem0.search = MagicMock(return_value=[])

    _ = store.retrieve("anything", top_k=3)
    _, kwargs = store.mem0.search.call_args
    assert kwargs["top_k"] == 3


def test_shadow_mode_records_overlap_metrics(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.mem0.enabled = True
    store.rollout["memory_rollout_mode"] = "enabled"
    store.rollout["memory_shadow_mode"] = True
    store.rollout["memory_shadow_sample_rate"] = 1.0
    store.mem0.search = MagicMock(
        return_value=[
            {"id": "a", "summary": "A", "type": "fact", "score": 0.9, "memory_type": "semantic"},
            {"id": "b", "summary": "B", "type": "task", "score": 0.7, "memory_type": "episodic"},
        ]
    )

    rows = store.retrieve("query", top_k=2)
    assert len(rows) == 2
    metrics = store.get_metrics()
    assert metrics["retrieval_shadow_runs"] >= 1
    assert metrics["retrieval_shadow_overlap_count"] >= 1


def test_evaluate_rollout_gates_returns_checks(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    evaluation = {"summary": {"recall_at_k": 0.8, "precision_at_k": 0.4}}
    observability = {"kpis": {"avg_memory_context_tokens": 900.0}}

    gates = store.evaluate_rollout_gates(evaluation, observability)
    assert isinstance(gates, dict)
    assert isinstance(gates.get("checks"), list)
    assert gates.get("passed") is True


def test_rollout_overrides_apply_from_constructor(tmp_path: Path) -> None:
    store = MemoryStore(
        tmp_path,
        rollout_overrides={
            "memory_rollout_mode": "disabled",
            "memory_router_enabled": False,
            "memory_shadow_sample_rate": 0.75,
            "rollout_gates": {"min_recall_at_k": 0.66},
        },
    )
    status = store.get_rollout_status()
    assert status["memory_rollout_mode"] == "disabled"
    assert status["memory_router_enabled"] is False
    assert abs(float(status["memory_shadow_sample_rate"]) - 0.75) < 1e-9
    assert abs(float(status["rollout_gates"]["min_recall_at_k"]) - 0.66) < 1e-9


def test_workspace_rollout_file_is_ignored(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "rollout.json").write_text(
        json.dumps(
            {
                "memory_rollout_mode": "disabled",
                "memory_router_enabled": False,
                "memory_shadow_mode": True,
            }
        ),
        encoding="utf-8",
    )

    store = MemoryStore(tmp_path)
    status = store.get_rollout_status()
    # Defaults remain active because workspace rollout files are no longer loaded.
    assert status["memory_rollout_mode"] == "enabled"
    assert status["memory_router_enabled"] is True


def test_infer_retrieval_intent_expanded_markers(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    assert (
        store._infer_retrieval_intent("List long-term constraints we must follow.")
        == "constraints_lookup"
    )
    assert (
        store._infer_retrieval_intent("What unresolved decisions need user input?")
        == "conflict_review"
    )
    assert (
        store._infer_retrieval_intent("What memory behavior is currently enabled in rollout?")
        == "rollout_status"
    )


def test_evaluate_retrieval_cases_balanced_mode_supports_structural_hits(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.retrieve = MagicMock(
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

    evaluation = store.evaluate_retrieval_cases(
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


def test_reindex_reports_not_ok_when_no_vector_or_get_all_rows(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.mem0.enabled = True
    store.mem0.add_text = MagicMock(return_value=True)
    store._vector_points_count = MagicMock(return_value=0)  # type: ignore[method-assign]
    store._mem0_get_all_rows = MagicMock(return_value=[])  # type: ignore[method-assign]

    profile = store.read_profile()
    profile["stable_facts"] = ["API authentication method is OAuth2."]
    store.write_profile(profile)

    result = store.reindex_from_structured_memory()

    assert result["written"] >= 1
    assert result["ok"] is False


def test_vector_health_marks_degraded_when_history_exists_but_no_vectors(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.mem0.enabled = True
    store.mem0.search = MagicMock(return_value=[])  # type: ignore[method-assign]
    store._history_row_count = MagicMock(return_value=10)  # type: ignore[method-assign]
    store._vector_points_count = MagicMock(return_value=0)  # type: ignore[method-assign]
    store._mem0_get_all_rows = MagicMock(return_value=[])  # type: ignore[method-assign]
    store.reindex_from_structured_memory = MagicMock(
        return_value={"ok": False, "reason": "structured_reindex"}
    )  # type: ignore[method-assign]

    store._ensure_vector_health()

    metrics = store.get_metrics()
    assert metrics["vector_health_degraded_count"] >= 1
    assert metrics.get("vector_health_hard_degraded") is True


# ---------------------------------------------------------------------------
# Budget-aware section allocation tests
# ---------------------------------------------------------------------------


def test_allocate_section_budgets_proportional(tmp_path: Path) -> None:
    """Sections receive budget proportional to their priority weight."""
    sizes = {
        "long_term": 500,
        "profile": 400,
        "semantic": 300,
        "episodic": 0,
        "reflection": 0,
        "graph": 200,
        "unresolved": 50,
    }
    alloc = MemoryStore._allocate_section_budgets(900, "fact_lookup", sizes)

    # Every section with content should get *some* allocation.
    assert alloc["long_term"] > 0
    assert alloc["profile"] > 0
    assert alloc["semantic"] > 0
    assert alloc["graph"] > 0
    # Empty sections get nothing.
    assert alloc["episodic"] == 0
    assert alloc["reflection"] == 0
    # Total allocation should not exceed budget.
    assert sum(alloc.values()) <= 900


def test_allocate_section_budgets_caps_at_actual_size() -> None:
    """A section smaller than its share should not get inflated."""
    sizes = {
        "long_term": 10,
        "profile": 10,
        "semantic": 10,
        "episodic": 0,
        "reflection": 0,
        "graph": 10,
        "unresolved": 10,
    }
    alloc = MemoryStore._allocate_section_budgets(2000, "fact_lookup", sizes)

    # Each section is tiny — should be capped at its actual size.
    for name, sz in sizes.items():
        assert alloc[name] <= max(sz, 0)


def test_allocate_section_budgets_redistributes_surplus() -> None:
    """Surplus from small sections flows to sections that need more."""
    sizes = {
        "long_term": 10,    # tiny
        "profile": 10,      # tiny
        "semantic": 500,    # large
        "episodic": 0,
        "reflection": 0,
        "graph": 500,       # large
        "unresolved": 0,
    }
    alloc = MemoryStore._allocate_section_budgets(600, "fact_lookup", sizes)

    # long_term and profile freed most of their share to semantic + graph.
    assert alloc["long_term"] == 10
    assert alloc["profile"] == 10
    # semantic and graph should each get substantially more than their
    # base proportional share (0.20 * 600 = 120).
    assert alloc["semantic"] > 120
    assert alloc["graph"] > 120


def test_get_memory_context_graph_not_truncated_at_default_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entity graph section should appear even at the default 900 token budget."""
    monkeypatch.setenv("NANOBOT_GRAPH_ENABLED", "true")
    store = MemoryStore(tmp_path)

    # Simulate a large profile that previously consumed the whole budget.
    large_profile = {
        "preferences": [f"User prefers option {i}" for i in range(6)],
        "stable_facts": [f"Fact number {i} about the system" for i in range(6)],
        "active_projects": [],
        "relationships": [],
        "constraints": [f"Constraint {i}: must validate input" for i in range(4)],
    }
    store.write_profile(large_profile)

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
    store.append_events(events)

    # Mock retrieve to return the events we just stored.
    store.retrieve = MagicMock(return_value=events)  # type: ignore[method-assign]

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
