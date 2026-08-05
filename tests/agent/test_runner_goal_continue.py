"""Tests for sustained-goal continuation in AgentRunner.

When a goal_active_predicate returns True, the runner must not exit with
stop_reason="completed" after a plain-text final response. Instead it should
inject a continuation message and keep looping (similar to mid-turn injection).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_exits_normally_without_predicate():
    """Baseline: no predicate, runner exits with completed on final text."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="all done", tool_calls=[], usage={},
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
async def test_runner_exits_normally_with_inactive_goal():
    """Predicate returns False, runner should exit normally."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="all done", tool_calls=[], usage={},
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
        goal_active_predicate=lambda: False,
    ))

    assert result.stop_reason == "completed"
    assert result.final_content == "all done"


@pytest.mark.asyncio
async def test_runner_forces_continue_when_goal_active():
    """Predicate returns True on final text → runner injects continuation and loops.

    Without the goal predicate this would exit on the first iteration. How many
    continuations are allowed is covered by the idle-budget tests below.
    """
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage={},
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
        goal_active_predicate=lambda: True,
    ))

    assert provider.chat_with_retry.await_count > 1
    # The injected continuation message should be present in the message list.
    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    assert any("active sustained goal" in str(m.get("content", "")) for m in user_msgs)


@pytest.mark.asyncio
async def test_runner_respects_max_iterations_even_with_active_goal():
    """A single iteration with active goal still hits max_iterations."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage={},
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
        goal_active_predicate=lambda: True,
    ))

    assert result.stop_reason == "max_iterations"


@pytest.mark.asyncio
async def test_runner_keeps_answering_user_after_goal_idle_budget_is_spent():
    """A spent idle budget silences the goal nudge only, never real user input."""
    from nanobot.agent.runner import _MAX_GOAL_IDLE_CONTINUES, AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    drains = {"n": 0}

    async def inject_once_after_budget():
        drains["n"] += 1
        if drains["n"] == _MAX_GOAL_IDLE_CONTINUES + 1:
            return [{"role": "user", "content": "actually, one more thing"}]
        return []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=20,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        goal_active_predicate=lambda: True,
        injection_callback=inject_once_after_budget,
    ))

    assert result.stop_reason == "completed"
    user_msgs = [str(m.get("content", "")) for m in result.messages if m.get("role") == "user"]
    assert any("actually, one more thing" in m for m in user_msgs)
    # Idle budget, then the real injection, then the turn ends.
    assert provider.chat_with_retry.await_count == _MAX_GOAL_IDLE_CONTINUES + 2


@pytest.mark.asyncio
async def test_runner_stops_goal_continue_after_consecutive_idle_responses():
    """An idling goal must hand control back instead of nagging until the budget dies.

    A goal that keeps answering in plain text is waiting for the user, not working.
    The runner allows a bounded number of nudges, then finishes the turn normally.
    """
    from nanobot.agent.runner import _MAX_GOAL_IDLE_CONTINUES, AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Still here whenever you're ready.", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=20,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        goal_active_predicate=lambda: True,
    ))

    assert result.stop_reason == "completed"
    assert result.final_content == "Still here whenever you're ready."
    assert provider.chat_with_retry.await_count == _MAX_GOAL_IDLE_CONTINUES + 1


@pytest.mark.asyncio
async def test_runner_resets_goal_idle_streak_after_tool_use():
    """Tool progress means the goal is working, so the nudge budget starts over."""
    from nanobot.agent.runner import _MAX_GOAL_IDLE_CONTINUES, AgentRunner

    idle = LLMResponse(content="Waiting on you.", tool_calls=[], usage={})
    working = LLMResponse(
        content="Checking.",
        tool_calls=[ToolCallRequest(id="c1", name="list_dir", arguments={"path": "."})],
        usage={},
    )
    # Idle up to the cap, do real work, then idle again: the streak must restart.
    responses = [idle] * _MAX_GOAL_IDLE_CONTINUES + [working] + [idle] * 10

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(side_effect=responses)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="ok")

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=20,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        goal_active_predicate=lambda: True,
    ))

    assert result.stop_reason == "completed"
    # cap idle responses + 1 tool iteration + cap idle responses again + the one
    # that finds the budget spent.
    assert provider.chat_with_retry.await_count == 2 * _MAX_GOAL_IDLE_CONTINUES + 2


@pytest.mark.asyncio
async def test_runner_does_not_force_continue_on_error():
    """Even with active goal, an LLM error should exit with stop_reason="error"."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content=None, tool_calls=[], usage={},
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
        goal_active_predicate=lambda: True,
    ))

    assert result.stop_reason == "error"


@pytest.mark.asyncio
async def test_runner_uses_custom_goal_continue_message():
    """Custom goal_continue_message should be injected instead of the default."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working", tool_calls=[], usage={},
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
        goal_active_predicate=lambda: True,
        goal_continue_message=custom_msg,
    ))

    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    assert any(custom_msg in str(m.get("content", "")) for m in user_msgs)


@pytest.mark.asyncio
async def test_runner_resolves_goal_continue_message_lazily():
    """The continuation text can depend on goal metadata created during the run."""
    from nanobot.agent.runner import AgentRunner

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

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
