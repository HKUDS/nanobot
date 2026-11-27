"""Exercise tool discovery at the model request boundary, without a server or LLM."""

from contextlib import aclosing, asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from mcp import ClientSession, types

from agent.session_helpers import make_agent_loop
from nanobot.agent.hooks import create_file_edit_activity_hook
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.tool_search import tool_view
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionPolicy

_CORE = {"exec", "exec_session", "list_exec_sessions", "read_file", "edit_file", "write_file", "apply_patch"}
_BAROMETER = "mcp_lab_barometer"
_STATION = {"type": "object", "properties": {"station": {"type": "string"}}, "required": ["station"]}


class _Hygrometer(Tool):
    name = "hygrometer"
    description = "Read station humidity."
    parameters = _STATION

    async def execute(self, station):
        return f"{station}: 52%"


def _sensor(client, name):
    return MCPToolWrapper(client, "lab", types.Tool(
        name=name, description=f"Read the {name} measurement at a weather station.", inputSchema=_STATION,
    ))


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
        super().__init__(provider_name="offline-tool-test")
        self.responses = iter(responses)
        self.requests = []

    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, tools=None, **kwargs):
        self.requests.append(_Request(deepcopy(tools), deepcopy(messages)))
        return next(self.responses)


def _step(*calls):
    return LLMResponse(content=None, tool_calls=[
        ToolCallRequest(id=call_id, name=name, arguments=args) for call_id, name, args in calls
    ])


@asynccontextmanager
async def _catalog_run(tmp_path, *responses, budget=1):
    provider = _ScriptedProvider(responses)
    loop = make_agent_loop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        tools_config=ToolsConfig.model_validate({"schemaTokenBudget": budget}),
        context_window_tokens=128_000,
    )
    async with aclosing(loop):
        client = AsyncMock(spec=ClientSession)
        client.call_tool.return_value = types.CallToolResult(content=[types.TextContent(type="text", text="1013 hPa")])
        loop.tools.register(_sensor(client, "barometer"))
        loop.tools.register(_Hygrometer())
        yield loop, provider, client


async def test_first_request_can_use_native_file_tools_without_search_or_exec(tmp_path):
    (tmp_path / "input.txt").write_text("fresh measurement\n", encoding="utf-8")
    (tmp_path / "edit.txt").write_text("old\n", encoding="utf-8")
    file_events, tool_events = [], []

    async def progress(content, **kwargs):
        file_events.extend(kwargs.get("file_edit_events", []))
        tool_events.extend(kwargs.get("tool_events", []))

    async with _catalog_run(tmp_path, _step(
        ("read", "read_file", {"path": "input.txt"}),
        ("write", "write_file", {"path": "write.txt", "content": "new\n"}),
        ("edit", "edit_file", {"path": "edit.txt", "old_text": "old", "new_text": "new"}),
        ("patch", "apply_patch", {"edits": [{"path": "patch.txt", "action": "add", "new_text": "new\n"}]}),
    ), LLMResponse(content="done")) as (loop, provider, _):
        await loop.process_direct("Read input.txt and update the three files.", on_progress=progress,
                                  hook_factories=[create_file_edit_activity_hook])
        initial, final = provider.requests
        assert set(initial.by_name()) == _CORE | {"tool_search"}
        assert "fresh measurement" in final.tool_reply("read")
        assert {e["name"] for e in tool_events} == {"read_file", "write_file", "edit_file", "apply_patch"}
        assert {(e["call_id"], e["tool"], e["path"]) for e in file_events if e["status"] == "done"} == {
            ("write", "write_file", "write.txt"), ("edit", "edit_file", "edit.txt"), ("patch", "apply_patch", "patch.txt"),
        }
        for path in ("write.txt", "edit.txt", "patch.txt"):
            assert (tmp_path / path).read_text(encoding="utf-8") == "new\n"


async def test_search_exposes_original_schemas_on_next_request_and_resets_for_next_run(tmp_path):
    async with _catalog_run(
        tmp_path, _step(("find", "tool_search", {"query": "barometer hygrometer"})),
        _step(("pressure", _BAROMETER, {"station": "north"}), ("humidity", "hygrometer", {"station": "south"})),
        LLMResponse(content="done"), _step(("guess", "hygrometer", {"station": "east"})), LLMResponse(content="done"),
    ) as (loop, provider, client):
        await loop.process_direct("Read station pressure and humidity.", session_key="cli:weather")
        initial, discovered, final = provider.requests
        assert set(initial.by_name()) == _CORE | {"tool_search"}
        assert set(discovered.by_name()) == set(initial.by_name()) | {_BAROMETER, "hygrometer"}
        for name in (_BAROMETER, "hygrometer"):
            assert discovered.by_name()[name] == loop.tools.get(name).to_schema()
            assert name in discovered.tool_reply("find")
        assert final.tool_reply("pressure") == "1013 hPa"
        assert final.tool_reply("humidity") == "south: 52%"
        client.call_tool.assert_awaited_once_with("barometer", arguments={"station": "north"})

        await loop.process_direct("A separate request.", session_key="cli:weather")
        fresh, after_guess = provider.requests[3:]
        assert fresh.schemas == initial.schemas
        assert "not found" in after_guess.tool_reply("guess")


