"""Tests for rollout_fn callback pattern in memory subsystems."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def test_ingester_uses_rollout_fn():
    """EventIngester reads rollout via callback, not cached dict."""
    from nanobot.memory.write.ingester import EventIngester

    rollout_dict: dict[str, Any] = {"memory_fallback_max_summary_chars": 300}
    ingester = EventIngester(
        graph=None,
        rollout_fn=lambda: rollout_dict,
        db=None,
    )
    assert ingester._rollout_fn() is rollout_dict


def test_retriever_uses_rollout_fn():
    """MemoryRetriever reads rollout via callback, not cached dict."""
    from nanobot.memory.read.retriever import MemoryRetriever

    rollout_dict: dict[str, Any] = {"reranker_mode": "enabled"}
    retriever = MemoryRetriever(
        graph=None,
        planner=MagicMock(),
        reranker=MagicMock(),
        profile_mgr=MagicMock(),
        rollout_fn=lambda: rollout_dict,
        read_events_fn=MagicMock(),
        db=None,
    )
    assert retriever._rollout_fn() is rollout_dict


def test_maintenance_uses_rollout_fn():
    """MemoryMaintenance reads rollout via callback, not cached dict."""
    from nanobot.memory.maintenance import MemoryMaintenance

    rollout_dict: dict[str, Any] = {"memory_vector_health_enabled": True}
    maintenance = MemoryMaintenance(
        rollout_fn=lambda: rollout_dict,
        db=None,
    )
    assert maintenance._rollout_fn() is rollout_dict
