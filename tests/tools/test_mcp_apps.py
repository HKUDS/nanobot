"""Source binding, authorization and lifecycle of the backend MCP Apps bridge."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import anyio
import pytest
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.shared.memory import create_client_server_memory_streams

from nanobot.agent.tools.mcp import MCPProvider, MCPToolWrapper
from nanobot.agent.tools.mcp_apps import MCPAppServer
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.network import NetworkConfig
from nanobot.config.schema import MCPServerConfig

_URI = "ui://weather/dashboard"
_MIME = "text/html;profile=mcp-app"


@pytest.fixture
def bridge():
    session = AsyncMock()
    session.read_resource.return_value = types.ReadResourceResult(contents=[
        types.TextResourceContents(uri=_URI, mimeType=_MIME, text="<h1>Weather</h1>"),
    ])
    session.call_tool.return_value = types.CallToolResult(
        content=[types.TextContent(type="text", text="Filtered")],
        structuredContent={"temperature": 23},
    )
    tools = {
        "dashboard": types.Tool(name="dashboard", inputSchema={}, _meta={"ui": {"resourceUri": _URI}}),
        "filter": types.Tool(name="filter", inputSchema={}, _meta={"ui": {"visibility": ["app"]}}),
        "model_only": types.Tool(name="model_only", inputSchema={}, _meta={"ui": {"visibility": ["model"]}}),
    }
    server = MCPAppServer(session, "weather", tools, timeout=0.1)
    authorize = AsyncMock(return_value=True)
    return server.open_app("dashboard", authorize=authorize), server, session, authorize


@pytest.mark.parametrize("binary", [False, True])
async def test_app_reads_declared_resource_and_retains_csp(bridge, binary):
    app, _server, session, _authorize = bridge
    html = "<h1>天气</h1>"
    metadata = {"ui": {"csp": {"connectDomains": ["https://weather.example"]}}}
    common = {"uri": _URI, "mimeType": "text/html; profile=mcp-app", "_meta": metadata}
    resource = (
        types.BlobResourceContents(**common, blob=base64.b64encode(html.encode()).decode())
        if binary else types.TextResourceContents(**common, text=html)
    )
    session.read_resource.return_value = types.ReadResourceResult(contents=[resource])

    result = await app.read_resource()

    assert result.html == html
    assert result.uri == _URI
    assert result.meta == metadata
    resource.meta["ui"]["csp"]["connectDomains"].append("https://changed.example")
    assert result.meta["ui"]["csp"]["connectDomains"] == ["https://weather.example"]
    assert str(session.read_resource.call_args.args[0]) == _URI


@pytest.mark.parametrize("invalid", ["mime", "uri", "multiple", "utf8-size", "base64"])
async def test_app_rejects_unusable_ui_resources(bridge, invalid):
    app, _server, session, _authorize = bridge
    resource = types.TextResourceContents(uri=_URI, mimeType=_MIME, text="<h1>OK</h1>")
    if invalid == "mime":
        resource.mimeType = "text/html"
    elif invalid == "uri":
        resource.uri = "ui://different/document"
    elif invalid == "utf8-size":
        resource.text = "字" * 400_000
    elif invalid == "base64":
        resource = types.BlobResourceContents(uri=_URI, mimeType=_MIME, blob="%%%")
    session.read_resource.return_value = types.ReadResourceResult(
        contents=[resource, resource] if invalid == "multiple" else [resource],
    )

    with pytest.raises(ValueError):
        await app.read_resource()


@pytest.mark.parametrize("name", ["another_server_filter", "model_only", "unknown"])
async def test_app_cannot_reach_unavailable_or_model_only_tools(bridge, name):
    app, _server, session, authorize = bridge

    with pytest.raises(PermissionError, match="not available"):
        await app.call_tool(name, {})

    session.call_tool.assert_not_awaited()
    authorize.assert_not_awaited()


async def test_app_tool_authorization_is_host_owned_and_arguments_are_detached(bridge):
    app, _server, session, authorize = bridge

    async def approve(request):
        assert request.server_name == "weather"
        assert request.tool_name == "filter"
        assert request.arguments == {"location": ["north"]}
        request.arguments["location"].append("changed by policy")
        return True

    authorize.side_effect = approve
    original = {"location": ["north"]}
    result = await app.call_tool("filter", original)

    assert result.structuredContent == {"temperature": 23}
    assert original == {"location": ["north"]}
    session.call_tool.assert_awaited_once_with("filter", arguments=original)


@pytest.mark.parametrize("invalid", ["denied", "arguments", "large"])
async def test_app_rejects_unapproved_or_invalid_calls_before_dispatch(bridge, invalid):
    app, _server, session, authorize = bridge
    authorize.return_value = False if invalid == "denied" else True
    arguments = [] if invalid == "arguments" else {"value": "x" * 70_000} if invalid == "large" else {}

    with pytest.raises((PermissionError, ValueError)):
        await app.call_tool("filter", arguments)

    session.call_tool.assert_not_awaited()


@pytest.mark.parametrize("close_server", [False, True])
async def test_app_sessions_revoke_resource_and_tool_access(bridge, close_server):
    app, server, session, authorize = bridge
    server.close() if close_server else app.close()

    with pytest.raises(RuntimeError, match="closed"):
        await app.read_resource()
    with pytest.raises(RuntimeError, match="closed"):
        await app.call_tool("filter", {})
    session.read_resource.assert_not_awaited()
    session.call_tool.assert_not_awaited()
    authorize.assert_not_awaited()


async def test_closing_connection_while_approval_is_pending_prevents_dispatch(bridge):
    app, server, session, authorize = bridge
    waiting, release = asyncio.Event(), asyncio.Event()

    async def approve(_request):
        waiting.set()
        await release.wait()
        return True

    authorize.side_effect = approve
    task = asyncio.create_task(app.call_tool("filter", {}))
    await asyncio.wait_for(waiting.wait(), timeout=1)
    server.close()
    release.set()

    with pytest.raises(RuntimeError, match="closed"):
        await task
    session.call_tool.assert_not_awaited()


@pytest.mark.parametrize("failure", ["timeout", "cancel", "output"])
async def test_app_never_retries_a_possibly_committed_call(bridge, failure):
    app, _server, session, _authorize = bridge
    started = asyncio.Event()

    async def slow_call(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    if failure == "output":
        session.call_tool.return_value = types.CallToolResult(
            content=[types.TextContent(type="text", text="x" * 70_000)],
        )
        with pytest.raises(ValueError, match="do not retry"):
            await app.call_tool("filter", {})
    else:
        session.call_tool.side_effect = slow_call
        task = asyncio.create_task(app.call_tool("filter", {}))
        await asyncio.wait_for(started.wait(), timeout=1)
        if failure == "cancel":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else TimeoutError):
            await task
    session.call_tool.assert_awaited_once()


@pytest.mark.parametrize("apps_enabled", [False, True])
async def test_discovery_bridge_uses_real_mcp_session_allowlist_and_connection_lifetime(monkeypatch, apps_enabled):
    server = Server("weather")
    calls = []

    @server.list_tools()
    async def list_tools():
        capabilities = server.request_context.session.client_params.capabilities.model_dump()
        assert ("io.modelcontextprotocol/ui" in capabilities.get("extensions", {})) is apps_enabled
        return [
            types.Tool(name="dashboard", inputSchema={}, _meta={"ui": {"resourceUri": _URI}}),
            types.Tool(name="filter", inputSchema={}, _meta={"ui": {"visibility": ["app"]}}),
            types.Tool(name="not_enabled", inputSchema={}),
        ]

    @server.read_resource()
    async def read_resource(uri):
        assert str(uri) == _URI
        return [ReadResourceContents(content="<h1>Weather</h1>", mime_type=_MIME)]

    @server.call_tool()
    async def call_tool(name, arguments):
        calls.append((name, arguments))
        return types.CallToolResult(content=[types.TextContent(type="text", text="OK")])

    @asynccontextmanager
    async def memory_stdio(_params):
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(
                    server.run, *server_streams, server.create_initialization_options(),
                )
                try:
                    yield client_streams
                finally:
                    group.cancel_scope.cancel()

    monkeypatch.setattr("mcp.client.stdio.stdio_client", memory_stdio)
    registry = ToolRegistry()
    servers = {
        "weather": MCPServerConfig(command="synthetic", enabled_tools=["dashboard", "filter"]),
    }
    provider = MCPProvider(
        servers, registry, server_loader=lambda: (servers, NetworkConfig()),
    )
    provider.mcp_apps_enabled = apps_enabled
    await provider.connect()
    try:
        wrapper = registry.get("mcp_weather_dashboard")
        assert isinstance(wrapper, MCPToolWrapper)
        assert not registry.has("mcp_weather_filter")
        assert not registry.has("mcp_weather_not_enabled")
        app = wrapper.open_app(authorize=AsyncMock(return_value=True))
        assert (await app.read_resource()).html == "<h1>Weather</h1>"
        assert (await app.call_tool("filter", {"region": "north"})).isError is False
        with pytest.raises(PermissionError):
            await app.call_tool("not_enabled", {})
        assert calls == [("filter", {"region": "north"})]
        servers = {
            "weather": MCPServerConfig(
                command="synthetic-reloaded", enabled_tools=["dashboard", "filter"],
            ),
        }
        assert (await provider.reload())["ok"] is True
        with pytest.raises(RuntimeError, match="closed"):
            await app.read_resource()
        reloaded = registry.get("mcp_weather_dashboard")
        assert isinstance(reloaded, MCPToolWrapper)
        app = reloaded.open_app(authorize=AsyncMock(return_value=True))
        assert (await app.read_resource()).html == "<h1>Weather</h1>"
    finally:
        await provider.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await app.read_resource()
