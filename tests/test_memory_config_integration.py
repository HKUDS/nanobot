"""Tests that MemoryConfig replaces RolloutConfig for typed access."""

from __future__ import annotations

from unittest.mock import MagicMock

from nanobot.config.memory import MemoryConfig
from nanobot.memory.read.scoring import RetrievalScorer


def test_scorer_reads_reranker_mode_from_memory_config():
    mc = MemoryConfig(reranker={"mode": "disabled"})
    scorer = RetrievalScorer(
        profile_mgr=MagicMock(),
        reranker=MagicMock(),
        memory_config_fn=lambda: mc,
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
        memory_config_fn=lambda: mc,
    )
    items = [{"id": "1", "content": "test", "score": 1.0}]
    scorer.rerank_items("query", items)
    mock_reranker.rerank.assert_called_once()
