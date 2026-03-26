"""Tests for RetrievalScorer — filter, score, and rerank pipeline stages."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from nanobot.config.memory import MemoryConfig
from nanobot.memory.read.scoring import (
    PROFILE_KEYS,
    RetrievalScorer,
)


def _make_scorer(
    *,
    memory_config: MemoryConfig | None = None,
) -> RetrievalScorer:
    """Build a RetrievalScorer with mocked dependencies."""
    profile_mgr = MagicMock()
    profile_mgr.read_profile = MagicMock(return_value={})
    profile_mgr._meta_section = MagicMock(return_value={})

    reranker = MagicMock()
    reranker.rerank = MagicMock(side_effect=lambda q, items: items)

    mc = memory_config or MemoryConfig()
    return RetrievalScorer(
        profile_mgr=profile_mgr,
        reranker=reranker,
        memory_config_fn=lambda: mc,
    )


def _make_plan(
    *,
    intent: str = "general",
    policy: dict[str, Any] | None = None,
    routing_hints: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a mock RetrievalPlan."""
    plan = MagicMock()
    plan.intent = intent
    plan.policy = policy or {
        "candidate_multiplier": 3,
        "half_life_days": 60.0,
        "fallback_topics": [],
        "fallback_types": [],
        "type_boost": {},
    }
    plan.routing_hints = routing_hints or {
        "focus_task_decision": False,
        "focus_planning": False,
        "focus_architecture": False,
        "requires_open": False,
        "requires_resolved": False,
    }
    return plan


class TestLoadProfileScoringData:
    """load_profile_scoring_data extracts conflict resolution data."""

    def test_empty_profile(self) -> None:
        scorer = _make_scorer()
        data = scorer.load_profile_scoring_data()
        assert data["profile"] == {}
        assert all(len(v) == 0 for v in data["resolved_keep_new_old"].values())
        assert all(len(v) == 0 for v in data["resolved_keep_new_new"].values())

    def test_resolved_keep_new_extracted(self) -> None:
        scorer = _make_scorer()
        scorer._profile_mgr.read_profile.return_value = {
            "conflicts": [
                {
                    "status": "resolved",
                    "resolution": "keep_new",
                    "field": "preferences",
                    "old": "dark mode",
                    "new": "light mode",
                }
            ]
        }
        data = scorer.load_profile_scoring_data()
        assert len(data["resolved_keep_new_old"]["preferences"]) == 1
        assert len(data["resolved_keep_new_new"]["preferences"]) == 1


class TestFilterItems:
    """filter_items applies routing hints and intent filters."""

    def test_general_passes_all(self) -> None:
        scorer = _make_scorer()
        plan = _make_plan()
        items = [
            {"id": "f1", "type": "fact", "summary": "Fact one", "topic": "general"},
            {"id": "f2", "type": "fact", "summary": "Fact two", "topic": "general"},
        ]
        filtered, _ = scorer.filter_items(items, plan)
        assert len(filtered) == 2

    def test_focus_task_decision(self) -> None:
        scorer = _make_scorer()
        plan = _make_plan(
            routing_hints={
                "focus_task_decision": True,
                "focus_planning": False,
                "focus_architecture": False,
                "requires_open": False,
                "requires_resolved": False,
            }
        )
        items = [
            {"id": "t1", "type": "task", "summary": "Build", "topic": "task_progress"},
            {"id": "f1", "type": "fact", "summary": "Info", "topic": "language"},
        ]
        filtered, _ = scorer.filter_items(items, plan)
        assert len(filtered) == 1
        assert filtered[0]["id"] == "t1"


class TestScoreItems:
    """score_items applies the unified scoring formula."""

    def test_type_boost_increases_score(self) -> None:
        scorer = _make_scorer()
        plan = _make_plan(
            policy={
                "candidate_multiplier": 3,
                "half_life_days": 60.0,
                "fallback_topics": [],
                "fallback_types": [],
                "type_boost": {"semantic": 0.1},
            }
        )
        profile_data = {
            "profile": {},
            "resolved_keep_new_old": {k: set() for k in PROFILE_KEYS},
            "resolved_keep_new_new": {k: set() for k in PROFILE_KEYS},
        }
        items = [
            {
                "id": "s1",
                "type": "fact",
                "summary": "Semantic",
                "memory_type": "semantic",
                "timestamp": "2025-01-01T00:00:00Z",
                "score": 0.5,
                "stability": "medium",
                "entities": [],
            },
            {
                "id": "e1",
                "type": "task",
                "summary": "Episodic",
                "memory_type": "episodic",
                "timestamp": "2025-01-01T00:00:00Z",
                "score": 0.5,
                "stability": "medium",
                "entities": [],
            },
        ]
        scored = scorer.score_items(
            items,
            plan,
            profile_data,
            set(),
            use_recency=True,
            router_enabled=True,
            type_separation_enabled=True,
        )
        scores = {r["id"]: r["score"] for r in scored}
        assert scores["s1"] > scores["e1"]

    def test_graph_entity_boost(self) -> None:
        scorer = _make_scorer()
        plan = _make_plan()
        profile_data = {
            "profile": {},
            "resolved_keep_new_old": {k: set() for k in PROFILE_KEYS},
            "resolved_keep_new_new": {k: set() for k in PROFILE_KEYS},
        }
        items = [
            {
                "id": "g1",
                "type": "fact",
                "summary": "Graph item",
                "memory_type": "semantic",
                "timestamp": "2025-01-01T00:00:00Z",
                "score": 0.5,
                "stability": "medium",
                "entities": ["alice"],
            },
        ]
        scored = scorer.score_items(
            items,
            plan,
            profile_data,
            {"alice"},
            use_recency=True,
            router_enabled=True,
            type_separation_enabled=True,
        )
        assert scored[0]["score"] > 0.5  # boosted by graph entity match


class TestRerankItems:
    """rerank_items delegates to reranker based on rollout mode."""

    def test_enabled_calls_reranker(self) -> None:
        scorer = _make_scorer(memory_config=MemoryConfig(reranker={"mode": "enabled"}))
        items = [{"id": "a", "score": 0.5, "summary": "A"}]
        scorer.rerank_items("query", items)
        scorer._reranker.rerank.assert_called_once()

    def test_disabled_passthrough(self) -> None:
        scorer = _make_scorer(memory_config=MemoryConfig(reranker={"mode": "disabled"}))
        items = [{"id": "a", "score": 0.5, "summary": "A"}]
        result = scorer.rerank_items("query", items)
        scorer._reranker.rerank.assert_not_called()
        assert result is items

    def test_empty_items_passthrough(self) -> None:
        scorer = _make_scorer(memory_config=MemoryConfig(reranker={"mode": "enabled"}))
        result = scorer.rerank_items("query", [])
        scorer._reranker.rerank.assert_not_called()
        assert result == []
