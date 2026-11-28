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
from nanobot.agent.hooks import create_file_edit_activity_hook
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.tool_search import tool_view
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionPolicy
from nanobot.utils.llm_runtime import LLMRuntime

_CORE = {"exec", "exec_session", "list_exec_sessions", "read_file", "edit_file", "write_file", "apply_patch"}
_GATEWAYS = {"tool_search", "call_tool"}
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
        assert set(initial.by_name()) == _CORE | _GATEWAYS
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
        _step(("pressure", "call_tool", pressure), ("humidity", "call_tool", _dispatch("hygrometer", station="south")),
              ("direct", _BAROMETER, {"station": "north"})),
        LLMResponse(content="done"), _step(("stale", "call_tool", pressure)), LLMResponse(content="done"),
    ) as (loop, provider, client):
        await loop.process_direct("Read station pressure and humidity.", session_key="cli:weather", on_progress=progress)
        initial, after_guess, discovered, final = provider.requests
        assert set(initial.by_name()) == _CORE | _GATEWAYS
        assert "not available" in after_guess.tool_reply("before")
        reply = json.loads(discovered.tool_reply("find"))
        reply["tools"].sort(key=lambda f: f["name"])
        assert reply == {
            "tools": [loop.tools.get(name).to_schema()["function"] for name in ("hygrometer", _BAROMETER)],
            "other_matches": [],
        }
        assert "not found" in final.tool_reply("direct")
        assert final.tool_reply("pressure") == "1013 hPa"
        assert final.tool_reply("humidity") == "south: 52%"
        for call_id, name, station in (("pressure", _BAROMETER, "north"), ("humidity", "hygrometer", "south")):
            # Progress hooks observe the real operation; the provider sees the gateway it called.
            activity = [(e["phase"], e["name"], e["arguments"]) for e in events if e["call_id"] == call_id]
            assert activity == [(phase, name, {"station": station}) for phase in ("start", "end")]
            message = next(m for m in final.messages if m.get("tool_call_id") == call_id)
            assert message["name"] == "call_tool"

        # The conversation retains the search reply, not permission to use it on a later turn.
        await loop.process_direct("A separate request.", session_key="cli:weather")
        assert "not available" in provider.requests[-1].tool_reply("stale")
        for request in provider.requests[1:]:
            assert _serialized(request.schemas) == _serialized(initial.schemas)
        client.call_tool.assert_awaited_once_with("barometer", arguments={"station": "north"})


async def test_call_tool_cannot_bypass_native_repeated_lookup_guard(tmp_path, monkeypatch):
    args = _dispatch("web_fetch", url="https://fixture.invalid/forecast")
    async with _catalog_run(
        tmp_path, _step(("find", "tool_search", {"query": "web_fetch"})),
        *(_step((f"fetch-{i}", "call_tool", args)) for i in range(3)), LLMResponse(content="done"),
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
              ("guess_native", "call_tool", _dispatch("hygrometer", station="north")),
              ("guess_write", "write_file", {"path": "blocked.txt", "content": "blocked"})),
        LLMResponse(content="unavailable"),
    ) as (loop, provider, client):
        key = "cli:restricted"
        disabled = frozenset({_BAROMETER, "hygrometer", "write_file", "subagent"})
        await loop.sessions.state.get(key)
        await loop.sessions.state.set_policy(key, SessionPolicy(disabled_tools=disabled))
        await loop.process_direct("Try the disabled tools.", session_key=key)
        initial, after_search, final = provider.requests
        assert set(initial.by_name()) == (_CORE - disabled) | _GATEWAYS
        assert _serialized(after_search.schemas) == _serialized(initial.schemas)
        assert json.loads(after_search.tool_reply("find")) == {"tools": [], "other_matches": []}
        delegate = json.loads(after_search.tool_reply("find_delegate"))
        assert "subagent" not in [f["name"] for f in delegate["tools"]] + delegate["other_matches"]
        for call_id in ("guess", "guess_native", "delegate"):
            assert "not available" in final.tool_reply(call_id)
        assert "not found" in final.tool_reply("guess_write")
        client.call_tool.assert_not_awaited()
        assert not (tmp_path / "blocked.txt").exists()


