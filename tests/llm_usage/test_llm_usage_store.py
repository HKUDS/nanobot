from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from nanobot.llm_usage.context import LLMUsageSource
from nanobot.llm_usage.models import LLMCallRecord
from nanobot.llm_usage.store import SCHEMA_VERSION, LLMUsageStore
from nanobot.providers.base import LLMUsage


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def _call(
    started_at: str,
    *,
    provider: str = "openai",
    model: str = "gpt-5",
    source: LLMUsageSource = "user",
    usage: LLMUsage | None = None,
    finish_reason: str = "stop",
    error_kind: str | None = None,
) -> LLMCallRecord:
    return LLMCallRecord(
        started_at_ms=_timestamp(started_at),
        duration_ms=250,
        provider=provider,
        model=model,
        source=source,
        stream=True,
        finish_reason=finish_reason,
        usage=usage,
        error_status_code=429 if finish_reason == "error" else None,
        error_kind=error_kind or ("rate_limit" if finish_reason == "error" else None),
    )


def test_store_keeps_only_content_free_call_metadata(tmp_path: Path) -> None:
    path = tmp_path / "llm_usage.sqlite3"
    store = LLMUsageStore(path)
    store.record(
        _call(
            "2026-06-03T00:00:00+00:00",
            usage=LLMUsage.reported(input_tokens=100, output_tokens=20),
        )
    )

    row = store.recent_calls(limit=1)[0]
    assert row["provider"] == "openai"
    assert row["model"] == "gpt-5"
    assert row["total_tokens"] == 120
    assert not {
        "messages",
        "prompt",
        "content",
        "response",
        "tool_calls",
        "error_type",
        "error_code",
    } & set(row)

    with sqlite3.connect(path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert version == SCHEMA_VERSION
    assert str(mode).lower() == "wal"


def test_usage_payload_aggregates_cache_coverage_sources_and_failures(tmp_path: Path) -> None:
    store = LLMUsageStore(tmp_path / "llm_usage.sqlite3")
    store.record_many(
        [
            _call(
                "2026-06-02T23:30:00+00:00",
                usage=LLMUsage.reported(
                    input_tokens=100,
                    output_tokens=20,
                    cache_read_tokens=40,
                    cache_write_tokens=10,
                ),
            ),
            _call(
                "2026-06-03T01:00:00+00:00",
                source="api",
                usage=LLMUsage.reported(input_tokens=50, output_tokens=5).with_timing(
                    generation_ms=2500,
                    ttft_ms=200,
                ),
            ),
            _call(
                "2026-06-03T02:00:00+00:00",
                provider="anthropic",
                model="claude-sonnet-4",
                source="dream",
                usage=LLMUsage.estimated(input_tokens=30, output_tokens=10),
            ),
            _call(
                "2026-06-03T03:00:00+00:00",
                provider="anthropic",
                model="claude-sonnet-4",
                source="system",
                finish_reason="error",
            ),
        ]
    )

    payload = store.usage_payload(
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 6, 3, 8, tzinfo=timezone.utc),
    )

    assert payload["total_tokens_30d"] == 215
    assert payload["reported_tokens_30d"] == 175
    assert payload["estimated_tokens_30d"] == 40
    assert payload["requests_30d"] == 4
    assert payload["failed_requests_30d"] == 1
    assert payload["cache_read_tokens_30d"] == 40
    assert payload["cache_read_observed_input_tokens_30d"] == 100
    assert payload["cache_read_rate_30d"] == 0.4
    assert payload["model_days_30d"] == [
        {
            "date": "2026-06-03",
            "provider": "anthropic",
            "model": "claude-sonnet-4",
            "total_tokens": 40,
            "measured_output_tokens": 0,
            "generation_ms": 0,
            "ttft_ms": 0,
            "timed_requests": 0,
            "cache_read_tokens": 0,
            "cache_read_observed_input_tokens": 0,
        },
        {
            "date": "2026-06-03",
            "provider": "openai",
            "model": "gpt-5",
            "total_tokens": 175,
            "measured_output_tokens": 5,
            "generation_ms": 2500,
            "ttft_ms": 200,
            "timed_requests": 1,
            "cache_read_tokens": 40,
            "cache_read_observed_input_tokens": 100,
        },
    ]

    day = payload["days"][0]
    assert day["date"] == "2026-06-03"
    assert day["requests"] == 4
    assert day["reported_requests"] == 2
    assert day["estimated_requests"] == 1
    assert day["cache_miss_tokens"] == 50
    assert day["cache_unknown_tokens"] == 80
    assert day["sources"]["api"]["cache_read_observed_input_tokens"] == 0
    assert day["sources"]["user"]["cache_read_observed_input_tokens"] == 100
    assert {(row["provider"], row["model"]) for row in payload["providers_30d"]} == {
        ("openai", "gpt-5"),
        ("anthropic", "claude-sonnet-4"),
    }


