"""Tests that MemoryConfig replaces RolloutConfig for typed access."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from nanobot.config.memory import MemoryConfig
from nanobot.memory.read.scoring import RetrievalScorer


def test_scorer_reads_reranker_mode_from_memory_config():
    mc = MemoryConfig(reranker={"mode": "disabled"})
    scorer = RetrievalScorer(
        profile_mgr=MagicMock(),
        reranker=MagicMock(),
        memory_config=mc,
    )
    items = [{"id": "1", "content": "test", "score": 1.0}]
    result = scorer.rerank_items("query", items)
    assert result == items  # disabled = no reranking


def test_scorer_reranker_mode_enabled():
    mc = MemoryConfig(reranker={"mode": "enabled"})
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = [{"id": "1", "content": "test", "score": 2.0}]
    scorer = RetrievalScorer(
        profile_mgr=MagicMock(),
        reranker=mock_reranker,
        memory_config=mc,
    )
    items = [{"id": "1", "content": "test", "score": 1.0}]
    scorer.rerank_items("query", items)
    mock_reranker.rerank.assert_called_once()


def test_eval_runner_reads_gates_from_memory_config() -> None:
    mc = MemoryConfig(
        rollout_gate_min_recall_at_k=0.7,
        rollout_gate_min_precision_at_k=0.3,
    )
    from nanobot.eval.memory_eval import EvalRunner

    mock_retriever = MagicMock()
    mock_maintenance = MagicMock()
    runner = EvalRunner(
        retriever=mock_retriever,
        workspace=Path("/tmp"),
        memory_dir=Path("/tmp"),
        memory_config=mc,
        maintenance=mock_maintenance,
    )
    result = runner.evaluate_rollout_gates(
        evaluation={"summary": {"recall_at_k": 0.8, "precision_at_k": 0.4}},
        observability={"kpis": {}},
    )
    assert result["checks"][0]["threshold"] == 0.7
    assert result["checks"][1]["threshold"] == 0.3
