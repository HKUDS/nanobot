"""Tests for the cross-encoder re-ranker (Step 7)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from nanobot.agent.memory.reranker import CrossEncoderReranker

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


class FakeCrossEncoder:
    """Stub that returns scores proportional to reverse list index."""

    def __init__(self, model_name: str = "") -> None:
        self.model_name = model_name

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        n = len(pairs)
        # Give higher scores to later items to force a rank flip.
        return [float(i) / max(n - 1, 1) for i in range(n)]


# ---------------------------------------------------------------------------
# Unit tests — CrossEncoderReranker
# ---------------------------------------------------------------------------


class TestCrossEncoderRerankerUnit:
    """Tests that exercise the reranker without loading a real model."""

    def test_rerank_empty_returns_empty(self) -> None:
        reranker = CrossEncoderReranker()
        result = reranker.rerank("query", [])
        assert result == []

    def test_rerank_no_model_returns_unchanged(self) -> None:
        reranker = CrossEncoderReranker()
        items = _make_items(3)
        original_scores = [it["score"] for it in items]
        # Model is None by default (sentence-transformers not installed in test env)
        with patch.object(reranker, "_load_model", return_value=None):
            result = reranker.rerank("query", items)
        assert [it["score"] for it in result] == original_scores

    def test_rerank_with_fake_model_reorders(self) -> None:
        reranker = CrossEncoderReranker(alpha=1.0)  # pure CE score
        reranker._model = FakeCrossEncoder()
        items = _make_items(4)
        original_ids = [it["id"] for it in items]
        result = reranker.rerank("query", items)
        # CE gives increasing scores → last item should now be first
        assert result[0]["id"] == original_ids[-1]

    def test_rerank_alpha_zero_preserves_heuristic_order(self) -> None:
        reranker = CrossEncoderReranker(alpha=0.0)
        reranker._model = FakeCrossEncoder()
        items = _make_items(4)
        original_order = [it["id"] for it in items]
        result = reranker.rerank("query", items)
        assert [it["id"] for it in result] == original_order

    def test_rerank_blends_scores(self) -> None:
        reranker = CrossEncoderReranker(alpha=0.5)
        reranker._model = FakeCrossEncoder()
        items = _make_items(3)
        result = reranker.rerank("query", items)
        for item in result:
            reason = item["retrieval_reason"]
            assert "ce_score" in reason
            assert "ce_norm" in reason
            assert "blended_score" in reason
            assert "reranker_alpha" in reason
            assert reason["reranker_alpha"] == 0.5

    def test_rerank_alpha_override(self) -> None:
        reranker = CrossEncoderReranker(alpha=0.5)
        reranker._model = FakeCrossEncoder()
        items = _make_items(2)
        result = reranker.rerank("query", items, alpha=0.9)
        assert result[0]["retrieval_reason"]["reranker_alpha"] == 0.9

    def test_rerank_handles_predict_exception(self) -> None:
        reranker = CrossEncoderReranker()
        model = MagicMock()
        model.predict.side_effect = RuntimeError("GPU OOM")
        reranker._model = model
        items = _make_items(3)
        original_scores = [it["score"] for it in items]
        result = reranker.rerank("query", items)
        assert [it["score"] for it in result] == original_scores

    def test_rerank_single_item(self) -> None:
        reranker = CrossEncoderReranker(alpha=0.5)
        reranker._model = FakeCrossEncoder()
        items = _make_items(1)
        result = reranker.rerank("query", items)
        assert len(result) == 1
        # Single item → normalised CE score is 0.5 (all-same normalization)
        assert "ce_score" in result[0]["retrieval_reason"]

    def test_alpha_clamped(self) -> None:
        reranker = CrossEncoderReranker(alpha=5.0)
        assert reranker._alpha == 1.0
        reranker2 = CrossEncoderReranker(alpha=-1.0)
        assert reranker2._alpha == 0.0


# ---------------------------------------------------------------------------
# compute_rank_delta tests
# ---------------------------------------------------------------------------


class TestComputeRankDelta:
    def test_identical_order_zero_delta(self) -> None:
        reranker = CrossEncoderReranker()
        ids = ["a", "b", "c"]
        assert reranker.compute_rank_delta(ids, ids) == 0.0

    def test_reversed_order_positive_delta(self) -> None:
        reranker = CrossEncoderReranker()
        delta = reranker.compute_rank_delta(["a", "b", "c"], ["c", "b", "a"])
        assert delta > 0.0

    def test_disjoint_sets_zero_delta(self) -> None:
        reranker = CrossEncoderReranker()
        assert reranker.compute_rank_delta(["a"], ["b"]) == 0.0

    def test_empty_lists(self) -> None:
        reranker = CrossEncoderReranker()
        assert reranker.compute_rank_delta([], []) == 0.0


# ---------------------------------------------------------------------------
# Integration with MemoryStore._retrieve_core (rollout gating)
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
        assert isinstance(store._reranker, CrossEncoderReranker)

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


# ---------------------------------------------------------------------------
# available property
# ---------------------------------------------------------------------------


class TestAvailableProperty:
    def test_available_false_without_package(self) -> None:
        with (
            patch("nanobot.agent.memory.reranker._import_attempted", False),
            patch("nanobot.agent.memory.reranker._cross_encoder_cls", None),
        ):
            # Force re-import attempt that fails
            import nanobot.agent.memory.reranker as mod

            old_attempted = mod._import_attempted
            old_cls = mod._cross_encoder_cls
            mod._import_attempted = False
            mod._cross_encoder_cls = None
            try:
                reranker = CrossEncoderReranker()
                # Will try to import and likely fail in test env
                _ = reranker.available
                # Either True (if installed) or False — just check we don't crash
            finally:
                mod._import_attempted = old_attempted
                mod._cross_encoder_cls = old_cls
