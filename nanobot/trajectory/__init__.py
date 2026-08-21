"""Unified, content-free LLM trajectory backend."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_data_dir
from nanobot.trajectory.models import LLMCall
from nanobot.trajectory.store import TrajectoryStore

_STORES_LOCK = threading.Lock()
_STORES: dict[Path, TrajectoryStore] = {}


def empty_usage_payload() -> dict[str, Any]:
    return {
        "days": [],
        "total_tokens": 0,
        "total_tokens_30d": 0,
        "total_tokens_365d": 0,
        "reported_tokens_30d": 0,
        "estimated_tokens_30d": 0,
        "cache_read_tokens_30d": 0,
        "cache_read_observed_input_tokens_30d": 0,
        "cache_read_rate_30d": None,
        "peak_day_tokens": 0,
        "current_streak_days": 0,
        "longest_streak_days": 0,
        "active_days_30d": 0,
        "requests_30d": 0,
        "failed_requests_30d": 0,
        "providers_30d": [],
        "updated_at": None,
    }


def trajectory_store_path() -> Path:
    return get_data_dir() / "trajectory.sqlite3"


def get_trajectory_store(path: Path | None = None) -> TrajectoryStore:
    resolved = (path or trajectory_store_path()).resolve(strict=False)
    with _STORES_LOCK:
        store = _STORES.get(resolved)
        if store is None:
            store = TrajectoryStore(resolved)
            _STORES[resolved] = store
        return store


def record_llm_call(call: LLMCall) -> None:
    """Default fail-open callback attached to gateway provider snapshots."""
    try:
        get_trajectory_store().record(call)
    except Exception:
        logger.exception("failed to record LLM trajectory")


def trajectory_usage_payload(
    *,
    days: int = 371,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    try:
        return get_trajectory_store().usage_payload(
            days=days,
            timezone_name=timezone_name,
        )
    except Exception:
        logger.exception("failed to query LLM trajectory usage")
        return empty_usage_payload()


__all__ = [
    "LLMCall",
    "TrajectoryStore",
    "empty_usage_payload",
    "get_trajectory_store",
    "record_llm_call",
    "trajectory_store_path",
    "trajectory_usage_payload",
]
