"""MCP host data stays separate from the model's tool observation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent.runner_helpers import make_run_spec
from mcp import types
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_connected_server_and_client_session

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.execution import execute_tool_calls
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.agent.tools.registry import ToolRegistry, is_tool_error_result
from nanobot.providers.base import LLMResponse, ToolCallRequest


@pytest.fixture
def rich_tool():
    definition = types.Tool(
        name="weather",
        inputSchema={"type": "object", "properties": {}},
        outputSchema={"type": "object", "properties": {"temperature": {"type": "number"}}},
        annotations=types.ToolAnnotations(readOnlyHint=True),
        _meta={"ui": {"resourceUri": "ui://weather/dashboard", "visibility": ["model", "app"]}},
    )
    response = types.CallToolResult(
        content=[types.TextContent(type="text", text="Sunny")],
        structuredContent={"temperature": 23, "stations": ["north"]},
        _meta={"host_only": "private-ui-receipt"},
    )
    session = AsyncMock()
    session.call_tool.return_value = response
    wrapper = MCPToolWrapper(session, "forecast", definition)
    return wrapper, response, session


@pytest.mark.parametrize("is_error", [False, True])
async def test_mcp_rich_results_survive_registry_and_execution_hooks(rich_tool, is_error):
    wrapper, response, session = rich_tool
    response.isError = is_error
    registry = ToolRegistry()
    registry.register(wrapper)

    direct = await registry.execute(wrapper.name, {})
    assert isinstance(direct, ToolResult)
    assert is_tool_error_result(direct) is is_error
    assert str(direct).startswith("Sunny")
    assert "private-ui-receipt" not in json.dumps(direct)
    assert direct.data["mcp"] == {
        "server_name": "forecast",
        "tool_name": "weather",
        "tool_meta": {"ui": {"resourceUri": "ui://weather/dashboard", "visibility": ["model", "app"]}},
        "outputSchema": {"type": "object", "properties": {"temperature": {"type": "number"}}},
        "annotations": {"readOnlyHint": True},
        "content": [{"type": "text", "text": "Sunny"}],
        "structuredContent": {"temperature": 23, "stations": ["north"]},
        "_meta": {"host_only": "private-ui-receipt"},
        "isError": is_error,
    }

    hook = AgentHook()
    callback = AsyncMock()
    if is_error:
        hook.on_execute_tool_error = callback
    else:
        hook.after_execute_tool = callback
    results, events = await execute_tool_calls(
        registry,
        [ToolCallRequest(id="call-1", name=wrapper.name, arguments={})],
        concurrent=False,
        external_lookup_counts={},
        workspace_violation_counts={},
        hook=hook,
        context=AgentHookContext(iteration=1, messages=[]),
    )
    callback.assert_awaited_once()
    observed = callback.call_args.args[-1]
    assert observed.data == direct.data
    assert results[0].data == direct.data
    assert is_tool_error_result(results[0]) is is_error
    assert events[0]["status"] == ("error" if is_error else "ok")
    assert "private-ui-receipt" not in json.dumps(events)
    assert session.call_tool.await_count == 2

    response.structuredContent["stations"].append("south")
    assert direct.data["mcp"]["structuredContent"]["stations"] == ["north"]


@pytest.mark.parametrize("payload", ["large", "deep", "wide", "nonfinite"])
async def test_mcp_omits_unbounded_fields_without_changing_text(rich_tool, payload):
    wrapper, response, _session = rich_tool
    if payload == "large":
        structured = {"value": "字" * 30_000}
    elif payload == "deep":
        structured = {}
        for _ in range(20):
            structured = {"child": structured}
    elif payload == "wide":
        structured = {"values": list(range(5000))}
    else:
        structured = {"value": float("nan")}
    response.structuredContent = structured

    result = await wrapper.execute()

    assert result == "Sunny"
    assert not is_tool_error_result(result)
    assert "structuredContent" not in result.data["mcp"]
    assert result.data["mcp"]["_meta"] == {"host_only": "private-ui-receipt"}
    assert len(json.dumps(result.data, ensure_ascii=False).encode("utf-8")) <= 64 * 1024


async def test_mcp_host_data_uses_a_shared_budget(rich_tool):
    wrapper, response, _session = rich_tool
    response.structuredContent = {"first": "x" * 40_000}
    response.meta = {"second": "x" * 40_000}

    result = await wrapper.execute()

    assert result == "Sunny"
    assert result.data["mcp"]["structuredContent"] == response.structuredContent
    assert "_meta" not in result.data["mcp"]
    assert result.data["mcp"]["content"] == [{"type": "text", "text": "Sunny"}]
    assert len(json.dumps(result.data, ensure_ascii=False).encode("utf-8")) <= 64 * 1024


async def test_plain_mcp_results_keep_their_text():
    session = AsyncMock()
    session.call_tool.return_value = types.CallToolResult(content=[])
    wrapper = MCPToolWrapper(session, "plain", types.Tool(name="empty", inputSchema={}))

    result = await wrapper.execute()

    assert isinstance(result, str)
    assert result == "(no output)"
    assert json.loads(json.dumps(result)) == "(no output)"
    assert result.data["mcp"]["content"] == []


async def test_real_mcp_session_preserves_host_data_outside_model_and_checkpoint():
    server = Server("weather")

    @server.list_tools()
    async def list_tools():
        return [types.Tool(
            name="weather", inputSchema={"type": "object", "properties": {}},
            _meta={"ui": {"resourceUri": "ui://weather/dashboard"}},
        )]

    @server.call_tool()
    async def call_tool(name, arguments):
        assert name == "weather"
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="Sunny")],
            structuredContent={"temperature": 23},
            _meta={"private": "ui-only-receipt"},
        )

    async with create_connected_server_and_client_session(server) as session:
        registry = ToolRegistry()
        definition = (await session.list_tools()).tools[0]
        wrapper = MCPToolWrapper(session, "forecast", definition)
        registry.register(wrapper)
        seen = []
        hook = AgentHook()
        hook.after_execute_tool = AsyncMock(side_effect=lambda *args: seen.append(args[-1]))
        provider = MagicMock()
        provider.chat_stream_with_retry = AsyncMock(side_effect=[
            LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="call-1", name=wrapper.name, arguments={},
            )]),
            LLMResponse(content="It is sunny."),
        ])
        checkpoint = AsyncMock()

        run = await AgentRunner().run(make_run_spec(
            provider,
            initial_messages=[
                {"role": "system", "content": "Check the weather."},
                {"role": "user", "content": "How is the weather?"},
            ],
            tools=registry,
            model="test-model",
            max_iterations=3,
            max_tool_result_chars=2000,
            hook=hook,
            checkpoint_callback=checkpoint,
        ))

    assert run.final_content == "It is sunny."
    assert seen[0].data["mcp"]["structuredContent"] == {"temperature": 23}
    assert seen[0].data["mcp"]["_meta"] == {"private": "ui-only-receipt"}
    observation = next(row["content"] for row in run.messages if row["role"] == "tool")
    assert observation == "Sunny"
    assert type(observation) is str
    for payload in [run.messages, *[call.args[0] for call in checkpoint.call_args_list]]:
        encoded = json.dumps(payload)
        assert "ui-only-receipt" not in encoded
        assert "temperature" not in encoded
