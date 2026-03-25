"""Tests for rollout_fn callback pattern in memory subsystems."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def test_ingester_uses_rollout_fn():
    """EventIngester reads rollout via callback, not cached dict."""
    from nanobot.memory.write.classification import EventClassifier
    from nanobot.memory.write.coercion import EventCoercer
    from nanobot.memory.write.dedup import EventDeduplicator
    from nanobot.memory.write.ingester import EventIngester

    rollout_dict: dict[str, Any] = {"memory_fallback_max_summary_chars": 300}
    classifier = EventClassifier()
    coercer = EventCoercer(classifier)
    dedup = EventDeduplicator(coercer=coercer)
    ingester = EventIngester(
        coercer=coercer,
        dedup=dedup,
        graph=None,
        rollout_fn=lambda: rollout_dict,
        db=None,
    )
    assert ingester._rollout_fn() is rollout_dict


def test_retriever_uses_rollout_fn():
    """RetrievalScorer reads rollout via callback, not cached dict."""
    from nanobot.memory.read.scoring import RetrievalScorer

    rollout_dict: dict[str, Any] = {"reranker_mode": "enabled"}
    scorer = RetrievalScorer(
        profile_mgr=MagicMock(),
        reranker=MagicMock(),
        rollout_fn=lambda: rollout_dict,
    )
    assert scorer._rollout_fn() is rollout_dict


def test_maintenance_uses_rollout_fn():
    """MemoryMaintenance reads rollout via callback, not cached dict."""
    from nanobot.memory.maintenance import MemoryMaintenance

    rollout_dict: dict[str, Any] = {"memory_vector_health_enabled": True}
    maintenance = MemoryMaintenance(
        rollout_fn=lambda: rollout_dict,
        db=None,
    )
    assert maintenance._rollout_fn() is rollout_dict
