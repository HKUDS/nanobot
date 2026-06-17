"""Tests for sustained-goal continuation in AgentRunner.

When a goal_active_predicate returns True, the runner must not exit with
stop_reason="completed" after a plain-text final response. Instead it should
inject a continuation message and keep looping (similar to mid-turn injection).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_exits_normally_without_predicate():
    """Baseline: no predicate, runner exits with completed on final text."""
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="all done", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "completed"
    assert result.final_content == "all done"


@pytest.mark.asyncio
async def test_runner_exits_normally_with_inactive_goal():
    """Predicate returns False, runner should exit normally."""
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="all done", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        goal_active_predicate=lambda: False,
    ))

    assert result.stop_reason == "completed"
    assert result.final_content == "all done"


@pytest.mark.asyncio
async def test_runner_forces_continue_when_goal_active():
    """Predicate returns True on final text → runner injects continuation and loops.

    We set max_iterations=3 and let the provider return final text every time.
    Without the fix this would exit on the first iteration with stop_reason
    "completed". With the fix the runner is forced to continue until
    max_iterations is hit.
    """
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        goal_active_predicate=lambda: True,
    ))

    # Because the predicate keeps returning True, the runner should never
    # naturally complete. It loops until max_iterations is exhausted.
    assert result.stop_reason == "max_iterations"
    # The injected continuation message should be present in the message list.
    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    assert any("active sustained goal" in str(m.get("content", "")) for m in user_msgs)


@pytest.mark.asyncio
async def test_runner_respects_max_iterations_even_with_active_goal():
    """A single iteration with active goal still hits max_iterations."""
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        goal_active_predicate=lambda: True,
    ))

    assert result.stop_reason == "max_iterations"


@pytest.mark.asyncio
async def test_runner_goal_continue_not_limited_by_injection_cycle_cap():
    """Synthetic goal continuation should be governed by max_iterations."""
    from nanobot.agent.runner import _MAX_INJECTION_CYCLES, AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    max_iterations = _MAX_INJECTION_CYCLES + 3

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=max_iterations,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        goal_active_predicate=lambda: True,
        finalize_on_max_iterations=False,
    ))

    assert result.stop_reason == "max_iterations"
    assert provider.chat_with_retry.await_count == max_iterations


@pytest.mark.asyncio
async def test_runner_does_not_force_continue_on_error():
    """Even with active goal, an LLM error should exit with stop_reason="error"."""
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content=None, tool_calls=[], usage={},
        finish_reason="error",
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        goal_active_predicate=lambda: True,
    ))

    assert result.stop_reason == "error"


@pytest.mark.asyncio
async def test_runner_uses_custom_goal_continue_message():
    """Custom goal_continue_message should be injected instead of the default."""
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    custom_msg = "CUSTOM_CONTINUE_PLEASE"

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        goal_active_predicate=lambda: True,
        goal_continue_message=custom_msg,
    ))

    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    assert any(custom_msg in str(m.get("content", "")) for m in user_msgs)


@pytest.mark.asyncio
async def test_runner_resolves_goal_continue_message_lazily():
    """The continuation text can depend on goal metadata created during the run."""
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    calls = {"n": 0}

    def dynamic_msg() -> str:
        calls["n"] += 1
        return "Goal (active):\nWrite the article draft."

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        goal_active_predicate=lambda: True,
        goal_continue_message=dynamic_msg,
        finalize_on_max_iterations=False,
    ))

    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    assert calls["n"] == 1
    assert any("Write the article draft." in str(m.get("content", "")) for m in user_msgs)
