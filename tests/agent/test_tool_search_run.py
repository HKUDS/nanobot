"""Exercise tool discovery at the model request boundary, without a server or LLM."""

import asyncio
import json
from contextlib import aclosing, asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from mcp import ClientSession, types

from agent.session_helpers import make_agent_loop
from nanobot.agent.hook import AgentHook
from nanobot.agent.hooks import create_file_edit_activity_hook
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.mcp import MCPPromptWrapper, MCPResourceWrapper, MCPToolWrapper
from nanobot.agent.tools.mcp_metadata import MCPServerInfo
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.tool_search import mcp_server_directory, tool_view
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionPolicy
from nanobot.utils.llm_runtime import LLMRuntime

_GATEWAYS = {"tool_search", "call_tool"}
_BAROMETER = "mcp_lab_barometer"
_STATION = {"type": "object", "properties": {"station": {"type": "string"}}, "required": ["station"]}


class _Hygrometer(Tool):
    name = "mcp_plugin_hygrometer"  # A plugin's chosen name is not proof of MCP origin.
    description = "Read station humidity."
    parameters = _STATION

    async def execute(self, station):
        return f"{station}: 52%"


def _sensor(client, name, *, server_info=None):
    return MCPToolWrapper(client, "lab", types.Tool(
        name=name, description=f"Read the {name} measurement at a weather station.", inputSchema=_STATION,
    ), server_info=server_info)


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
        response = next(self.responses)
        return await response() if callable(response) else response


def _step(*calls):
    return LLMResponse(content=None, tool_calls=[
        ToolCallRequest(id=call_id, name=name, arguments=args) for call_id, name, args in calls
    ])


def _dispatch(name, **arguments):
    return {"name": name, "arguments": arguments}