async def test_policy_blocks_discovery_and_dispatch_for_disabled_tools(tmp_path):
    async with _catalog_run(
        tmp_path, _step(("find", "tool_search", {"query": "barometer hygrometer"})),
        _step(("guess", _BAROMETER, {"station": "north"}), ("guess_native", "hygrometer", {"station": "north"}),
              ("guess_write", "write_file", {"path": "blocked.txt", "content": "blocked"})),
        LLMResponse(content="unavailable"),
    ) as (loop, provider, client):
        key = "cli:restricted"
        disabled = frozenset({_BAROMETER, "hygrometer", "write_file"})
        await loop.sessions.state.get(key)
        await loop.sessions.state.set_policy(key, SessionPolicy(disabled_tools=disabled))
        await loop.process_direct("Try the disabled tools.", session_key=key)
        initial, after_search, final = provider.requests
        assert "tool_search" in initial.by_name()
        for name in disabled:
            assert name not in initial.by_name()
            assert name not in after_search.by_name()
            assert name not in after_search.tool_reply("find")
        for call_id in ("guess", "guess_native", "guess_write"):
            assert "not found" in final.tool_reply(call_id)
        client.call_tool.assert_not_awaited()
        assert not (tmp_path / "blocked.txt").exists()


async def test_zero_budget_sends_full_catalog_on_first_request(tmp_path):
    async with _catalog_run(tmp_path, LLMResponse(content="done"), budget=0) as (loop, provider, client):
        for i in range(300):
            loop.tools.register(_sensor(client, f"sensor_{i:03}"))
        assert loop.tools.searchable_schema_tokens() > ToolsConfig().schema_token_budget
        expected = loop.tools.get_definitions()
        await loop.process_direct("Hello.", session_key="cli:full-catalog")
        (request,) = provider.requests
        assert request.schemas == expected
        assert "tool_search" not in request.by_name()


@pytest.mark.parametrize("names", [(_BAROMETER,), ("hygrometer",), (_BAROMETER, "hygrometer")],
                         ids=["mcp", "native", "mixed"])
async def test_budget_counts_only_deferred_tools_and_keeps_small_catalog_eager(tmp_path, names):
    async with _catalog_run(tmp_path) as (loop, _, _client):
        source = ToolRegistry()
        for name in names:
            source.register(loop.tools.get(name))
        budget = source.searchable_schema_tokens()
        assert 1 < budget <= ToolsConfig().schema_token_budget
        assert tool_view(source, ToolsConfig().schema_token_budget) is source
        view = tool_view(source, budget - 1)
        assert view.tool_names == ["tool_search"]
        for name in names:
            assert name in await view.execute("tool_search", {"query": name})
        assert set(view.tool_names) == {"tool_search", *names}

        for name in _CORE:
            source.register(loop.tools.get(name))
        assert source.searchable_schema_tokens() == budget
        assert tool_view(source, budget) is source
        assert set(tool_view(source, budget - 1).tool_names) == _CORE | {"tool_search"}


async def test_discovery_preserves_previous_schema_prefix_and_tracks_catalog_changes(tmp_path):
    async with _catalog_run(tmp_path) as (loop, _, client):
        source = loop.tools
        view = tool_view(source, 1)
        initial = view.get_definitions()
        await view.execute("tool_search", {"query": "barometer"})
        first = view.get_definitions()
        assert first[:-1] == initial and first[-1]["function"]["name"] == _BAROMETER
        await view.execute("tool_search", {"query": "hygrometer"})
        second = view.get_definitions()
        assert second[:-1] == first and second[-1]["function"]["name"] == "hygrometer"

        source.unregister(_BAROMETER)
        result = await view.execute(_BAROMETER, {"station": "north"})
        assert result.is_error
        assert _BAROMETER not in await view.execute("tool_search", {"query": "barometer"})
        client.call_tool.assert_not_awaited()


async def test_more_matches_can_be_selected_by_name_without_loading_another_page(tmp_path):
    async with _catalog_run(tmp_path) as (_, _provider, client):
        source = ToolRegistry()
        for i in range(12):
            source.register(_sensor(client, f"pressure_{i:02}"))
        view = tool_view(source, 1)
        reply = await view.execute("tool_search", {"query": "pressure"})
        assert len(view.get_definitions()) == 6  # Search plus five callable tools, not ten.
        target = "mcp_lab_pressure_06"
        assert target in reply and not view.has(target)
        await view.execute("tool_search", {"query": target})
        assert await view.execute(target, {"station": "north"}) == "1013 hPa"
