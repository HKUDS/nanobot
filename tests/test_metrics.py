from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.metrics import (
    LLM_CALLS_TOTAL,
    REQUEST_DURATION_SUM_MS,
    REQUESTS_FAILED,
    REQUESTS_TOTAL,
    TOKENS_COMPLETION_TOTAL,
    TOKENS_PROMPT_TOTAL,
    TOOL_CALLS_TOTAL,
    MetricsCollector,
    role_invocations_key,
    role_tool_calls_key,
)


def test_metrics_record_set_and_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "metrics.json"
    collector = MetricsCollector(path, defaults={"seed": 1})

    collector.record("a")
    collector.record("a", 2)
    collector.record_many({"b": 3, "c": 1})
    collector.set_fields({"s": "x"})
    collector.set_max("mx", 5)
    collector.set_max("mx", 4)

    snap = collector.snapshot()
    assert snap["seed"] == 1
    assert snap["a"] == 3
    assert snap["b"] == 3
    assert snap["c"] == 1
    assert snap["s"] == "x"
    assert snap["mx"] == 5
    assert collector.get("missing", 9) == 9


@pytest.mark.asyncio
async def test_metrics_flush_and_close(tmp_path: Path) -> None:
    path = tmp_path / "metrics.json"
    collector = MetricsCollector(path)
    collector.record("x", 2)
    await collector.flush()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["x"] == 2
    assert "last_updated" in data

    await collector.close()


@pytest.mark.asyncio
async def test_metrics_start_flush_loop_and_close(tmp_path: Path) -> None:
    path = tmp_path / "metrics_loop.json"
    collector = MetricsCollector(path, flush_interval_s=0.01)
    collector.record("loop", 1)
    collector.start()

    # Allow the background loop to run at least once.
    await pytest.importorskip("asyncio").sleep(0.03)
    await collector.close()
    assert path.exists()


def test_metrics_load_invalid_json_and_flush_sync(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not-json", encoding="utf-8")

    collector = MetricsCollector(path)
    collector.record("k", 1)
    collector.flush_sync()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["k"] == 1
    assert "last_updated" in data


def test_metric_key_helpers() -> None:
    assert role_invocations_key("pm") == "role_invocations:pm"
    assert role_tool_calls_key("code") == "role_tool_calls:code"


def test_record_request(tmp_path: Path) -> None:
    path = tmp_path / "metrics.json"
    collector = MetricsCollector(path)

    collector.record_request(duration_ms=150.5, llm_calls=2, tool_calls=3, failed=False)
    collector.record_request(
        duration_ms=80.0, tokens_prompt=500, tokens_completion=200, failed=True
    )

    snap = collector.snapshot()
    assert snap[REQUESTS_TOTAL] == 2
    assert snap[REQUESTS_FAILED] == 1
    assert snap[REQUEST_DURATION_SUM_MS] == 230
    assert snap[LLM_CALLS_TOTAL] == 2
    assert snap[TOOL_CALLS_TOTAL] == 3
    assert snap[TOKENS_PROMPT_TOTAL] == 500
    assert snap[TOKENS_COMPLETION_TOTAL] == 200