def _serialized(schemas):
    # Keep list and key order: dict equality would miss changes to the wire prefix.
    return json.dumps(schemas, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@asynccontextmanager
async def _catalog_run(tmp_path, *responses):
    provider = _ScriptedProvider(responses)
    loop = make_agent_loop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
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
        assert set(initial.by_name()) == (set(loop.tools.tool_names) - {_BAROMETER}) | _GATEWAYS
        assert "fresh measurement" in final.tool_reply("read")
        assert {e["name"] for e in tool_events} == {"read_file", "write_file", "edit_file", "apply_patch"}
        assert {(e["call_id"], e["tool"], e["path"]) for e in file_events if e["status"] == "done"} == {
            ("write", "write_file", "write.txt"), ("edit", "edit_file", "edit.txt"), ("patch", "apply_patch", "patch.txt"),
        }
        for path in ("write.txt", "edit.txt", "patch.txt"):
            assert (tmp_path / path).read_text(encoding="utf-8") == "new\n"


async def test_discovery_returns_original_functions_without_changing_model_tools(tmp_path):
    pressure = _dispatch(_BAROMETER, station="north")
    events = []

    async def progress(content, **kwargs):
        events.extend(kwargs.get("tool_events", []))

    async with _catalog_run(
        tmp_path, _step(("before", "call_tool", pressure)),
        _step(("find", "tool_search", {"query": "barometer hygrometer"})),
        _step(("pressure", "call_tool", pressure), ("humidity", _Hygrometer.name, {"station": "south"}),
              ("direct", _BAROMETER, {"station": "north"}),
              ("indirect", "call_tool", _dispatch(_Hygrometer.name, station="south"))),
        LLMResponse(content="done"), _step(("stale", "call_tool", pressure)), LLMResponse(content="done"),
    ) as (loop, provider, client):
        await loop.process_direct("Read station pressure and humidity.", session_key="cli:weather", on_progress=progress)
        initial, after_guess, discovered, final = provider.requests
        assert set(initial.by_name()) == (set(loop.tools.tool_names) - {_BAROMETER}) | _GATEWAYS
        assert "not available" in after_guess.tool_reply("before")
        reply = json.loads(discovered.tool_reply("find"))
        assert reply == {
            "tools": [loop.tools.get(_BAROMETER).to_schema()["function"]],
            "other_matches": [],
        }
        assert "not found" in final.tool_reply("direct")
        assert "not available" in final.tool_reply("indirect")
        assert final.tool_reply("pressure") == "1013 hPa"
        assert final.tool_reply("humidity") == "south: 52%"
        for call_id, name, station in (("pressure", _BAROMETER, "north"), ("humidity", _Hygrometer.name, "south")):
            # Progress hooks observe the real operation; the provider sees the gateway it called.
            activity = [(e["phase"], e["name"], e["arguments"]) for e in events if e["call_id"] == call_id]
            assert activity == [(phase, name, {"station": station}) for phase in ("start", "end")]
            message = next(m for m in final.messages if m.get("tool_call_id") == call_id)
            assert message["name"] == ("call_tool" if name == _BAROMETER else _Hygrometer.name)

        # The conversation retains the search reply, not permission to use it on a later turn.
        await loop.process_direct("A separate request.", session_key="cli:weather")
        assert "not available" in provider.requests[-1].tool_reply("stale")
        for request in provider.requests[1:]:
            assert _serialized(request.schemas) == _serialized(initial.schemas)
        client.call_tool.assert_awaited_once_with("barometer", arguments={"station": "north"})


async def test_native_repeated_lookup_guard_applies_with_mcp_present(tmp_path, monkeypatch):
    args = {"url": "https://fixture.invalid/forecast"}
    async with _catalog_run(
        tmp_path, *(_step((f"fetch-{i}", "web_fetch", args)) for i in range(3)), LLMResponse(content="done"),
    ) as (loop, provider, _):
        fetch = AsyncMock(return_value="cached fixture forecast")
        monkeypatch.setattr(loop.tools.get("web_fetch"), "execute", fetch)
        await loop.process_direct("Look up the same forecast three times.")
        final = provider.requests[-1]
        assert final.tool_reply("fetch-0") == final.tool_reply("fetch-1") == "cached fixture forecast"
        assert "repeated external lookup blocked" in final.tool_reply("fetch-2")
        assert fetch.await_count == 2


async def test_policy_blocks_discovery_and_dispatch_for_disabled_tools(tmp_path):
    async with _catalog_run(
        tmp_path, _step(("find", "tool_search", {"query": "barometer hygrometer"}),
                        ("find_delegate", "tool_search", {"query": "subagent"})),
        _step(("delegate", "call_tool", _dispatch("subagent", action="check")),
              ("guess", "call_tool", _dispatch(_BAROMETER, station="north")),
              ("guess_native", _Hygrometer.name, {"station": "north"}),
              ("guess_write", "write_file", {"path": "blocked.txt", "content": "blocked"})),
        LLMResponse(content="unavailable"),
    ) as (loop, provider, client):
        key = "cli:restricted"
        allowed = _sensor(client, "rainfall")
        loop.tools.register(allowed)
        disabled = frozenset({_BAROMETER, _Hygrometer.name, "write_file", "subagent"})
        await loop.sessions.state.get(key)
        await loop.sessions.state.set_policy(key, SessionPolicy(disabled_tools=disabled))
        await loop.process_direct("Try the disabled tools.", session_key=key)
        initial, after_search, final = provider.requests
        assert set(initial.by_name()) == (set(loop.tools.tool_names) - disabled - {allowed.name}) | _GATEWAYS
        assert _serialized(after_search.schemas) == _serialized(initial.schemas)
        found = json.loads(after_search.tool_reply("find"))
        assert not found["tools"] and not found["other_matches"] and "barometer" not in str(found)
        delegate = json.loads(after_search.tool_reply("find_delegate"))
        assert "subagent" not in [f["name"] for f in delegate["tools"]] + delegate["other_matches"]
        for call_id in ("guess", "delegate"):
            assert "not available" in final.tool_reply(call_id)
        for call_id in ("guess_native", "guess_write"):
            assert "not found" in final.tool_reply(call_id)
        client.call_tool.assert_not_awaited()
        assert not (tmp_path / "blocked.txt").exists()


@pytest.mark.parametrize("disabled_gateway", sorted(_GATEWAYS))
async def test_disabled_gateway_exposes_only_permitted_direct_tools(tmp_path, disabled_gateway):
    async with _catalog_run(
        tmp_path, _step(("blocked", _BAROMETER, {"station": "north"}),
                        ("read", _Hygrometer.name, {"station": "north"})), LLMResponse(content="done"),
    ) as (loop, provider, client):
        key = "cli:direct-tools"
        disabled = frozenset({disabled_gateway, "write_file"})
        await loop.sessions.state.get(key)
        await loop.sessions.state.set_policy(key, SessionPolicy(disabled_tools=disabled))
        await loop.process_direct("Read the sensors directly.", session_key=key)
        initial, final = provider.requests
        assert set(initial.by_name()) == set(loop.tools.tool_names) - disabled - {_BAROMETER}
        assert final.tool_reply("read") == "north: 52%"
        assert "not found" in final.tool_reply("blocked")
        client.call_tool.assert_not_awaited()


async def test_resource_and_prompt_only_server_exposes_its_helpers_directly(tmp_path):
    async with _catalog_run(tmp_path, LLMResponse(content="done")) as (loop, provider, client):
        loop.tools.unregister(_BAROMETER)
        resource = MCPResourceWrapper(client, "lab", types.Resource(name="report", uri="lab://report"))
        prompt = MCPPromptWrapper(client, "lab", types.Prompt(name="inspect"))
        for tool in (resource, prompt):
            loop.tools.register(tool)
        await loop.process_direct("Hello.")
        (request,) = provider.requests
        assert request.schemas == loop.tools.get_definitions()
        assert {_Hygrometer.name, resource.name, prompt.name} <= set(request.by_name())
        assert _GATEWAYS.isdisjoint(request.by_name())
        assert mcp_server_directory(tool_view(loop.tools)) == ()


@pytest.mark.parametrize("collision", sorted(_GATEWAYS))
async def test_collision_preserves_registered_plugin_and_closes_bridge(collision):
    client = AsyncMock(spec=ClientSession)
    source = ToolRegistry()
    source.register(_sensor(client, "barometer"))
    view = tool_view(source)
    await view.execute("tool_search", {"query": _BAROMETER})
    call = view.get("call_tool")
    plugin = _Hygrometer()
    plugin.name = collision
    source.register(plugin)

    assert set(view.tool_names) == {collision}
    assert mcp_server_directory(view) == ()
    assert await view.execute(collision, {"station": "north"}) == "north: 52%"
    assert (await call.execute(**_dispatch(_BAROMETER, station="north"))).is_error
    assert (await view.execute(_BAROMETER, {"station": "north"})).is_error
    client.call_tool.assert_not_awaited()


def test_directory_deduplicates_and_orders_only_reachable_server_records():
    client = AsyncMock(spec=ClientSession)
    source = ToolRegistry()
    a, b, c = MCPServerInfo("same", "d", "A"), MCPServerInfo("same", "d", "B"), MCPServerInfo("last")
    for operation, info in [("b", b), ("c", c), ("a", a), ("also_b", b)]:
        source.register(_sensor(client, operation, server_info=info))
    view = tool_view(source, disabled=frozenset({"mcp_lab_c"}))
    assert mcp_server_directory(view) == (a, b)
    source.unregister("mcp_lab_a")
    assert mcp_server_directory(view) == (b,)
    assert mcp_server_directory(tool_view(source.excluding(frozenset({"call_tool"})))) == ()


@pytest.mark.parametrize("reconnect", [False, True], ids=["retired", "replaced-under-same-name"])
async def test_discovery_does_not_authorize_retired_or_reconnected_wrappers(tmp_path, reconnect):
    async with _catalog_run(tmp_path) as (loop, _, client):
        source = loop.tools
        # A restricted session must see reconnects too; copying its allowed wrappers would leave them stale.
        view = tool_view(source.excluding(frozenset({"exec"})))
        params = _dispatch(_BAROMETER, station="north")
        await view.execute("tool_search", {"query": "barometer"})
        source.unregister(_BAROMETER)
        if reconnect:
            # There need not be a model request between removal and re-registration.
            replacement = AsyncMock(spec=ClientSession)
            replacement.call_tool.return_value = client.call_tool.return_value
            source.register(_sensor(replacement, "barometer"))

        denied = await view.execute("call_tool", params)
        assert denied.is_error
        client.call_tool.assert_not_awaited()
        if reconnect:
            found = json.loads(await view.execute("tool_search", {"query": "barometer"}))
            replacement.call_tool.assert_not_awaited()
            assert found["tools"] == [source.get(_BAROMETER).to_schema()["function"]]
            assert await view.execute("call_tool", params) == "1013 hPa"
            replacement.call_tool.assert_awaited_once_with("barometer", arguments={"station": "north"})
            client.call_tool.assert_not_awaited()
        else:
            assert not view.has("tool_search") and mcp_server_directory(view) == ()


async def test_call_tool_validates_the_envelope_and_the_discovered_tools_arguments(tmp_path):
    async with _catalog_run(tmp_path) as (loop, _, client):
        view = tool_view(loop.tools)
        await view.execute("tool_search", {"query": "barometer"})
        for bad_args in ({}, {"station": 17}):
            native = await loop.tools.execute(_BAROMETER, bad_args)
            forwarded = await view.execute("call_tool", _dispatch(_BAROMETER, **bad_args))
            assert forwarded.is_error and native.is_error
            assert forwarded == native
        assert (await view.execute("tool_search", {"query": ""})).is_error
        found = json.loads(await view.execute("tool_search", {"query": "write_file"}))
        assert "write_file" not in [f["name"] for f in found["tools"]] + found["other_matches"]
        for params in ({"arguments": {}}, {"name": _BAROMETER, "arguments": ["north"]},
                       _dispatch("missing_sensor"), _dispatch("tool_search", query="barometer"),
                       _dispatch("write_file", path="blocked.txt", content="blocked")):
            assert (await view.execute("call_tool", params)).is_error
        assert not (tmp_path / "blocked.txt").exists()
        client.call_tool.assert_not_awaited()


async def test_miss_suggests_permitted_name_and_source_without_authorizing_it():
    client = AsyncMock(spec=ClientSession)
    source = ToolRegistry()
    source.register(_sensor(client, "barometer", server_info=MCPServerInfo("Weather Station")))
    view = tool_view(source)

    miss = json.loads(await view.execute("tool_search", {"query": "baromter"}))
    assert miss["tools"] == []
    assert miss["suggestion"] == {"name": _BAROMETER, "source": "Weather Station"}
    assert miss["hint"]
    assert (await view.execute("call_tool", _dispatch(_BAROMETER, station="north"))).is_error
    client.call_tool.assert_not_awaited()


async def test_reconnect_during_native_hook_invalidates_pending_dispatch(tmp_path):
    async with _catalog_run(
        tmp_path, _step(("find", "tool_search", {"query": _BAROMETER})),
        _step(("read", "call_tool", _dispatch(_BAROMETER, station="north"))), LLMResponse(content="done"),
    ) as (loop, provider, old):
        replacement = AsyncMock(spec=ClientSession)

        class Reconnect(AgentHook):
            async def before_execute_tool(self, context, tool_call, tool, params):
                if tool_call.name == _BAROMETER:
                    loop.tools.register(_sensor(replacement, "barometer"))

        await loop.process_direct("Read pressure.", hook_factories=[lambda _: Reconnect()])
        assert "availability changed" in provider.requests[-1].tool_reply("read")
        old.call_tool.assert_not_awaited()
        replacement.call_tool.assert_not_awaited()


async def test_more_matches_can_be_selected_by_name_without_loading_another_page(tmp_path):
    async with _catalog_run(tmp_path) as (_, _provider, client):
        source = ToolRegistry()
        for i in range(12):
            source.register(_sensor(client, f"pressure_{i:02}"))
        view = tool_view(source)
        initial = _serialized(view.get_definitions())
        reply = json.loads(await view.execute("tool_search", {"query": "pressure"}))
        first = [f["name"] for f in reply["tools"]]
        assert len(first) == 5
        assert reply["tools"] == [source.get(name).to_schema()["function"] for name in first]
        target = "mcp_lab_pressure_06"
        assert target in reply["other_matches"] and target not in first
        assert set(reply["other_matches"]) <= set(source.tool_names) - set(first)
        params = _dispatch(target, station="north")
        assert (await view.execute("call_tool", params)).is_error
        client.call_tool.assert_not_awaited()
        exact = json.loads(await view.execute("tool_search", {"query": target}))
        assert exact["tools"][0] == source.get(target).to_schema()["function"]
        assert await view.execute("call_tool", params) == "1013 hPa"
        assert await view.execute("call_tool", _dispatch(first[0], station="south")) == "1013 hPa"
        assert _serialized(view.get_definitions()) == initial


async def test_parallel_runs_do_not_share_discovery(tmp_path):
    both_searched = asyncio.Barrier(2)

    async def read_both():
        # Both runs have received their own search result before either tries the other's tool.
        await asyncio.wait_for(both_searched.wait(), timeout=10)
        return _step(("pressure", "call_tool", _dispatch(_BAROMETER, station="north")),
                     ("humidity", "call_tool", _dispatch("mcp_lab_humidity", station="south")))

    def script(query):
        return [_step(("find", "tool_search", {"query": query})), read_both, LLMResponse(content="done")]

    async with _catalog_run(tmp_path, *script("barometer")) as (loop, pressure, client):
        loop.tools.register(_sensor(client, "humidity"))
        humidity = _ScriptedProvider(script("humidity"))
        await asyncio.gather(
            loop.process_direct("Find pressure.", session_key="cli:pressure"),
            loop.process_direct("Find humidity.", session_key="cli:humidity",
                                runtime=LLMRuntime.capture(humidity, "test-model", context_window_tokens=128_000)),
        )
        assert pressure.requests[-1].tool_reply("pressure") == "1013 hPa"
        assert "not available" in pressure.requests[-1].tool_reply("humidity")
        assert humidity.requests[-1].tool_reply("humidity") == "1013 hPa"
        assert "not available" in humidity.requests[-1].tool_reply("pressure")
        assert client.call_tool.await_count == 2
        client.call_tool.assert_any_await("barometer", arguments={"station": "north"})
        client.call_tool.assert_any_await("humidity", arguments={"station": "south"})