@pytest.mark.parametrize("disabled_gateway", sorted(_GATEWAYS))
async def test_disabled_gateway_falls_back_to_allowed_direct_tools(tmp_path, disabled_gateway):
    async with _catalog_run(
        tmp_path, _step(("read", _BAROMETER, {"station": "north"}),
                        ("blocked", "hygrometer", {"station": "north"})), LLMResponse(content="done"),
    ) as (loop, provider, client):
        key = "cli:direct-tools"
        disabled = frozenset({disabled_gateway, "write_file", "hygrometer"})
        await loop.sessions.state.get(key)
        await loop.sessions.state.set_policy(key, SessionPolicy(disabled_tools=disabled))
        await loop.process_direct("Read the sensors directly.", session_key=key)
        initial, final = provider.requests
        assert initial.schemas == [s for s in loop.tools.get_definitions() if s["function"]["name"] not in disabled]
        assert disabled_gateway not in initial.by_name()
        assert final.tool_reply("read") == "1013 hPa"
        assert "not found" in final.tool_reply("blocked")
        client.call_tool.assert_awaited_once_with("barometer", arguments={"station": "north"})


async def test_zero_budget_sends_full_catalog_on_first_request(tmp_path):
    async with _catalog_run(tmp_path, LLMResponse(content="done"), budget=0) as (loop, provider, client):
        for i in range(300):
            loop.tools.register(_sensor(client, f"sensor_{i:03}"))
        assert loop.tools.searchable_schema_tokens() > ToolsConfig().schema_token_budget
        expected = loop.tools.get_definitions()
        await loop.process_direct("Hello.", session_key="cli:full-catalog")
        (request,) = provider.requests
        assert request.schemas == expected
        assert _GATEWAYS.isdisjoint(request.by_name())


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
        assert set(view.tool_names) == _GATEWAYS

        for name in _CORE:
            source.register(loop.tools.get(name))
        assert source.searchable_schema_tokens() == budget
        assert tool_view(source, budget) is source
        assert set(tool_view(source, budget - 1).tool_names) == _CORE | _GATEWAYS


@pytest.mark.parametrize("reconnect", [False, True], ids=["retired", "replaced-under-same-name"])
async def test_discovery_does_not_authorize_retired_or_reconnected_wrappers(tmp_path, reconnect):
    async with _catalog_run(tmp_path) as (loop, _, client):
        source = loop.tools
        # A restricted session must see reconnects too; copying its allowed wrappers would leave them stale.
        view = tool_view(source.excluding(frozenset({"exec"})), 1)
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
        found = json.loads(await view.execute("tool_search", {"query": "barometer"}))
        if reconnect:
            replacement.call_tool.assert_not_awaited()
            assert found["tools"] == [source.get(_BAROMETER).to_schema()["function"]]
            assert await view.execute("call_tool", params) == "1013 hPa"
            replacement.call_tool.assert_awaited_once_with("barometer", arguments={"station": "north"})
            client.call_tool.assert_not_awaited()
        else:
            assert found == {"tools": [], "other_matches": []}


async def test_call_tool_validates_the_envelope_and_the_discovered_tools_arguments(tmp_path):
    async with _catalog_run(tmp_path) as (loop, _, client):
        view = tool_view(loop.tools, 1)
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


async def test_more_matches_can_be_selected_by_name_without_loading_another_page(tmp_path):
    async with _catalog_run(tmp_path) as (_, _provider, client):
        source = ToolRegistry()
        for i in range(12):
            source.register(_sensor(client, f"pressure_{i:02}"))
        view = tool_view(source, 1)
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
                     ("humidity", "call_tool", _dispatch("hygrometer", station="south")))

    def script(query):
        return [_step(("find", "tool_search", {"query": query})), read_both, LLMResponse(content="done")]

    async with _catalog_run(tmp_path, *script("barometer")) as (loop, pressure, client):
        humidity = _ScriptedProvider(script("hygrometer"))
        await asyncio.gather(
            loop.process_direct("Find pressure.", session_key="cli:pressure"),
            loop.process_direct("Find humidity.", session_key="cli:humidity",
                                runtime=LLMRuntime.capture(humidity, "test-model", context_window_tokens=128_000)),
        )
        assert pressure.requests[-1].tool_reply("pressure") == "1013 hPa"
        assert "not available" in pressure.requests[-1].tool_reply("humidity")
        assert humidity.requests[-1].tool_reply("humidity") == "south: 52%"
        assert "not available" in humidity.requests[-1].tool_reply("pressure")
        client.call_tool.assert_awaited_once_with("barometer", arguments={"station": "north"})
