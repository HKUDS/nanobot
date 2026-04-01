"""Tests for OTelHook metrics and traces."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.observability.hook import OTelHook
from nanobot.providers.base import ToolCallRequest


def _make_context(
    iteration=0,
    tool_calls=None,
    tool_events=None,
    usage=None,
    stop_reason=None,
    final_content=None,
    error=None,
):
    return AgentHookContext(
        iteration=iteration,
        messages=[],
        tool_calls=tool_calls or [],
        tool_events=tool_events or [],
        usage=usage or {},
        stop_reason=stop_reason,
        final_content=final_content,
        error=error,
    )


@pytest.fixture
def mock_meter_and_tracer():
    """Patch get_meter/get_tracer to return mock objects."""
    mock_counter = MagicMock()
    mock_histogram = MagicMock()
    mock_meter = MagicMock()
    mock_meter.create_counter.return_value = mock_counter
    mock_meter.create_histogram.return_value = mock_histogram

    mock_span = MagicMock()
    mock_tracer = MagicMock()
    mock_tracer.start_span.return_value = mock_span

    with (
        patch("nanobot.observability.otel.get_meter", return_value=mock_meter),
        patch("nanobot.observability.otel.get_tracer", return_value=mock_tracer),
    ):
        yield mock_meter, mock_tracer, mock_counter, mock_histogram, mock_span


@pytest.mark.asyncio
async def test_before_iteration_starts_span(mock_meter_and_tracer):
    mock_meter, mock_tracer, _, _, mock_span = mock_meter_and_tracer

    hook = OTelHook(channel="telegram", chat_id="123")
    ctx = _make_context(iteration=0)

    await hook.before_iteration(ctx)

    mock_tracer.start_span.assert_called_once_with(
        "agent.iteration",
        attributes={"channel": "telegram", "chat_id": "123", "iteration": 0},
    )
    mock_span.__enter__.assert_called_once()


@pytest.mark.asyncio
async def test_after_iteration_records_tool_metrics(mock_meter_and_tracer):
    mock_meter, mock_tracer, mock_counter, mock_histogram, mock_span = mock_meter_and_tracer

    hook = OTelHook(channel="telegram", chat_id="123")
    ctx = _make_context(
        iteration=0,
        tool_events=[
            {"name": "exec", "status": "ok", "detail": "output"},
            {"name": "read_file", "status": "error", "detail": "not found"},
        ],
        stop_reason="completed",
    )
    hook._current_span = mock_span

    await hook.after_iteration(ctx)

    # 2 tool calls + 1 iteration = 3 total counter.add calls
    assert mock_counter.add.call_count == 3

    call1_kwargs = mock_counter.add.call_args_list[0].kwargs
    assert call1_kwargs["attributes"]["tool_name"] == "exec"
    assert call1_kwargs["attributes"]["status"] == "ok"

    call2_kwargs = mock_counter.add.call_args_list[1].kwargs
    assert call2_kwargs["attributes"]["tool_name"] == "read_file"
    assert call2_kwargs["attributes"]["status"] == "error"

    # Third call is the iteration counter (no tool_name attr)
    call3_kwargs = mock_counter.add.call_args_list[2].kwargs
    assert "stop_reason" in call3_kwargs["attributes"]

    assert mock_histogram.record.call_count >= 1

    counter_names = [call.args[0] for call in mock_meter.create_counter.call_args_list]
    assert "nanobot.agent.iterations" in counter_names
    assert "nanobot.tool.calls" in counter_names

    mock_span.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_after_iteration_ends_span(mock_meter_and_tracer):
    mock_meter, mock_tracer, _, _, mock_span = mock_meter_and_tracer

    hook = OTelHook(channel="cli", chat_id="direct")
    hook._current_span = mock_span
    ctx = _make_context(stop_reason="completed")

    await hook.after_iteration(ctx)

    mock_span.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_hook_survives_exceptions(mock_meter_and_tracer):
    """Hook methods should never raise, even if OTEL calls fail."""
    mock_meter, mock_tracer, mock_counter, _, mock_span = mock_meter_and_tracer
    mock_counter.add.side_effect = RuntimeError("OTEL export failed")

    hook = OTelHook(channel="telegram", chat_id="123")
    hook._current_span = mock_span
    ctx = _make_context(tool_events=[{"name": "exec", "status": "ok", "detail": "ok"}])

    # Should NOT raise
    await hook.after_iteration(ctx)


def test_record_skill_loaded(mock_meter_and_tracer):
    mock_meter, mock_tracer, mock_counter, _, _ = mock_meter_and_tracer

    hook = OTelHook(channel="telegram", chat_id="123")
    hook.record_skill("firefly_tools")

    assert mock_counter.add.call_count >= 1