@pytest.mark.parametrize("with_read_call", [False, True], ids=["write-only", "mixed-observation"])
def test_usage_payload_partitions_cache_tokens_before_aggregation(
    tmp_path: Path, with_read_call: bool,
) -> None:
    store = LLMUsageStore(tmp_path / "llm_usage.sqlite3")
    store.record(_call(
        "2026-06-03T00:00:00+00:00",
        usage=LLMUsage.reported(
            input_tokens=100, output_tokens=20, cache_write_tokens=100,
        ),
    ))
    if with_read_call:
        store.record(_call(
            "2026-06-03T00:01:00+00:00",
            usage=LLMUsage.reported(
                input_tokens=100, output_tokens=20,
                cache_read_tokens=100, cache_write_tokens=0,
            ),
        ))

    payload = store.usage_payload(now=datetime(2026, 6, 3, 12, tzinfo=timezone.utc))
    day = payload["days"][0]
    assert day["cache_write_tokens"] == 100
    assert day["cache_read_tokens"] == (100 if with_read_call else 0)
    assert day["cache_miss_tokens"] == 0
    assert day["cache_unknown_tokens"] == 0
    assert sum(day[key] for key in (
        "cache_read_tokens", "cache_write_tokens", "cache_miss_tokens",
        "cache_unknown_tokens", "output_tokens",
    )) == day["total_tokens"]


def test_usage_payload_preserves_zero_cache_observation(tmp_path: Path) -> None:
    store = LLMUsageStore(tmp_path / "llm_usage.sqlite3")
    store.record(
        _call(
            "2026-06-03T00:00:00+00:00",
            usage=LLMUsage.reported(
                input_tokens=80,
                output_tokens=5,
                cache_read_tokens=0,
            ),
        )
    )

    payload = store.usage_payload(
        now=datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
    )

    assert payload["cache_read_tokens_30d"] == 0
    assert payload["cache_read_observed_input_tokens_30d"] == 80
    assert payload["cache_read_rate_30d"] == 0.0


def test_recent_calls_is_bounded(tmp_path: Path) -> None:
    store = LLMUsageStore(tmp_path / "llm_usage.sqlite3")
    call = _call(
        "2026-06-03T00:00:00+00:00",
        usage=LLMUsage.reported(input_tokens=1, output_tokens=1),
    )
    store.record_many(call for _ in range(1_005))

    assert len(store.recent_calls(limit=10_000)) == 1_000


def test_cancelled_calls_are_failures_and_error_kind_is_coarse(tmp_path: Path) -> None:
    store = LLMUsageStore(tmp_path / "llm_usage.sqlite3")
    call = _call(
        "2026-06-03T00:00:00+00:00",
        finish_reason="cancelled",
        error_kind="provider payload: secret text",
    )
    store.record(call)

    payload = store.usage_payload(
        now=datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
    )

    assert payload["failed_requests_30d"] == 1
    assert store.recent_calls(limit=1)[0]["error_kind"] == "other"


def test_usage_payload_cache_is_isolated_and_invalidated_on_write(tmp_path: Path) -> None:
    store = LLMUsageStore(tmp_path / "llm_usage.sqlite3")
    first_call = _call(
        "2026-06-03T00:00:00+00:00",
        usage=LLMUsage.reported(input_tokens=10, output_tokens=2),
    )
    store.record(first_call)
    kwargs = {"now": datetime(2026, 6, 3, 12, tzinfo=timezone.utc)}

    first = store.usage_payload(**kwargs)
    first["days"].clear()
    cached = store.usage_payload(**kwargs)
    assert cached["total_tokens"] == 12
    assert cached["days"]

    store.record(first_call)
    refreshed = store.usage_payload(**kwargs)
    assert refreshed["total_tokens"] == 24


