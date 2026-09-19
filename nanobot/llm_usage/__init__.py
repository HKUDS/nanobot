"""Unified, content-free LLM usage backend."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_data_dir
from nanobot.llm_usage.models import LLMCallRecord
from nanobot.llm_usage.store import LLMUsageStore

_STORES_LOCK = threading.Lock()
_STORES: dict[Path, LLMUsageStore] = {}


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


def llm_usage_store_path() -> Path:
    return get_data_dir() / "llm_usage.sqlite3"


def get_llm_usage_store(path: Path | None = None) -> LLMUsageStore:
    resolved = (path or llm_usage_store_path()).resolve(strict=False)
    with _STORES_LOCK:
        store = _STORES.get(resolved)
        if store is None:
            store = LLMUsageStore(resolved)
            _STORES[resolved] = store
        return store


def record_llm_call(call: LLMCallRecord) -> None:
    """Default fail-open callback attached to gateway provider snapshots."""
    try:
        get_llm_usage_store().record(call)
    except Exception:
        logger.exception("failed to record LLM usage")


def llm_usage_payload(
    *,
    days: int = 371,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    try:
        return get_llm_usage_store().usage_payload(
            days=days,
            timezone_name=timezone_name,
        )
    except Exception:
        logger.exception("failed to query LLM usage")
        return empty_usage_payload()


__all__ = [
    "LLMCallRecord",
    "LLMUsageStore",
    "empty_usage_payload",
    "get_llm_usage_store",
    "record_llm_call",
    "llm_usage_store_path",
    "llm_usage_payload",
]
