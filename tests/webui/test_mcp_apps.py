"""Gateway-local app handles never authorize an iframe to approve itself."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp import types
from websockets.asyncio.client import connect
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Request

from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.agent.tools.mcp_apps import MCPAppServer
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.events import EventSink
from nanobot.providers.base import ToolCallRequest
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.mcp_apps import WebUIMCPApps


@pytest.fixture
async def apps():
    definition = types.Tool(name="dashboard", inputSchema={}, _meta={"ui": {"resourceUri": "ui://weather/view"}})
    filter_tool = types.Tool(name="filter", inputSchema={}, _meta={"ui": {"visibility": ["app"]}})
    session = AsyncMock()
    session.read_resource.return_value = types.ReadResourceResult(contents=[types.TextResourceContents(
        uri="ui://weather/view", mimeType="text/html;profile=mcp-app", text="<h1>Weather</h1>",
    )])
    session.call_tool.return_value = types.CallToolResult(
        content=[types.TextContent(type="text", text="Weather")],
        structuredContent={"temperature": 23}, _meta={"private": "only-for-app"},
    )
    server = MCPAppServer(session, "weather", {"dashboard": definition, "filter": filter_tool})
    wrapper = MCPToolWrapper(session, "weather", definition, app_server=server)
    manager = WebUIMCPApps()
    manager.enabled = True
    emitted = []

    async def emit(event):
        emitted.append(event)

    hook = manager.hook(AgentTurnHookContext(
        channel="websocket", session_key="websocket:chat-a", events=EventSink(publish=emit),
    ))
    result = await wrapper.execute()
    session.call_tool.reset_mock()
    await hook.after_execute_tool(
        AgentHookContext(iteration=1, messages=[]),
        ToolCallRequest(id="call-1", name=wrapper.name, arguments={}), wrapper, {}, result,
    )
    embed = emitted[0].tool_events[0]["embeds"][0]
    yield manager, {"app_id": embed["app_id"], "session_key": "websocket:chat-a"}, session, server
    server.close()


async def test_app_result_is_private_and_cross_session_handles_are_rejected(apps):
    manager, scope, session, _server = apps
    with pytest.raises(LookupError):
        await manager.action("open", {**scope, "session_key": "websocket:other"})
    session.read_resource.assert_not_awaited()

    opened = await manager.action("open", scope)
    assert opened["result"]["structuredContent"] == {"temperature": 23}
    assert opened["result"]["_meta"] == {"private": "only-for-app"}
    assert opened["html"] == "<h1>Weather</h1>"


@pytest.mark.parametrize("approved", [True, False])
async def test_app_calls_require_a_one_use_host_approval(apps, approved):
    manager, scope, session, _server = apps
    with pytest.raises(PermissionError):
        await manager.action("confirm", {**scope, "approval_id": "made-up", "approved": True})
    prepared = await manager.action("prepare", {**scope, "name": "filter", "arguments": {"region": "north"}})
    session.call_tool.assert_not_awaited()

    response = await manager.action("confirm", {**scope, **prepared, "approved": approved,
                                               "arguments": {"region": "tampered"}})
    if approved:
        session.call_tool.assert_awaited_once_with("filter", arguments={"region": "north"})
        assert response["structuredContent"] == {"temperature": 23}
    else:
        session.call_tool.assert_not_awaited()
        assert response["isError"] is True
    with pytest.raises(PermissionError):
        await manager.action("confirm", {**scope, **prepared, "approved": True})


async def test_app_prepare_never_bypasses_the_originating_catalog(apps):
    manager, scope, session, _server = apps
    with pytest.raises(PermissionError):
        await manager.action("prepare", {**scope, "name": "other_server_tool"})
    session.call_tool.assert_not_awaited()


async def test_expiration_revokes_pending_approvals(apps, monkeypatch):
    manager, scope, session, _server = apps
    prepared = await manager.action("prepare", {**scope, "name": "filter"})
    monkeypatch.setattr("nanobot.webui.mcp_apps.time.monotonic", lambda: float("inf"))
    with pytest.raises(LookupError):
        await manager.action("confirm", {**scope, **prepared, "approved": True})
    session.call_tool.assert_not_awaited()


def test_disabled_hosts_and_other_channels_do_not_capture_apps():
    manager = WebUIMCPApps()
    assert manager.hook(AgentTurnHookContext(channel="websocket", session_key="websocket:a")) is None
    manager.enabled = True
    assert manager.hook(AgentTurnHookContext(channel="cli", session_key="cli:a")) is None


async def test_public_gateway_routes_require_authenticated_socket_and_opt_in(apps, tmp_path, monkeypatch):
    manager, scope, session, _server = apps
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    config = WebSocketConfig(mcp_apps_enabled=True)
    gateway = build_gateway_services(
        config=config, bus=MessageBus(), session_manager=None, static_dist_path=None,
        workspace_path=tmp_path, default_restrict_to_workspace=True, config_path=tmp_path / "config.json",
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None,
        mcp_apps_action=manager.action,
    )
    connection = SimpleNamespace(request=Request("/", Headers()), remote_address=("127.0.0.1", 50000))
    blocked = await gateway.http.dispatch(connection, Request("/api/webui/mcp-apps/confirm", Headers()))
    assert blocked.status_code == 405
    session.call_tool.assert_not_awaited()
    response = await gateway.http.dispatch_webui_mutation(connection, "mcp_apps.open", scope)
    assert response.status_code == 200
    assert json.loads(response.body)["result"]["structuredContent"] == {"temperature": 23}
    gateway.http.config.mcp_apps_enabled = False
    blocked = await gateway.http.dispatch_webui_mutation(connection, "mcp_apps.open", scope)
    assert blocked.status_code == 404


async def test_live_websocket_approval_and_replay_do_not_repeat_tool_calls(apps, tmp_path, monkeypatch):
    manager, scope, session, _server = apps
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    config = WebSocketConfig(port=0, mcp_apps_enabled=True)
    bus = MessageBus()
    gateway = build_gateway_services(
        config=config, bus=bus, session_manager=None, static_dist_path=None,
        workspace_path=tmp_path, default_restrict_to_workspace=True, config_path=tmp_path / "config.json",
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None,
        mcp_apps_action=manager.action,
    )
    channel = WebSocketChannel(config, bus, gateway=gateway)
    serving = asyncio.create_task(channel.start())
    try:
        async with asyncio.timeout(3):
            while channel._server is None:
                await asyncio.sleep(0.01)
        port = channel._server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}/?terminal_protocol=1&terminal_instance={gateway.tokens.instance_id}"
        with pytest.raises(InvalidStatus):
            async with connect(url):
                pass
        token = gateway.tokens.issue_token(300, audience="webui")
        async with connect(f"{url}&token={token}") as socket:
            ready = json.loads(await socket.recv())
            assert "webui.mcp-apps.v1" in ready["terminal"]["webui"]["capabilities"]

            async def request(request_id, action, payload):
                await socket.send(json.dumps({"type": "webui_request", "request_id": request_id,
                                               "action": action, "payload": payload}))
                async with asyncio.timeout(3):
                    while True:
                        response = json.loads(await socket.recv())
                        if response.get("request_id") == request_id:
                            return response

            opened = await request("open-1", "mcp_apps.open", scope)
            assert opened["ok"] is True
            assert opened["result"]["result"]["structuredContent"] == {"temperature": 23}
            prepared = await request("prepare-1", "mcp_apps.prepare", {**scope, "name": "filter"})
            session.call_tool.assert_not_awaited()
            confirmation = {**scope, "approval_id": prepared["result"]["approval_id"], "approved": True}
            first = await request("confirm-1", "mcp_apps.confirm", confirmation)
            replay = await request("confirm-1", "mcp_apps.confirm", confirmation)
            assert first["ok"] is replay["ok"] is True
            assert first["result"] == replay["result"]
            session.call_tool.assert_awaited_once_with("filter", arguments={})
    finally:
        await channel.stop()
        await serving
