"""Tests for AgentRunner tool execution: batching, concurrency, exclusive tools."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blackcat.agent.runner import AgentRunner, AgentRunSpec
from blackcat.agent.tools.base import Tool
from blackcat.agent.tools.registry import ToolRegistry
from blackcat.config.schema import AgentDefaults
from blackcat.providers.base import LLMResponse, ToolCallRequest
from blackcat.providers.openai_compat_provider import OpenAICompatProvider
from blackcat.providers.openai_responses.parsing import parse_response_output

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


class _DelayTool(Tool):
    def __init__(
        self,
        name: str,
        *,
        delay: float,
        read_only: bool,
        shared_events: list[str],
        exclusive: bool = False,
    ):
        self._name = name
        self._delay = delay
        self._read_only = read_only
        self._shared_events = shared_events
        self._exclusive = exclusive

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._name

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def exclusive(self) -> bool:
        return self._exclusive

    async def execute(self, **kwargs):
        self._shared_events.append(f"start:{self._name}")
        await asyncio.sleep(self._delay)
        self._shared_events.append(f"end:{self._name}")
        return self._name


async def _run_optional_tool_response(response: LLMResponse):
    provider = MagicMock()
    calls = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return response
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = ToolRegistry()
    shared_events: list[str] = []
    tools.register(_DelayTool(
        "optional_tool",
        delay=0,
        read_only=True,
        shared_events=shared_events,
    ))

    result = await AgentRunner(provider).run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "try optional"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))
    return result, shared_events


def _tool_message(result, tool_call_id: str) -> dict:
    return [
        msg for msg in result.messages
        if msg.get("role") == "tool" and msg.get("tool_call_id") == tool_call_id
    ][0]


@pytest.mark.asyncio
async def test_runner_batches_read_only_tools_before_exclusive_work():
    tools = ToolRegistry()
    shared_events: list[str] = []
    read_a = _DelayTool("read_a", delay=0.05, read_only=True, shared_events=shared_events)
    read_b = _DelayTool("read_b", delay=0.05, read_only=True, shared_events=shared_events)
    write_a = _DelayTool("write_a", delay=0.01, read_only=False, shared_events=shared_events)
    tools.register(read_a)
    tools.register(read_b)
    tools.register(write_a)

    runner = AgentRunner(MagicMock())
    await runner._execute_tools(
        AgentRunSpec(
            initial_messages=[],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            concurrent_tools=True,
        ),
        [
            ToolCallRequest(id="ro1", name="read_a", arguments={}),
            ToolCallRequest(id="ro2", name="read_b", arguments={}),
            ToolCallRequest(id="rw1", name="write_a", arguments={}),
        ],
        {},
        {},
    )

    assert shared_events[0:2] == ["start:read_a", "start:read_b"]
    assert "end:read_a" in shared_events and "end:read_b" in shared_events
    assert shared_events.index("end:read_a") < shared_events.index("start:write_a")
    assert shared_events.index("end:read_b") < shared_events.index("start:write_a")
    assert shared_events[-2:] == ["start:write_a", "end:write_a"]


@pytest.mark.asyncio
async def test_runner_does_not_batch_exclusive_read_only_tools():
    tools = ToolRegistry()
    shared_events: list[str] = []
    read_a = _DelayTool("read_a", delay=0.03, read_only=True, shared_events=shared_events)
    read_b = _DelayTool("read_b", delay=0.03, read_only=True, shared_events=shared_events)
    ddg_like = _DelayTool(
        "ddg_like",
        delay=0.01,
        read_only=True,
        shared_events=shared_events,
        exclusive=True,
    )
    tools.register(read_a)
    tools.register(ddg_like)
    tools.register(read_b)

    runner = AgentRunner(MagicMock())
    await runner._execute_tools(
        AgentRunSpec(
            initial_messages=[],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            concurrent_tools=True,
        ),
        [
            ToolCallRequest(id="ro1", name="read_a", arguments={}),
            ToolCallRequest(id="ddg1", name="ddg_like", arguments={}),
            ToolCallRequest(id="ro2", name="read_b", arguments={}),
        ],
        {},
        {},
    )

    assert shared_events[0] == "start:read_a"
    assert shared_events.index("end:read_a") < shared_events.index("start:ddg_like")
    assert shared_events.index("end:ddg_like") < shared_events.index("start:read_b")


@pytest.mark.asyncio
async def test_runner_rejects_near_miss_tool_name_without_executing():
    provider = MagicMock()
    call_count = {"n": 0}
    captured_second_call: list[dict] = []

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="readFile",
                        arguments={"path": "notes.txt"},
                    )
                ],
                finish_reason="tool_calls",
                usage={},
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = ToolRegistry()
    shared_events: list[str] = []
    tools.register(_DelayTool(
        "read_file",
        delay=0,
        read_only=True,
        shared_events=shared_events,
    ))

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "read notes"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"
    assert result.tools_used == []
    assert shared_events == []
    assistant_message = [
        msg for msg in result.messages
        if msg.get("role") == "assistant" and msg.get("tool_calls")
    ][0]
    assert assistant_message["tool_calls"][0]["function"]["name"] == "readFile"
    tool_message = [
        msg for msg in result.messages
        if msg.get("role") == "tool" and msg.get("tool_call_id") == "call_1"
    ][0]
    assert tool_message["name"] == "readFile"
    assert "Tool 'readFile' not found" in tool_message["content"]
    assert "Did you mean 'read_file'?" in tool_message["content"]
    replayed_assistant = [
        msg for msg in captured_second_call
        if msg.get("role") == "assistant" and msg.get("tool_calls")
    ][0]
    assert replayed_assistant["tool_calls"][0]["function"]["name"] == "readFile"


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ['{path:"notes.txt"}', "null"])
async def test_runner_rejects_openai_compat_invalid_arguments_without_executing(arguments):
    with patch("blackcat.providers.openai_compat_provider.AsyncOpenAI"):
        parsed = OpenAICompatProvider()._parse({
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "optional_tool",
                            "arguments": arguments,
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
        })

    result, shared_events = await _run_optional_tool_response(parsed)

    assert result.final_content == "done"
    assert parsed.tool_calls[0].arguments == arguments
    assert result.tools_used == []
    assert shared_events == []
    tool_message = _tool_message(result, "call_1")
    assert "parameters must be a JSON object" in tool_message["content"]


@pytest.mark.asyncio
async def test_runner_rejects_openai_responses_malformed_arguments_without_executing():
    parsed = parse_response_output({
        "output": [{
            "type": "function_call",
            "call_id": "call_1",
            "id": "fc_1",
            "name": "optional_tool",
            "arguments": "{bad",
        }],
        "status": "completed",
        "usage": {},
    })

    result, shared_events = await _run_optional_tool_response(parsed)

    assert result.final_content == "done"
    assert parsed.tool_calls[0].arguments == "{bad"
    assert result.tools_used == []
    assert shared_events == []
    tool_message = _tool_message(result, "call_1|fc_1")
    assert "parameters must be a JSON object" in tool_message["content"]


@pytest.mark.asyncio
async def test_runner_rejects_openai_responses_array_arguments_without_executing():
    parsed = parse_response_output({
        "output": [{
            "type": "function_call",
            "call_id": "call_1",
            "id": "fc_1",
            "name": "optional_tool",
            "arguments": [],
        }],
        "status": "completed",
        "usage": {},
    })

    result, shared_events = await _run_optional_tool_response(parsed)

    assert result.final_content == "done"
    assert parsed.tool_calls[0].arguments == []
    assert result.tools_used == []
    assert shared_events == []
    tool_message = _tool_message(result, "call_1|fc_1")
    assert "parameters must be a JSON object" in tool_message["content"]


@pytest.mark.asyncio
async def test_runner_blocks_repeated_external_fetches():
    provider = MagicMock()
    captured_final_call: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] <= 3:
            return LLMResponse(
                content="working",
                tool_calls=[ToolCallRequest(id=f"call_{call_count['n']}", name="web_fetch", arguments={"url": "https://example.com"})],
                usage={},
            )
        captured_final_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="page content")

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "research task"}],
        tools=tools,
        model="test-model",
        max_iterations=4,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"
    assert tools.execute.await_count == 2
    blocked_tool_message = [
        msg for msg in captured_final_call
        if msg.get("role") == "tool" and msg.get("tool_call_id") == "call_3"
    ][0]
    assert "repeated external lookup blocked" in blocked_tool_message["content"]
