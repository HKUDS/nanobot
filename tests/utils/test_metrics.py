"""Tests for the turn latency metrics module (#3257)."""
from __future__ import annotations

import json
import time

import pytest
from loguru import logger

from nanobot.utils.metrics import (
    TurnMetrics,
    activate,
    deactivate,
    llm_timer,
    mark_first_token,
    stage_timer,
    tool_timer,
)


@pytest.fixture
def captured_metric_logs():
    """Capture records tagged metric='turn' emitted during the test.

    Other tests call ``logger.disable('nanobot')`` (see ``cli.commands.agent``)
    and may leave loguru silenced for nanobot-namespaced modules. Re-enable
    here so metric emissions from ``nanobot.utils.metrics`` are observable.
    """
    logger.enable("nanobot")
    captured: list[dict] = []

    def sink(message):
        record = message.record
        if record["extra"].get("metric") == "turn":
            captured.append({"message": record["message"], "extra": dict(record["extra"])})

    sink_id = logger.add(sink, level="INFO")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


def test_turn_metrics_disabled_emits_nothing(captured_metric_logs):
    metrics, token = activate(channel="telegram", enabled=False)
    try:
        with stage_timer("stt"):
            time.sleep(0.001)
        metrics.flush()
    finally:
        deactivate(token)

    assert captured_metric_logs == []


def test_turn_metrics_enabled_emits_single_json_line(captured_metric_logs):
    metrics, token = activate(channel="telegram", enabled=True)
    try:
        with stage_timer("stt"):
            time.sleep(0.001)
        metrics.flush()
    finally:
        deactivate(token)

    assert len(captured_metric_logs) == 1
    payload = json.loads(captured_metric_logs[0]["message"])
    assert payload["channel"] == "telegram"
    assert "turn_id" in payload
    assert "stt" in payload["timings_ms"]
    assert payload["timings_ms"]["llm_ttft"] is None
    assert payload["timings_ms"]["tool_calls"] == []


def test_stage_timer_records_duration():
    metrics, token = activate(channel="cli", enabled=True)
    try:
        with stage_timer("context_build"):
            time.sleep(0.005)
    finally:
        deactivate(token)

    assert "context_build" in metrics.stages
    assert metrics.stages["context_build"] >= 5


def test_tool_timings_accumulate():
    metrics, token = activate(channel="cli", enabled=True)
    try:
        with tool_timer("memory_search"):
            time.sleep(0.001)
        with tool_timer("web_fetch"):
            time.sleep(0.001)
    finally:
        deactivate(token)

    names = [t.name for t in metrics.tool_timings]
    assert names == ["memory_search", "web_fetch"]
    assert all(t.duration_ms >= 1 for t in metrics.tool_timings)


def test_turn_id_unique_per_turn():
    m1, t1 = activate(channel="cli", enabled=True)
    deactivate(t1)
    m2, t2 = activate(channel="cli", enabled=True)
    deactivate(t2)

    assert m1.turn_id != m2.turn_id


def test_llm_ttft_recorded_only_when_streaming(captured_metric_logs):
    metrics, token = activate(channel="telegram", enabled=True)
    try:
        with llm_timer():
            time.sleep(0.002)
            mark_first_token()
            time.sleep(0.003)
        metrics.flush()
    finally:
        deactivate(token)

    payload = json.loads(captured_metric_logs[0]["message"])
    assert payload["timings_ms"]["llm_ttft"] is not None
    assert payload["timings_ms"]["llm_ttft"] >= 2
    assert payload["timings_ms"]["llm_total"] >= 5


def test_llm_ttft_null_when_no_first_token_marked(captured_metric_logs):
    metrics, token = activate(channel="telegram", enabled=True)
    try:
        with llm_timer():
            time.sleep(0.002)
        metrics.flush()
    finally:
        deactivate(token)

    payload = json.loads(captured_metric_logs[0]["message"])
    assert payload["timings_ms"]["llm_ttft"] is None
    assert payload["timings_ms"]["llm_total"] >= 2


def test_total_measures_activate_to_flush(captured_metric_logs):
    metrics, token = activate(channel="telegram", enabled=True)
    try:
        time.sleep(0.010)
        metrics.flush()
    finally:
        deactivate(token)

    payload = json.loads(captured_metric_logs[0]["message"])
    assert payload["timings_ms"]["total"] >= 10


def test_stage_timer_noop_without_active_metrics():
    assert TurnMetrics.current() is None
    with stage_timer("stt"):
        pass
    with tool_timer("x"):
        pass
    mark_first_token()
    assert TurnMetrics.current() is None
