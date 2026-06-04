"""Workspace-scoped token usage telemetry for WebUI overview surfaces."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.config.paths import get_webui_dir

TOKEN_USAGE_SCHEMA_VERSION = 1
_MAX_STATE_FILE_BYTES = 512 * 1024
_MAX_DAYS_RETAINED = 400
_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "cached_tokens",
    "total_tokens",
    "provider_tokens",
    "estimated_tokens",
)
_REQUEST_KEYS = ("requests", "provider_requests", "estimated_requests")
_SOURCE_KEYS = ("user", "api", "cron", "dream", "system")
_WRITE_LOCK = threading.Lock()


def token_usage_state_path() -> Path:
    return get_webui_dir() / "token-usage.json"


def default_token_usage_state() -> dict[str, Any]:
    return {
        "schema_version": TOKEN_USAGE_SCHEMA_VERSION,
        "days": {},
        "updated_at": None,
    }


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _zone(timezone_name: str | None) -> timezone | ZoneInfo:
    if not timezone_name:
        return timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _local_day(now: datetime | None = None, *, timezone_name: str | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_zone(timezone_name)).date().isoformat()


def _clean_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _clean_source(value: str | None) -> str:
    return value if value in _SOURCE_KEYS else "system"


def _normalize_usage(raw: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    usage = {key: _clean_int(raw.get(key)) for key in _USAGE_KEYS}
    fallback_total = usage["prompt_tokens"] + usage["completion_tokens"]
    if usage["total_tokens"] <= 0:
        usage["total_tokens"] = fallback_total
    if usage["estimated_tokens"] <= 0 and usage["provider_tokens"] <= 0:
        usage["provider_tokens"] = usage["total_tokens"]
    elif usage["estimated_tokens"] > 0 and usage["provider_tokens"] <= 0:
        usage["estimated_tokens"] = min(usage["estimated_tokens"], usage["total_tokens"])
    elif usage["provider_tokens"] > 0 and usage["estimated_tokens"] <= 0:
        usage["provider_tokens"] = min(usage["provider_tokens"], usage["total_tokens"])
    return usage if usage["total_tokens"] > 0 else {}


def _normalize_usage_row(row: dict[str, Any]) -> dict[str, int]:
    cleaned = {key: _clean_int(row.get(key)) for key in _USAGE_KEYS}
    if cleaned["total_tokens"] <= 0:
        cleaned["total_tokens"] = cleaned["prompt_tokens"] + cleaned["completion_tokens"]
    if cleaned["provider_tokens"] <= 0 and cleaned["estimated_tokens"] <= 0:
        cleaned["provider_tokens"] = cleaned["total_tokens"]
    requests = {key: _clean_int(row.get(key)) for key in _REQUEST_KEYS}
    if (
        requests["requests"] > 0
        and requests["provider_requests"] <= 0
        and requests["estimated_requests"] <= 0
    ):
        if cleaned["estimated_tokens"] > 0 and cleaned["provider_tokens"] <= 0:
            requests["estimated_requests"] = requests["requests"]
        else:
            requests["provider_requests"] = requests["requests"]
    return {**cleaned, **requests}


def _normalize_sources(raw: Any, fallback: dict[str, int]) -> dict[str, dict[str, int]]:
    sources: dict[str, dict[str, int]] = {}
    if isinstance(raw, dict):
        for source, row in raw.items():
            if not isinstance(row, dict):
                continue
            normalized = _normalize_usage_row(row)
            if normalized["total_tokens"] <= 0 and normalized["requests"] <= 0:
                continue
            source_key = _clean_source(str(source))
            current = sources.get(source_key)
            if current is None:
                sources[source_key] = normalized
            else:
                for key in (*_USAGE_KEYS, *_REQUEST_KEYS):
                    current[key] = _clean_int(current.get(key)) + normalized[key]
    if not sources and (fallback["total_tokens"] > 0 or fallback["requests"] > 0):
        sources["user"] = {key: fallback[key] for key in (*_USAGE_KEYS, *_REQUEST_KEYS)}
    return sources


def normalize_token_usage_state(raw: Any) -> dict[str, Any]:
    state = default_token_usage_state()
    if not isinstance(raw, dict):
        return state
    days_raw = raw.get("days")
    if not isinstance(days_raw, dict):
        return state

    days: dict[str, dict[str, Any]] = {}
    for date, row in sorted(days_raw.items())[-_MAX_DAYS_RETAINED:]:
        if not isinstance(date, str) or len(date) != 10 or not isinstance(row, dict):
            continue
        normalized = _normalize_usage_row(row)
        if normalized["total_tokens"] <= 0 and normalized["requests"] <= 0:
            continue
        days[date] = {
            "date": date,
            **normalized,
            "sources": _normalize_sources(row.get("sources"), normalized),
        }

    state["days"] = days
    updated_at = raw.get("updated_at")
    state["updated_at"] = updated_at if isinstance(updated_at, str) else None
    return state


def read_token_usage_state() -> dict[str, Any]:
    path = token_usage_state_path()
    if not path.is_file():
        return default_token_usage_state()
    try:
        if path.stat().st_size > _MAX_STATE_FILE_BYTES:
            logger.warning("token usage state too large, ignoring: {}", path)
            return default_token_usage_state()
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("read token usage state failed {}: {}", path, e)
        return default_token_usage_state()
    return normalize_token_usage_state(raw)


def write_token_usage_state(raw: dict[str, Any]) -> dict[str, Any]:
    state = normalize_token_usage_state(raw)
    state["updated_at"] = _utc_now_iso()
    encoded = json.dumps(
        state,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _MAX_STATE_FILE_BYTES:
        raise ValueError("token usage state is too large")

    path = token_usage_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "wb") as f:
        f.write(encoded)
        f.write(b"\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return state
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return state


def record_token_usage(
    usage: dict[str, Any] | None,
    *,
    source: str = "user",
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = _normalize_usage(usage)
    if not normalized:
        return read_token_usage_state()

    with _WRITE_LOCK:
        state = read_token_usage_state()
        day = _local_day(now, timezone_name=timezone_name)
        row = dict(state["days"].get(day) or {"date": day, "requests": 0})
        for key in _USAGE_KEYS:
            row[key] = _clean_int(row.get(key)) + normalized.get(key, 0)
        row["requests"] = _clean_int(row.get("requests")) + 1
        if normalized.get("estimated_tokens", 0) > 0 and normalized.get("provider_tokens", 0) <= 0:
            row["estimated_requests"] = _clean_int(row.get("estimated_requests")) + 1
        else:
            row["provider_requests"] = _clean_int(row.get("provider_requests")) + 1

        source_key = _clean_source(source)
        sources = dict(row.get("sources") or {})
        source_row = dict(sources.get(source_key) or {"requests": 0})
        for key in _USAGE_KEYS:
            source_row[key] = _clean_int(source_row.get(key)) + normalized.get(key, 0)
        source_row["requests"] = _clean_int(source_row.get("requests")) + 1
        if normalized.get("estimated_tokens", 0) > 0 and normalized.get("provider_tokens", 0) <= 0:
            source_row["estimated_requests"] = _clean_int(source_row.get("estimated_requests")) + 1
        else:
            source_row["provider_requests"] = _clean_int(source_row.get("provider_requests")) + 1
        sources[source_key] = source_row
        row["sources"] = sources

        state["days"][day] = row
        if len(state["days"]) > _MAX_DAYS_RETAINED:
            kept = dict(sorted(state["days"].items())[-_MAX_DAYS_RETAINED:])
            state["days"] = kept
        return write_token_usage_state(state)


def token_usage_payload(
    *,
    days: int = 371,
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    state = read_token_usage_state()
    today = datetime.fromisoformat(_local_day(now, timezone_name=timezone_name)).date()
    start = today - timedelta(days=max(1, days) - 1)
    day_rows = [
        row
        for date, row in sorted(state["days"].items())
        if start.isoformat() <= date <= today.isoformat()
    ]
    last_30_start = today - timedelta(days=29)
    last_30 = [
        row
        for date, row in state["days"].items()
        if last_30_start.isoformat() <= date <= today.isoformat()
    ]
    last_365_start = today - timedelta(days=364)
    last_365 = [
        row
        for date, row in state["days"].items()
        if last_365_start.isoformat() <= date <= today.isoformat()
    ]
    active_dates = {
        datetime.fromisoformat(date).date()
        for date, row in state["days"].items()
        if _clean_int(row.get("total_tokens")) > 0
    }
    current_streak = 0
    cursor = today
    while cursor in active_dates:
        current_streak += 1
        cursor -= timedelta(days=1)

    longest_streak = 0
    running_streak = 0
    for cursor in sorted(active_dates):
        if cursor - timedelta(days=1) in active_dates:
            running_streak += 1
        else:
            running_streak = 1
        longest_streak = max(longest_streak, running_streak)

    all_rows = list(state["days"].values())
    return {
        "days": day_rows,
        "total_tokens": sum(_clean_int(row.get("total_tokens")) for row in all_rows),
        "total_tokens_30d": sum(_clean_int(row.get("total_tokens")) for row in last_30),
        "total_tokens_365d": sum(_clean_int(row.get("total_tokens")) for row in last_365),
        "peak_day_tokens": max([_clean_int(row.get("total_tokens")) for row in all_rows] or [0]),
        "current_streak_days": current_streak,
        "longest_streak_days": longest_streak,
        "active_days_30d": sum(1 for row in last_30 if _clean_int(row.get("total_tokens")) > 0),
        "requests_30d": sum(_clean_int(row.get("requests")) for row in last_30),
        "updated_at": state.get("updated_at"),
    }


class TokenUsageHook(AgentHook):
    """Persist provider-reported token usage without coupling it to chat messages."""

    def __init__(self, *, timezone_name: str | None = None) -> None:
        super().__init__()
        self._timezone_name = timezone_name

    def include_ephemeral(self) -> bool:
        return True

    async def after_iteration(self, context: AgentHookContext) -> None:
        try:
            record_token_usage(
                context.usage,
                source=context.usage_source,
                timezone_name=self._timezone_name,
            )
        except Exception:
            logger.exception("failed to record token usage")
