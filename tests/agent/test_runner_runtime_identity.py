from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="AgentRunner reads its mutable provider again between model iterations",
)
async def test_active_run_keeps_provider_captured_at_admission() -> None:
    first_provider = MagicMock(spec=LLMProvider)
    second_provider = MagicMock(spec=LLMProvider)
    first_calls = 0
    second_calls = 0
    runner = AgentRunner(first_provider)

    async def first_chat(**_kwargs):
        nonlocal first_calls
        first_calls += 1
        runner.provider = second_provider
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
        model="captured-model",
        max_iterations=2,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
    ))

    assert first_calls == 2
    assert second_calls == 0
