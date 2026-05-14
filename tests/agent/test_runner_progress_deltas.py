"""Tests for provider progress delta routing in the shared runner."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_can_disable_provider_progress_delta_streaming():
    """AgentLoop disables token progress streaming for non-streaming channels."""
    provider = MagicMock()
    provider.supports_progress_deltas = True
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="done", tool_calls=[], usage={})
    )
    provider.chat_stream_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    progress_cb = AsyncMock()

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hi"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
        stream_progress_deltas=False,
    ))

    assert result.final_content == "done"
    provider.chat_with_retry.assert_awaited_once()
    provider.chat_stream_with_retry.assert_not_awaited()
    progress_cb.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_streams_provider_progress_deltas_by_default():
    """Direct runner users keep the existing opt-in provider progress behavior."""
    provider = MagicMock()
    provider.supports_progress_deltas = True

    async def chat_stream_with_retry(*, on_content_delta, **kwargs):
        await on_content_delta("he")
        await on_content_delta("llo")
        return LLMResponse(content="hello", tool_calls=[], usage={})

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    progress_cb = AsyncMock()

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hi"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
    ))

    assert result.final_content == "hello"
    assert [call.args[0] for call in progress_cb.await_args_list] == ["he", "llo"]
    provider.chat_with_retry.assert_not_awaited()
