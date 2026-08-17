"""Regression coverage for sustained-goal completion in AgentRunner.

An active goal continues internally only after a tool-call budget boundary.
When the model responds with plain text, including a clarification question,
the turn must end and the user must receive exactly one reply.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.runner import AgentRunner
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_exits_normally_after_plain_final_response() -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="All done.", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "completed"
    assert result.final_content == "All done."
    assert provider.chat_with_retry.await_count == 1


@pytest.mark.asyncio
async def test_runner_does_not_repeat_clarification_for_active_goal() -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Which day should I start?", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "/goal make a study plan"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "completed"
    assert result.final_content == "Which day should I start?"
    assert provider.chat_with_retry.await_count == 1