def test_usage_payload_cache_is_invalidated_when_connection_pid_changes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "llm_usage.sqlite3"
    store = LLMUsageStore(path)
    other_store = LLMUsageStore(path)
    first_call = _call(
        "2026-06-03T00:00:00+00:00",
        usage=LLMUsage.reported(input_tokens=1, output_tokens=0),
    )
    kwargs = {"now": datetime(2026, 6, 3, 12, tzinfo=timezone.utc)}
    store.record(first_call)
    assert store.usage_payload(**kwargs)["total_tokens"] == 1

    other_store.record(_call(
        "2026-06-03T00:01:00+00:00",
        usage=LLMUsage.reported(input_tokens=2, output_tokens=0),
    ))
    store._connection_pid = -1

    assert store.usage_payload(**kwargs)["total_tokens"] == 3
    other_store.close()


def test_usage_query_does_not_hold_writer_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LLMUsageStore(tmp_path / "llm_usage.sqlite3")
    call = _call(
        "2026-06-03T00:00:00+00:00",
        usage=LLMUsage.reported(input_tokens=10, output_tokens=2),
    )
    store.record(call)
    query_started = threading.Event()
    release_query = threading.Event()
    record_finished = threading.Event()
    original_daily_rows = store._daily_rows

    def slow_daily_rows(**kwargs: Any):
        query_started.set()
        assert release_query.wait(timeout=2)
        return original_daily_rows(**kwargs)

    def record_call() -> None:
        store.record(call)
        record_finished.set()

    monkeypatch.setattr(store, "_daily_rows", slow_daily_rows)
    query_thread = threading.Thread(target=lambda: store.usage_payload(
        now=datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
    ))
    record_thread = threading.Thread(target=record_call)

    query_thread.start()
    assert query_started.wait(timeout=2)
    record_thread.start()
    try:
        assert record_finished.wait(timeout=0.5)
    finally:
        release_query.set()
        query_thread.join(timeout=2)
        record_thread.join(timeout=2)

    assert not query_thread.is_alive()
    assert not record_thread.is_alive()


def test_dashboard_views_are_bounded_and_cached_independently(tmp_path, monkeypatch) -> None:
    path = tmp_path / "llm_usage.sqlite3"
    store = LLMUsageStore(path)
    store.record_many([
        _call("2026-05-04T12:00:00+00:00", usage=LLMUsage.reported(input_tokens=100, output_tokens=0)),
        _call("2026-06-03T12:00:00+00:00", usage=LLMUsage.reported(input_tokens=10, output_tokens=2)),
    ])
    queries = []
    daily_rows = store._daily_rows

    def count_daily_rows(**kwargs):
        queries.append((kwargs["start_ms"], kwargs["end_ms"]))
        return daily_rows(**kwargs)

    monkeypatch.setattr(store, "_daily_rows", count_daily_rows)
    kwargs = {"now": datetime(2026, 6, 3, 23, tzinfo=timezone.utc), "timezone_name": "UTC"}
    overview = store.usage_payload(view="overview", **kwargs)
    models = store.usage_payload(view="models", **kwargs)
    assert overview["range_start"] == "2026-05-05"
    assert overview["range_end"] == "2026-06-03"
    assert sum(day["total_tokens"] for day in overview["days"]) == 12
    assert set(overview) == {"days", "range_start", "range_end", "revision"}
    assert models["days"] == overview["days"]
    assert models["providers_30d"][0]["total_tokens"] == 12
    assert models["model_days_30d"][0]["total_tokens"] == 12
    assert models["revision"] != overview["revision"]
    assert store.usage_payload(view="overview", **kwargs) == overview
    assert store.usage_payload(view="models", **kwargs) == models
    assert queries == [(_timestamp("2026-05-05T00:00:00+00:00"),
                        _timestamp("2026-06-04T00:00:00+00:00"))] * 2

    # Another gateway writer must invalidate both projections, not just the last read view.
    other = LLMUsageStore(path)
    other.record(_call("2026-06-03T13:00:00+00:00", usage=LLMUsage.reported(input_tokens=5, output_tokens=0)))
    other.close()
    refreshed = store.usage_payload(view="overview", **kwargs)
    assert sum(day["total_tokens"] for day in refreshed["days"]) == 17
    assert refreshed["revision"] != overview["revision"]
    assert store.usage_payload(view="models", **kwargs)["providers_30d"][0]["total_tokens"] == 17

    next_day = store.usage_payload(view="overview", timezone_name="UTC",
                                   now=datetime(2026, 6, 4, 1, tzinfo=timezone.utc))
    assert next_day["days"] == refreshed["days"]
    assert next_day["range_end"] == "2026-06-04"
    assert next_day["revision"] != refreshed["revision"]
