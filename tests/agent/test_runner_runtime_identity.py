from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)
from nanobot.utils.llm_runtime import LLMRuntime


@pytest.mark.asyncio
async def test_active_run_keeps_provider_captured_at_admission() -> None:
    first_provider = MagicMock(spec=LLMProvider)
    second_provider = MagicMock(spec=LLMProvider)
    first_provider.generation = GenerationSettings(temperature=0.2, max_tokens=2048)
    second_provider.generation = GenerationSettings(temperature=0.9, max_tokens=512)
    first_calls = 0
    second_calls = 0
    request_temperatures: list[float] = []
    selected_runtime = LLMRuntime.capture(
        first_provider,
        "captured-model",
        context_window_tokens=16_384,
    )
    runner = AgentRunner()

    async def first_chat(**kwargs):
        nonlocal first_calls, selected_runtime
        first_calls += 1
        request_temperatures.append(kwargs["temperature"])
        selected_runtime = LLMRuntime.capture(
            second_provider,
            "future-model",
            context_window_tokens=8192,
        )
        first_provider.generation = GenerationSettings(temperature=0.7, max_tokens=128)
        if first_calls > 1:
            return LLMResponse(content="done")
        return LLMResponse(
            content="working",
            tool_calls=[ToolCallRequest(id="call-1", name="read_file", arguments={})],
        )

    async def second_chat(**_kwargs):
        nonlocal second_calls
        second_calls += 1
        return LLMResponse(content="done")

    first_provider.chat_with_retry = first_chat
    second_provider.chat_with_retry = second_chat
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="contents")

    await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "read it"}],
        tools=tools,
        runtime=selected_runtime,
        max_iterations=2,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
    ))

    assert first_calls == 2
    assert second_calls == 0
    assert request_temperatures == [0.2, 0.2]
    assert selected_runtime.provider is second_provider
