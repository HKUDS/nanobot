"""Tests for OnnxCrossEncoderReranker."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

from nanobot.agent.memory.onnx_reranker import OnnxCrossEncoderReranker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_items(*scores: float) -> list[dict[str, Any]]:
    """Build minimal memory items with the given heuristic scores."""
    return [
        {
            "id": f"item-{i}",
            "summary": f"Summary for item {i}",
            "score": s,
            "retrieval_reason": {"score": s},
        }
        for i, s in enumerate(scores)
    ]


# ---------------------------------------------------------------------------
# TestOnnxRerankerAvailable
# ---------------------------------------------------------------------------


class TestOnnxRerankerAvailable:
    """OnnxCrossEncoderReranker.available is always True."""

    def test_available_is_true(self) -> None:
        reranker = OnnxCrossEncoderReranker()
        assert reranker.available is True

    def test_available_true_regardless_of_model_name(self) -> None:
        reranker = OnnxCrossEncoderReranker(model_name="nonexistent-model")
        assert reranker.available is True


# ---------------------------------------------------------------------------
# TestOnnxRerankerEmptyInput
# ---------------------------------------------------------------------------


class TestOnnxRerankerEmptyInput:
    """Empty items list returns empty without loading any model."""

    def test_empty_items_returns_empty(self) -> None:
        reranker = OnnxCrossEncoderReranker()
        result = reranker.rerank("test query", [])
        assert result == []

    def test_empty_items_does_not_load_model(self) -> None:
        reranker = OnnxCrossEncoderReranker()
        reranker.rerank("test query", [])
        assert reranker._session is None


# ---------------------------------------------------------------------------
# TestOnnxRerankerWithMockSession
# ---------------------------------------------------------------------------


class TestOnnxRerankerWithMockSession:
    """Mock the ONNX session to return known scores, verify blending + sorting."""

    def _setup_reranker(self, logits: np.ndarray, alpha: float = 0.5) -> OnnxCrossEncoderReranker:
        """Create a reranker with a mocked ONNX session returning *logits*."""
        reranker = OnnxCrossEncoderReranker(alpha=alpha)

        # Mock session
        mock_session = MagicMock()
        mock_session.run.return_value = [logits]
        reranker._session = mock_session

        # Mock tokenizer
        mock_tokenizer = MagicMock()
        mock_encoding = MagicMock()
        mock_encoding.ids = [101, 2023, 2003, 102, 2070, 3793, 102]
        mock_encoding.attention_mask = [1, 1, 1, 1, 1, 1, 1]
        mock_encoding.type_ids = [0, 0, 0, 0, 1, 1, 1]
        mock_tokenizer.encode.return_value = mock_encoding
        reranker._tokenizer = mock_tokenizer

        return reranker

    def test_blending_and_sorting(self) -> None:
        # Logits: item-0 gets low score, item-1 gets high score
        logits = np.array([[-2.0], [3.0]], dtype=np.float32)
        reranker = self._setup_reranker(logits, alpha=0.5)

        items = _make_items(0.8, 0.2)
        result = reranker.rerank("test query", items)

        # item-1 should have higher blended score due to high CE score
        assert result[0]["id"] == "item-1"
        assert result[1]["id"] == "item-0"

        # Check ce_score is sigmoid of logit
        for item in result:
            reason = item["retrieval_reason"]
            assert "ce_score" in reason
            assert "blended_score" in reason
            assert 0.0 <= reason["ce_score"] <= 1.0

    def test_alpha_zero_preserves_heuristic_order(self) -> None:
        # With alpha=0, CE score has no effect — heuristic order preserved
        logits = np.array([[10.0], [-10.0]], dtype=np.float32)
        reranker = self._setup_reranker(logits, alpha=0.0)

        items = _make_items(0.9, 0.1)
        result = reranker.rerank("test query", items)

        assert result[0]["id"] == "item-0"
        assert result[1]["id"] == "item-1"

    def test_alpha_one_uses_only_ce(self) -> None:
        # With alpha=1, only CE score matters
        logits = np.array([[-5.0], [5.0]], dtype=np.float32)
        reranker = self._setup_reranker(logits, alpha=1.0)

        items = _make_items(0.99, 0.01)
        result = reranker.rerank("test query", items)

        # item-1 has higher logit -> higher sigmoid -> should be first
        assert result[0]["id"] == "item-1"

    def test_alpha_override_in_rerank(self) -> None:
        logits = np.array([[5.0], [-5.0]], dtype=np.float32)
        reranker = self._setup_reranker(logits, alpha=0.5)

        items = _make_items(0.1, 0.9)
        # Override alpha to 0 — heuristic only
        result = reranker.rerank("test query", items, alpha=0.0)

        assert result[0]["id"] == "item-1"  # higher heuristic
        assert result[1]["id"] == "item-0"

    def test_inference_failure_returns_items_unchanged(self) -> None:
        reranker = OnnxCrossEncoderReranker()

        mock_session = MagicMock()
        mock_session.run.side_effect = RuntimeError("ONNX error")
        reranker._session = mock_session

        mock_tokenizer = MagicMock()
        mock_encoding = MagicMock()
        mock_encoding.ids = [101, 102]
        mock_encoding.attention_mask = [1, 1]
        mock_encoding.type_ids = [0, 0]
        mock_tokenizer.encode.return_value = mock_encoding
        reranker._tokenizer = mock_tokenizer

        items = _make_items(0.5, 0.3)
        original_ids = [item["id"] for item in items]
        result = reranker.rerank("test", items)
        assert [item["id"] for item in result] == original_ids

    def test_items_without_retrieval_reason(self) -> None:
        """Items without retrieval_reason dict get one created."""
        logits = np.array([[1.0], [2.0]], dtype=np.float32)
        reranker = self._setup_reranker(logits)

        items = [
            {"id": "a", "summary": "foo", "score": 0.5},
            {"id": "b", "summary": "bar", "score": 0.3},
        ]
        result = reranker.rerank("test", items)
        for item in result:
            assert "retrieval_reason" in item
            assert "ce_score" in item["retrieval_reason"]


# ---------------------------------------------------------------------------
# TestOnnxRerankerModelDownload
# ---------------------------------------------------------------------------


class TestOnnxRerankerModelDownload:
    """Mock httpx to test download path."""

    def test_download_success(self, tmp_path: Any) -> None:
        reranker = OnnxCrossEncoderReranker()
        reranker._model_dir = tmp_path / "test-model"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_bytes.return_value = [b"fake model data"]
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("httpx.stream", return_value=mock_response):
            result = reranker._download_model()

        assert result is True
        assert (reranker._model_dir / "model.onnx").exists()
        assert (reranker._model_dir / "tokenizer.json").exists()

    def test_download_failure(self, tmp_path: Any) -> None:
        reranker = OnnxCrossEncoderReranker()
        reranker._model_dir = tmp_path / "test-model"

        with patch("httpx.stream", side_effect=ConnectionError("network error")):
            result = reranker._download_model()

        assert result is False
        # Partial files should be cleaned up
        assert not (reranker._model_dir / "model.onnx").exists()

    def test_download_skips_existing_files(self, tmp_path: Any) -> None:
        reranker = OnnxCrossEncoderReranker()
        reranker._model_dir = tmp_path / "test-model"
        reranker._model_dir.mkdir(parents=True)

        # Pre-create the files
        (reranker._model_dir / "model.onnx").write_bytes(b"existing")
        (reranker._model_dir / "tokenizer.json").write_bytes(b"existing")

        with patch("httpx.stream") as mock_stream:
            result = reranker._download_model()

        assert result is True
        mock_stream.assert_not_called()

    def test_ensure_model_fails_gracefully_on_download_failure(self, tmp_path: Any) -> None:
        reranker = OnnxCrossEncoderReranker()
        reranker._model_dir = tmp_path / "no-model"

        with patch("httpx.stream", side_effect=ConnectionError("fail")):
            result = reranker._ensure_model()

        assert result is False
        assert reranker._session is None


# ---------------------------------------------------------------------------
# TestComputeRankDelta
# ---------------------------------------------------------------------------


class TestComputeRankDelta:
    """compute_rank_delta matches CompositeReranker implementation."""

    def test_identical_order(self) -> None:
        reranker = OnnxCrossEncoderReranker()
        delta = reranker.compute_rank_delta(["a", "b", "c"], ["a", "b", "c"])
        assert delta == 0.0

    def test_reversed_order(self) -> None:
        reranker = OnnxCrossEncoderReranker()
        delta = reranker.compute_rank_delta(["a", "b", "c"], ["c", "b", "a"])
        # a: |0-2|=2, b: |1-1|=0, c: |2-0|=2 => avg = 4/3
        assert abs(delta - 4 / 3) < 1e-9

    def test_empty_lists(self) -> None:
        reranker = OnnxCrossEncoderReranker()
        assert reranker.compute_rank_delta([], []) == 0.0

    def test_no_common_items(self) -> None:
        reranker = OnnxCrossEncoderReranker()
        assert reranker.compute_rank_delta(["a"], ["b"]) == 0.0

    def test_partial_overlap(self) -> None:
        reranker = OnnxCrossEncoderReranker()
        delta = reranker.compute_rank_delta(["a", "b", "x"], ["b", "a", "y"])
        # common: a, b; a: |0-1|=1, b: |1-0|=1 => avg = 1.0
        assert delta == 1.0
