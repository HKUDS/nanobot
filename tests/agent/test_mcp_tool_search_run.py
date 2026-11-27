"""Exercise deferred MCP schemas at the model request boundary, without a server or LLM."""

from contextlib import aclosing, asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from unittest.mock import AsyncMock

from mcp import ClientSession, types

from agent.session_helpers import make_agent_loop
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionPolicy

_BAROMETER = "mcp_lab_barometer"


@dataclass
class _Request:
    schemas: list[dict]
    messages: list[dict]

    def by_name(self):
        return {d["function"]["name"]: d for d in self.schemas}

    def tool_reply(self, call_id):
        return next(m["content"] for m in self.messages if m["role"] == "tool" and m["tool_call_id"] == call_id)


class _ScriptedProvider(LLMProvider):
    def __init__(self, responses):
        super().__init__(provider_name="offline-mcp-test")
        self.responses = iter(responses)
        self.requests = []

    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, tools=None, **kwargs):
        self.requests.append(_Request(deepcopy(tools), deepcopy(messages)))
        return next(self.responses)


def _call(call_id, name, **arguments):
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=call_id, name=name, arguments=arguments)])


@asynccontextmanager
async def _catalog_run(tmp_path, *responses, budget=2048):
    provider = _ScriptedProvider(responses)
    loop = make_agent_loop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        tools_config=ToolsConfig.model_validate({"mcpSchemaTokenBudget": budget}),
        context_window_tokens=128_000,
    )
    async with aclosing(loop):
        client = AsyncMock(spec=ClientSession)
        client.call_tool.return_value = types.CallToolResult(content=[types.TextContent(type="text", text="1013 hPa")])
        for i in range(300):
            name = "barometer" if i == 173 else f"sensor_{i:03}"
            loop.tools.register(MCPToolWrapper(client, "lab", types.Tool(
                name=name, description=f"Read the {name} measurement at a weather station.",
                inputSchema={"type": "object", "properties": {"station": {"type": "string"}}, "required": ["station"]},
            )))
        yield loop, provider, client


async def test_search_exposes_native_schema_on_next_request_and_resets_for_next_run(tmp_path):
    async with _catalog_run(
        tmp_path, _call("find", "tool_search", query="barometer"),
        _call("measure", _BAROMETER, station="north"), LLMResponse(content="1013 hPa at north"),
        LLMResponse(content="new run"),
    ) as (loop, provider, client):
        builtins = {name for name in loop.tools.tool_names if not isinstance(loop.tools.get(name), MCPToolWrapper)}
        target = loop.tools.get(_BAROMETER)
        assert target is not None
        result = await loop.process_direct("Read the barometer at north.", session_key="cli:weather")
        assert result is not None and result.content == "1013 hPa at north"
        initial, discovered, final = provider.requests
        assert set(initial.by_name()) == builtins | {"tool_search"}
        hits = discovered.by_name()
        assert set(hits) == builtins | {"tool_search", _BAROMETER}
        assert hits[_BAROMETER] == target.to_schema()
        assert _BAROMETER in discovered.tool_reply("find")
        assert final.tool_reply("measure") == "1013 hPa"
        client.call_tool.assert_awaited_once_with("barometer", arguments={"station": "north"})

        await loop.process_direct("A separate request.", session_key="cli:weather")
        assert len(provider.requests) == 4
        assert provider.requests[3].schemas == initial.schemas


async def test_search_cannot_reveal_or_dispatch_tool_disabled_by_session(tmp_path):
    async with _catalog_run(
        tmp_path, _call("find", "tool_search", query="barometer"),
        _call("guess", _BAROMETER, station="north"), LLMResponse(content="unavailable"),
    ) as (loop, provider, client):
        key = "cli:restricted"
        await loop.sessions.state.get(key)
        await loop.sessions.state.set_policy(key, SessionPolicy(disabled_tools=frozenset({_BAROMETER})))
        await loop.process_direct("Try the barometer.", session_key=key)
        initial, after_search, final = provider.requests
        assert "tool_search" in initial.by_name()
        assert _BAROMETER not in after_search.by_name()
        assert _BAROMETER not in after_search.tool_reply("find")
        assert _BAROMETER in final.tool_reply("guess")
        client.call_tool.assert_not_awaited()


async def test_zero_budget_sends_full_catalog_on_first_request(tmp_path):
    async with _catalog_run(tmp_path, LLMResponse(content="done"), budget=0) as (loop, provider, _):
        expected = loop.tools.get_definitions()
        await loop.process_direct("Hello.", session_key="cli:full-catalog")
        (request,) = provider.requests
        assert request.schemas == expected
        assert "tool_search" not in request.by_name()


async def test_discovery_preserves_previous_schema_prefix_and_tracks_server_changes(tmp_path):
    from nanobot.agent.tools.mcp_tool_search import mcp_tool_view

    async with _catalog_run(tmp_path) as (loop, _, client):
        source = loop.tools
        assert mcp_tool_view(source, source.mcp_schema_tokens()) is source
        view = mcp_tool_view(source, 1)
        initial = view.get_definitions()
        await view.execute("tool_search", {"query": "barometer"})
        first = view.get_definitions()
        assert first[:-1] == initial and first[-1]["function"]["name"] == _BAROMETER
        await view.execute("tool_search", {"query": "sensor_037"})
        second = view.get_definitions()
        assert len(second) > len(first) and second[:len(first)] == first

        source.unregister(_BAROMETER)
        result = await view.execute(_BAROMETER, {"station": "north"})
        assert result.is_error
        assert _BAROMETER not in await view.execute("tool_search", {"query": "barometer"})
        client.call_tool.assert_not_awaited()
