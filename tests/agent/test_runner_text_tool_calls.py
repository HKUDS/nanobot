from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse


def test_normalize_text_tool_call_markup() -> None:
    response = LLMResponse(
        content=(
            "I will check.\n"
            '<tool_call>{"id":"call_1","name":"read_file",'
            '"arguments":{"path":"README.md"}}</tool_call>'
        ),
    )

    AgentRunner._normalize_text_tool_calls(response)

    assert response.finish_reason == "tool_calls"
    assert response.content == "I will check."
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].name == "read_file"
    assert response.tool_calls[0].arguments == {"path": "README.md"}


def test_normalize_text_tool_call_leaves_malformed_json_as_text() -> None:
    content = 'Before <tool_call>{"name":"read_file","arguments":</tool_call> after'
    response = LLMResponse(content=content)

    AgentRunner._normalize_text_tool_calls(response)

    assert response.content == content
    assert response.tool_calls == []
    assert response.finish_reason == "stop"


@pytest.mark.asyncio
async def test_runner_executes_text_tool_call_markup() -> None:
    provider = MagicMock()
    call_count = {"n": 0}
    captured_messages: list[list[dict]] = []

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append([dict(message) for message in messages])
        if call_count["n"] == 1:
            return LLMResponse(
                content=(
                    "Checking now.\n"
                    '<tool_call>{"name":"read_file",'
                    '"arguments":{"path":"README.md"}}</tool_call>'
                ),
            )
        return LLMResponse(content="The file says ok.")

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = [{"name": "read_file"}]
    tools.execute = AsyncMock(return_value="ok")

    result = await AgentRunner(provider).run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "read README"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
    ))

    assert result.final_content == "The file says ok."
    tools.execute.assert_awaited_once_with("read_file", {"path": "README.md"})
    assistant = next(message for message in result.messages if message.get("role") == "assistant")
    assert assistant["content"] == "Checking now."
    assert "<tool_call>" not in assistant["content"]
    assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
    second_call = captured_messages[-1]
    assert any(
        message.get("role") == "tool" and message.get("content") == "ok"
        for message in second_call
    )
