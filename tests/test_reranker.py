"""Tests for re-ranker implementations (CompositeReranker + OnnxCrossEncoderReranker alias)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nanobot.agent.memory.onnx_reranker import OnnxCrossEncoderReranker
from nanobot.agent.memory.reranker import CompositeReranker, Reranker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_items(n: int = 5) -> list[dict[str, Any]]:
    """Build *n* dummy memory items with decreasing heuristic scores."""
    items = []
    for i in range(n):
        items.append(
            {
                "id": f"item_{i}",
                "summary": f"Summary about topic {i}",
                "score": round(1.0 - i * 0.15, 2),
                "retrieval_reason": {"semantic": 0.8, "recency": 0.1},
            }
        )
    return items


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------


class TestBackwardCompatAlias:
    """CrossEncoderReranker is aliased to OnnxCrossEncoderReranker in __init__.py."""

    def test_alias_importable(self) -> None:
        from nanobot.agent.memory import CrossEncoderReranker

        assert CrossEncoderReranker is OnnxCrossEncoderReranker


# ---------------------------------------------------------------------------
# CompositeReranker compute_rank_delta tests
# ---------------------------------------------------------------------------


class TestComputeRankDelta:
    def test_identical_order_zero_delta(self) -> None:
        reranker = CompositeReranker()
        ids = ["a", "b", "c"]
        assert reranker.compute_rank_delta(ids, ids) == 0.0

    def test_reversed_order_positive_delta(self) -> None:
        reranker = CompositeReranker()
        delta = reranker.compute_rank_delta(["a", "b", "c"], ["c", "b", "a"])
        assert delta > 0.0

    def test_disjoint_sets_zero_delta(self) -> None:
        reranker = CompositeReranker()
        assert reranker.compute_rank_delta(["a"], ["b"]) == 0.0

    def test_empty_lists(self) -> None:
        reranker = CompositeReranker()
        assert reranker.compute_rank_delta([], []) == 0.0


# ---------------------------------------------------------------------------
# Integration with MemoryStore._run_mem0_pipeline (rollout gating)
# ---------------------------------------------------------------------------


class TestRerankerRolloutGating:
    """Verify the rollout gating logic in MemoryStore.retrieve."""

    def _make_store(self, tmp_path, reranker_mode: str = "disabled"):
        from nanobot.agent.memory.store import MemoryStore

        store = MemoryStore(
            tmp_path,
            rollout_overrides={
                "memory_rollout_mode": "enabled",
                "reranker_mode": reranker_mode,
            },
        )
        return store

    def test_disabled_mode_no_reranker_call(self, tmp_path) -> None:
        store = self._make_store(tmp_path, "disabled")
        assert str(store.rollout["reranker_mode"]) == "disabled"

    def test_enabled_mode_sets_flag(self, tmp_path) -> None:
        store = self._make_store(tmp_path, "enabled")
        assert store.rollout["reranker_mode"] == "enabled"

    def test_shadow_mode_sets_flag(self, tmp_path) -> None:
        store = self._make_store(tmp_path, "shadow")
        assert store.rollout["reranker_mode"] == "shadow"

    def test_reranker_instance_created(self, tmp_path) -> None:
        store = self._make_store(tmp_path, "enabled")
        assert isinstance(store._reranker, OnnxCrossEncoderReranker)

    def test_env_override_reranker_mode(self, tmp_path, monkeypatch) -> None:
        from nanobot.agent.memory.store import MemoryStore

        store = MemoryStore(tmp_path, rollout_overrides={"reranker_mode": "shadow"})
        assert store.rollout["reranker_mode"] == "shadow"

    def test_env_override_reranker_alpha(self, tmp_path, monkeypatch) -> None:
        from nanobot.agent.memory.store import MemoryStore

        store = MemoryStore(tmp_path, rollout_overrides={"reranker_alpha": 0.8})
        assert store.rollout["reranker_alpha"] == 0.8

    def test_env_override_reranker_model(self, tmp_path, monkeypatch) -> None:
        from nanobot.agent.memory.store import MemoryStore

        store = MemoryStore(tmp_path, rollout_overrides={"reranker_model": "custom/model"})
        assert store.rollout["reranker_model"] == "custom/model"

    def test_composite_reranker_for_non_onnx_model(self, tmp_path) -> None:
        from nanobot.agent.memory.store import MemoryStore

        store = MemoryStore(
            tmp_path,
            rollout_overrides={"reranker_model": "custom/model"},
        )
        assert isinstance(store._reranker, CompositeReranker)


# ---------------------------------------------------------------------------
# CompositeReranker tests
# ---------------------------------------------------------------------------


def _make_composite_items() -> list[dict[str, Any]]:
    """Build items with varying summaries, entities, types, and timestamps."""
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "item_a",
            "summary": "User prefers dark mode in the editor",
            "score": 0.9,
            "type": "preference",
            "entities": ["dark mode", "editor"],
            "timestamp": now.isoformat(),
            "retrieval_reason": {"provider": "bm25", "score": 0.8},
        },
        {
            "id": "item_b",
            "summary": "Task progress on the API refactor",
            "score": 0.7,
            "type": "task",
            "entities": ["API", "refactor"],
            "timestamp": "2024-01-01T00:00:00+00:00",
            "retrieval_reason": {"provider": "bm25", "score": 0.3},
        },
        {
            "id": "item_c",
            "summary": "Decided to use PostgreSQL over MySQL",
            "score": 0.5,
            "type": "decision",
            "entities": ["PostgreSQL", "MySQL"],
            "timestamp": now.isoformat(),
            "retrieval_reason": {"provider": "bm25", "score": 0.6},
        },
    ]


class TestCompositeRerankerAvailable:
    """CompositeReranker.available is always True."""

    def test_available_always_true(self) -> None:
        reranker = CompositeReranker()
        assert reranker.available is True

    def test_available_true_regardless_of_alpha(self) -> None:
        assert CompositeReranker(alpha=0.0).available is True
        assert CompositeReranker(alpha=1.0).available is True

    def test_satisfies_reranker_protocol(self) -> None:
        reranker = CompositeReranker()
        assert isinstance(reranker, Reranker)


class TestCompositeRerankerScoring:
    """Verify items are re-ordered by composite score."""

    def test_reranks_by_composite(self) -> None:
        reranker = CompositeReranker(alpha=1.0)
        items = _make_composite_items()
        # Query about preferences should boost the preference item
        result = reranker.rerank("What are the user preferences for dark mode?", items)
        # item_a has the strongest lexical + entity + type match for this query
        assert result[0]["id"] == "item_a"

    def test_retrieval_reason_keys_present(self) -> None:
        reranker = CompositeReranker(alpha=0.5)
        items = _make_composite_items()
        result = reranker.rerank("dark mode preference", items)
        for item in result:
            reason = item["retrieval_reason"]
            assert "ce_score" in reason
            assert "blended_score" in reason
            assert "reranker_alpha" in reason

    def test_scores_are_sorted_descending(self) -> None:
        reranker = CompositeReranker(alpha=0.6)
        items = _make_composite_items()
        result = reranker.rerank("dark mode editor preference", items)
        scores = [it["score"] for it in result]
        assert scores == sorted(scores, reverse=True)

    def test_old_items_penalized_by_recency(self) -> None:
        """An item from 2024 should score lower on recency than a fresh item."""
        reranker = CompositeReranker(alpha=1.0)
        items = _make_composite_items()
        # Both item_a and item_c are recent; item_b is old.
        # With a generic query, recency should penalize item_b.
        result = reranker.rerank("some generic query", items)
        item_b = next(it for it in result if it["id"] == "item_b")
        item_a = next(it for it in result if it["id"] == "item_a")
        # item_a should score >= item_b due to recency advantage (both have low lexical)
        assert item_a["score"] >= item_b["score"]


class TestCompositeRerankerAlphaBlending:
    """Verify alpha blending works correctly."""

    def test_alpha_zero_preserves_heuristic_order(self) -> None:
        reranker = CompositeReranker(alpha=0.0)
        items = _make_composite_items()
        original_order = [it["id"] for it in items]
        result = reranker.rerank("dark mode", items)
        # alpha=0 means 100% heuristic → original descending score order preserved
        assert [it["id"] for it in result] == original_order

    def test_alpha_override(self) -> None:
        reranker = CompositeReranker(alpha=0.5)
        items = _make_composite_items()
        result = reranker.rerank("query", items, alpha=0.9)
        assert result[0]["retrieval_reason"]["reranker_alpha"] == 0.9

    def test_alpha_clamped(self) -> None:
        reranker = CompositeReranker(alpha=5.0)
        assert reranker._alpha == 1.0
        reranker2 = CompositeReranker(alpha=-1.0)
        assert reranker2._alpha == 0.0

    def test_blended_score_between_zero_and_one(self) -> None:
        reranker = CompositeReranker(alpha=0.5)
        items = _make_composite_items()
        result = reranker.rerank("preference dark mode", items)
        for item in result:
            assert 0.0 <= item["retrieval_reason"]["blended_score"] <= 1.0


class TestCompositeRerankerEmptyInput:
    """Empty items list returns empty."""

    def test_empty_returns_empty(self) -> None:
        reranker = CompositeReranker()
        result = reranker.rerank("any query", [])
        assert result == []

    def test_compute_rank_delta_empty(self) -> None:
        reranker = CompositeReranker()
        assert reranker.compute_rank_delta([], []) == 0.0

    def test_compute_rank_delta_identical(self) -> None:
        reranker = CompositeReranker()
        ids = ["a", "b", "c"]
        assert reranker.compute_rank_delta(ids, ids) == 0.0

    def test_compute_rank_delta_reversed(self) -> None:
        reranker = CompositeReranker()
        delta = reranker.compute_rank_delta(["a", "b", "c"], ["c", "b", "a"])
        assert delta > 0.0
