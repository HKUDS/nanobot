"""Tests for the SQLite LLM usage store."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
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


@pytest.mark.parametrize("window", [7, 30, 365, 400])
def test_range_details_reconcile_days_models_and_retained_coverage(tmp_path, window):
    store = LLMUsageStore(tmp_path / "usage.sqlite3")
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    for offset in (0, 1, 6, 7, 29, 30, 364, 365, 399):
        store.record(_call(
            (now - timedelta(days=offset)).isoformat(),
            usage=LLMUsage.reported(input_tokens=100, output_tokens=20, cache_read_tokens=40),
        ))
    # One primary failure and a successful backup are two physical calls, not one turn.
    store.record(_call(now.isoformat(), provider="primary", model="a", finish_reason="error"))
    store.record(_call(now.isoformat(), provider="backup", model="b",
                       usage=LLMUsage.estimated(input_tokens=30, output_tokens=10)))
    payload = store.usage_payload(now=now, timezone_name="UTC", detail_days=window)
    assert set(payload) == {"details"}  # Do not add the legacy, potentially large 30d series.
    details = payload["details"]
    assert details["start_date"] == (now - timedelta(days=window - 1)).date().isoformat()
    assert details["end_date"] == now.date().isoformat()
    assert len(details["days"]) == sum(offset < window for offset in (0, 1, 6, 7, 29, 30, 364, 365, 399))
    for metric, value in details["totals"].items():
        assert value == sum(day[metric] for day in details["days"])
        assert value == sum(model[metric] for model in details["models"]) + details["other_models"][metric]
    assert details["totals"]["failed_requests"] == 1
    assert details["totals"]["estimated_requests"] == 1
    assert details["totals"]["estimated_tokens"] == 40
    assert details["totals"]["requests"] - details["totals"]["reported_requests"] - details["totals"]["estimated_requests"] == 1
    assert details["active_days"] == len(details["days"])
    assert details["current_streak_days"] == 2
    assert details["coverage"]["retained_requests"] == 11
    assert details["coverage"]["first_call_at_ms"] == _timestamp((now - timedelta(days=399)).isoformat())
    assert "details" not in store.usage_payload(now=now, timezone_name="UTC")
    assert store.usage_payload(now=now, timezone_name="UTC", detail_days=window) == payload


def test_range_details_are_bounded_and_include_model_remainder(tmp_path):
    store = LLMUsageStore(tmp_path / "usage.sqlite3")
    now = datetime.now(timezone.utc)
    for index in range(60):
        store.record(_call(now.isoformat(), model=f"model-{index:02}",
                           usage=LLMUsage.reported(input_tokens=index + 1, output_tokens=0)))
    details = store.usage_payload(now=now, detail_days=400)["details"]
    assert len(details["models"]) == 50
    assert len(details["model_days"]) == 5
    assert details["other_models"]["requests"] == 10
    assert details["other_models"]["total_tokens"] == sum(range(1, 11))
    assert sum(row["total_tokens"] for row in details["model_days"]) == sum(range(56, 61))
    assert details["totals"]["cache_read_observed_input_tokens"] == 0
    assert details["coverage"]["max_days"] == 400
    assert details["coverage"]["max_requests"] == 100_000


def test_range_details_respect_local_midnight_dst_and_request_only_activity(tmp_path, monkeypatch):
    store = LLMUsageStore(tmp_path / "usage.sqlite3")
    # Fixed DST dates must remain testable even after the real retention cutoff advances.
    monkeypatch.setattr(store, "_prune_if_due", lambda _connection: None)
    store.record_many([
        _call("2026-03-07T04:59:59+00:00", usage=LLMUsage.reported(input_tokens=1, output_tokens=0)),
        _call("2026-03-07T05:00:00+00:00", usage=LLMUsage.reported(input_tokens=2, output_tokens=0)),
        _call("2026-03-08T06:59:59+00:00", usage=LLMUsage.reported(input_tokens=3, output_tokens=0)),
        _call("2026-03-08T07:00:00+00:00", usage=LLMUsage.reported(input_tokens=4, output_tokens=0)),
        _call("2026-03-09T03:59:59+00:00", usage=LLMUsage.reported(input_tokens=5, output_tokens=0)),
        _call("2026-03-09T04:00:00+00:00", finish_reason="error"),
        _call("2026-03-10T04:00:00+00:00", usage=LLMUsage.reported(input_tokens=999, output_tokens=0)),
    ])
    now = datetime.fromisoformat("2026-03-09T12:00:00+00:00")
    details = store.usage_payload(now=now, timezone_name="America/New_York", detail_days=3)["details"]
    assert [(row["date"], row["total_tokens"]) for row in details["days"]] == [
        ("2026-03-07", 2), ("2026-03-08", 12), ("2026-03-09", 0),
    ]
    assert details["totals"]["requests"] == 5
    assert details["active_days"] == details["current_streak_days"] == details["longest_streak_days"] == 3


def test_range_details_tied_series_have_matching_model_metadata(tmp_path):
    store = LLMUsageStore(tmp_path / "usage.sqlite3")
    now = datetime.now(timezone.utc)
    for index in reversed(range(60)):
        store.record(_call(now.isoformat(), model=f"model-{index:02}",
                           usage=LLMUsage.reported(input_tokens=1, output_tokens=0, cache_read_tokens=0)))
    details = store.usage_payload(now=now, detail_days=30)["details"]
    assert [row["model"] for row in details["model_days"]] == [f"model-{i:02}" for i in range(5)]
    models = {row["model"]: row for row in details["models"]}
    assert all(models[row["model"]]["cache_read_observed_input_tokens"] == 1 for row in details["model_days"])


def test_range_details_empty_cache_isolated_and_external_write_visible(tmp_path):
    path = tmp_path / "usage.sqlite3"
    store = LLMUsageStore(path)
    writer = LLMUsageStore(path)
    now = datetime.now(timezone.utc)
    empty = store.usage_payload(now=now, detail_days=7)["details"]
    assert empty["totals"]["requests"] == empty["active_days"] == 0
    assert empty["coverage"]["first_call_at_ms"] is None
    writer.record(_call((now - timedelta(days=10)).isoformat(),
                        usage=LLMUsage.reported(input_tokens=10, output_tokens=0, cache_read_tokens=0)))
    long = store.usage_payload(now=now, detail_days=30)["details"]
    assert long["totals"]["requests"] == 1
    assert long["totals"]["cache_read_observed_input_tokens"] == 10
    long["totals"]["requests"] = 999
    assert store.usage_payload(now=now, detail_days=30)["details"]["totals"]["requests"] == 1
    assert store.usage_payload(now=now, detail_days=7)["details"]["totals"]["requests"] == 0
    writer.record(_call(now.isoformat(), finish_reason="error"))
    assert store.usage_payload(now=now, detail_days=7)["details"]["totals"]["requests"] == 1


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
                usage=LLMUsage.reported(input_tokens=50, output_tokens=5),
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
        {"date": "2026-06-03", "provider": "anthropic", "model": "claude-sonnet-4", "total_tokens": 40},
        {"date": "2026-06-03", "provider": "openai", "model": "gpt-5", "total_tokens": 175},
    ]

    day = payload["days"][0]
    assert day["date"] == "2026-06-03"
    assert day["requests"] == 4
    assert day["reported_requests"] == 2
    assert day["estimated_requests"] == 1
    assert day["sources"]["api"]["cache_read_observed_input_tokens"] == 0
    assert day["sources"]["user"]["cache_read_observed_input_tokens"] == 100
    assert {(row["provider"], row["model"]) for row in payload["providers_30d"]} == {
        ("openai", "gpt-5"),
        ("anthropic", "claude-sonnet-4"),
    }


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
