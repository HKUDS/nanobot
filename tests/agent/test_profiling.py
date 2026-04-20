"""Tests for the optional ProfilingHook."""

from unittest.mock import patch

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.profiling import ProfilingHook, is_profiling_enabled


@pytest.fixture()
def hook():
    return ProfilingHook()


@pytest.fixture()
def ctx():
    return AgentHookContext(iteration=1, messages=[])


async def test_before_iteration_records_start_time(hook, ctx):
    assert hook._iter_t0 is None
    await hook.before_iteration(ctx)
    assert hook._iter_t0 is not None and hook._iter_t0 > 0.0


async def test_after_iteration_logs_elapsed_time(hook, ctx):
    """after_iteration must log the elapsed ms derived from perf_counter."""
    with patch("nanobot.agent.profiling.logger") as mock_logger:
        with patch("nanobot.agent.profiling.time.perf_counter", side_effect=[100.0, 100.05]):
            await hook.before_iteration(ctx)
            await hook.after_iteration(ctx)
    # perf_counter delta is 0.05s → 50ms. The hook formats with "{:.0f}ms",
    # so the integer 50 must appear in the log args.
    mock_logger.debug.assert_called_once()
    args = mock_logger.debug.call_args.args
    assert 50 == round(args[2])  # elapsed_ms positional arg


async def test_after_iteration_without_before_is_safe(hook, ctx):
    """Calling after_iteration before before_iteration must not crash."""
    await hook.after_iteration(ctx)  # _iter_t0 is None — should be a no-op


async def test_after_iteration_includes_tool_names(hook, ctx):
    """Tool names from context are included in the log output."""
    from nanobot.providers.base import ToolCallRequest

    ctx.tool_calls = [
        ToolCallRequest(id="t1", name="read_file", arguments="{}"),
        ToolCallRequest(id="t2", name="exec", arguments="{}"),
    ]
    with patch("nanobot.agent.profiling.logger") as mock_logger:
        with patch("nanobot.agent.profiling.time.perf_counter", side_effect=[1.0, 1.025]):
            await hook.before_iteration(ctx)
            await hook.after_iteration(ctx)
        call_args = mock_logger.debug.call_args
        assert "read_file" in str(call_args)
        assert "exec" in str(call_args)


def test_profiling_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NANOBOT_PROFILING", raising=False)
    assert is_profiling_enabled() is False


def test_profiling_enabled_with_env(monkeypatch):
    monkeypatch.setenv("NANOBOT_PROFILING", "1")
    assert is_profiling_enabled() is True


def test_profiling_enabled_with_true_string(monkeypatch):
    monkeypatch.setenv("NANOBOT_PROFILING", "true")
    assert is_profiling_enabled() is True
