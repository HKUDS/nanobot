"""Tests for caller-controlled continuation in AgentRunner.

When the continuation callback returns a message, the runner must not exit with
stop_reason="completed" after a plain-text final response. Instead it injects
that message and keeps looping, similar to a mid-turn injection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def _continue_goal() -> str:
    return "Continue working toward the active sustained goal."


@pytest.mark.asyncio
async def test_runner_exits_normally_without_continuation_callback():
    """Without a continuation request, final text completes the run."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="all done", tool_calls=[], usage=None,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "completed"
    assert result.final_content == "all done"


@pytest.mark.asyncio
async def test_runner_exits_normally_when_continuation_callback_returns_none():
    """A callback returning None leaves the final response terminal."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="all done", tool_calls=[], usage=None,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        continuation_callback=lambda: None,
    ))

    assert result.stop_reason == "completed"
    assert result.final_content == "all done"


@pytest.mark.asyncio
async def test_runner_continues_when_callback_returns_message():
    """A callback result after final text is injected for the next iteration.

    We set max_iterations=3 and let the provider return final text every time.
    Without the fix this would exit on the first iteration with stop_reason
    "completed". With the fix the runner is forced to continue until
    max_iterations is hit.
    """
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage=None,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        continuation_callback=_continue_goal,
    ))

    # Because the callback keeps returning a message, the runner should never
    # naturally complete. It loops until max_iterations is exhausted.
    assert result.stop_reason == "max_iterations"
    # The injected continuation message should be present in the message list.
    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    assert any("active sustained goal" in str(m.get("content", "")) for m in user_msgs)


@pytest.mark.asyncio
async def test_runner_respects_max_iterations_with_continuation():
    """A continuation request after one iteration still hits max_iterations."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage=None,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        continuation_callback=_continue_goal,
    ))

    assert result.stop_reason == "max_iterations"


@pytest.mark.asyncio
async def test_runner_continuation_not_limited_by_injection_cycle_cap():
    """Caller-requested continuation is governed by max_iterations."""
    from nanobot.agent.runner import _MAX_INJECTION_CYCLES, AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage=None,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    max_iterations = _MAX_INJECTION_CYCLES + 3

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=max_iterations,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        continuation_callback=_continue_goal,
        finalize_on_max_iterations=False,
    ))

    assert result.stop_reason == "max_iterations"
    assert provider.chat_with_retry.await_count == max_iterations


@pytest.mark.asyncio
async def test_runner_does_not_continue_on_error():
    """An LLM error remains terminal even when continuation is available."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content=None, tool_calls=[], usage=None,
        finish_reason="error",
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        continuation_callback=_continue_goal,
    ))

    assert result.stop_reason == "error"


@pytest.mark.asyncio
async def test_runner_injects_continuation_callback_message():
    """The callback result becomes the injected user message."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage=None,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    custom_msg = "CUSTOM_CONTINUE_PLEASE"

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        continuation_callback=lambda: custom_msg,
    ))

    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    assert any(custom_msg in str(m.get("content", "")) for m in user_msgs)


@pytest.mark.asyncio
async def test_runner_resolves_continuation_callback_lazily():
    """The continuation text can depend on goal metadata created during the run."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage=None,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    calls = {"n": 0}

    def dynamic_msg() -> str:
        calls["n"] += 1
        return "Goal (active):\nWrite the article draft."

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        continuation_callback=dynamic_msg,
        finalize_on_max_iterations=False,
    ))

    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    assert calls["n"] == 1
    assert any("Write the article draft." in str(m.get("content", "")) for m in user_msgs)
