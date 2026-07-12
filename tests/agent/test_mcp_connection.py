"""Tests for MCP connection lifecycle in AgentLoop."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anyio
import pytest
from mcp import types as mcp_types
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.types import ErrorData

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools import mcp as mcp_runtime
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.mcp import MCPResourceWrapper, MCPToolWrapper
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import MCPServerConfig


def _mcp_notification(method: str, params: dict[str, Any] | None = None) -> SessionMessage:
    return SessionMessage(
        message=mcp_types.JSONRPCMessage(
            mcp_types.JSONRPCNotification(
                jsonrpc="2.0",
                method=method,
                params=params,
            )
        )
    )


def test_mcp_progress_detection_accepts_flattened_sdk_message_shape():
    malformed = SimpleNamespace(
        message=SimpleNamespace(
            method="notifications/progress",
            params={"progress": 20, "total": 600},
        )
    )
    valid = SimpleNamespace(
        message=SimpleNamespace(
            method="notifications/progress",
            params={"progressToken": "req-1", "progress": 25},
        )
    )

    assert mcp_runtime._is_malformed_mcp_progress_notification(malformed) is True
    assert mcp_runtime._is_malformed_mcp_progress_notification(valid) is False


class _FakeMcpTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "fake MCP tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **_kwargs: Any) -> str:
        return "ok"


def _make_loop(tmp_path, *, mcp_servers: dict | None = None) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        mcp_servers=mcp_servers or {"test": object()},
    )


@pytest.mark.asyncio
async def test_mcp_read_filter_drops_progress_notifications_without_progress_token():
    send, receive = anyio.create_memory_object_stream(4)
    malformed_progress = _mcp_notification(
        "notifications/progress",
        {"progress": 20, "total": 600, "message": "Polling"},
    )
    tool_change = _mcp_notification("notifications/tools/list_changed")
    valid_progress = _mcp_notification(
        "notifications/progress",
        {"progressToken": "req-1", "progress": 25, "total": 600, "message": "Polling"},
    )

    await send.send(malformed_progress)
    await send.send(tool_change)
    await send.send(valid_progress)
    await send.aclose()

    wrapped = mcp_runtime._filter_malformed_mcp_progress_notifications(receive, "brightdata")
    forwarded = []
    async with wrapped:
        async for message in wrapped:
            forwarded.append(message)

    assert forwarded == [tool_change, valid_progress]


@pytest.mark.asyncio
async def test_owned_mcp_connection_closes_from_its_owner_task():
    close_requested = asyncio.Event()
    ready = asyncio.Event()
    tasks: dict[str, asyncio.Task] = {}

    async def own_connection() -> None:
        tasks["open"] = asyncio.current_task()  # type: ignore[assignment]
        ready.set()
        await close_requested.wait()
        tasks["close"] = asyncio.current_task()  # type: ignore[assignment]

    owner = asyncio.create_task(own_connection())
    connection = mcp_runtime._OwnedMCPConnection(owner, close_requested)
    await ready.wait()

    await connection.aclose()

    assert tasks["open"] is owner
    assert tasks["close"] is owner
    assert tasks["close"] is not asyncio.current_task()


@pytest.mark.asyncio
async def test_connect_mcp_retries_when_no_servers_connect(tmp_path, monkeypatch: pytest.MonkeyPatch):
    loop = _make_loop(tmp_path)
    attempts = 0

    async def _fake_connect(_servers, _registry):
        nonlocal attempts
        attempts += 1
        return {}

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)

    await loop._connect_mcp()
    await loop._connect_mcp()

    assert attempts == 2
    assert loop._mcp_stacks == {}


@pytest.mark.asyncio
async def test_agent_loop_run_closes_mcp_from_connection_owner_task(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    loop = _make_loop(tmp_path, mcp_servers={"playwright": object()})
    connected = asyncio.Event()
    owner_tasks: list[asyncio.Task | None] = []
    closed_tasks: list[asyncio.Task | None] = []

    class _OwnerCheckedStack:
        def __init__(self) -> None:
            self.owner = asyncio.current_task()
            owner_tasks.append(self.owner)

        async def aclose(self) -> None:
            closed_tasks.append(asyncio.current_task())
            assert asyncio.current_task() is self.owner

    async def _fake_connect(servers, _registry):
        stacks = {name: _OwnerCheckedStack() for name in servers}
        connected.set()
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)

    task = asyncio.create_task(loop.run())
    await asyncio.wait_for(connected.wait(), timeout=1)
    loop.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert owner_tasks
    assert closed_tasks == owner_tasks
    assert loop._mcp_stacks == {}


@pytest.mark.asyncio
async def test_reload_mcp_servers_adds_and_removes_tools_without_restart(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config = load_config()
    config.tools.mcp_servers["browserbase"] = MCPServerConfig(
        type="stdio",
        command="browserbase-mcp",
    )
    save_config(config)

    closed: list[str] = []

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    async def _fake_connect(servers, registry):
        stacks = {}
        for name in servers:
            registry.register(_FakeMcpTool(f"mcp_{name}_navigate"))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stack.push_async_callback(_mark_closed, name)
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)
    loop = _make_loop(tmp_path, mcp_servers={})

    added = await mcp_runtime.reload_servers(loop, loop.tools)

    assert added["ok"] is True
    assert added["added"] == ["browserbase"]
    assert loop.tools.has("mcp_browserbase_navigate")
    assert "browserbase" in loop._mcp_stacks

    config = load_config()
    del config.tools.mcp_servers["browserbase"]
    save_config(config)

    removed = await mcp_runtime.reload_servers(loop, loop.tools)

    assert removed["ok"] is True
    assert removed["removed"] == ["browserbase"]
    assert not loop.tools.has("mcp_browserbase_navigate")
    assert "browserbase" not in loop._mcp_stacks
    assert closed == ["browserbase"]


@pytest.mark.asyncio
async def test_request_mcp_reload_reaches_runtime_control_without_restart(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config = load_config()
    config.tools.mcp_servers["browserbase"] = MCPServerConfig(
        type="stdio",
        command="browserbase-mcp",
    )
    save_config(config)

    closed: list[str] = []

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    async def _fake_connect(servers, registry):
        stacks = {}
        for name in servers:
            registry.register(_FakeMcpTool(f"mcp_{name}_navigate"))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stack.push_async_callback(_mark_closed, name)
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)
    loop = _make_loop(tmp_path, mcp_servers={})

    async def _handle_one_runtime_control() -> None:
        msg = await loop.bus.consume_inbound()
        handled = await mcp_runtime.handle_runtime_control(loop, msg, loop.tools)
        assert handled is True

    consumer = asyncio.create_task(_handle_one_runtime_control())
    result = await mcp_runtime.request_mcp_reload(loop.bus, timeout=2.0)
    await consumer

    assert result["ok"] is True
    assert result["added"] == ["browserbase"]
    assert result["requires_restart"] is False
    assert loop.tools.has("mcp_browserbase_navigate")

    config = load_config()
    del config.tools.mcp_servers["browserbase"]
    save_config(config)

    consumer = asyncio.create_task(_handle_one_runtime_control())
    result = await mcp_runtime.request_mcp_reload(loop.bus, timeout=2.0)
    await consumer

    assert result["ok"] is True
    assert result["removed"] == ["browserbase"]
    assert result["requires_restart"] is False
    assert not loop.tools.has("mcp_browserbase_navigate")
    assert closed == ["browserbase"]


@pytest.mark.asyncio
async def test_reload_mcp_servers_retries_configured_server_without_live_stack(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config = load_config()
    config.tools.mcp_servers["browserbase"] = MCPServerConfig(
        type="stdio",
        command="browserbase-mcp",
    )
    save_config(config)

    async def _fake_connect(servers, registry):
        stacks = {}
        for name in servers:
            registry.register(_FakeMcpTool(f"mcp_{name}_navigate"))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)
    loop = _make_loop(tmp_path, mcp_servers={"browserbase": config.tools.mcp_servers["browserbase"]})

    result = await mcp_runtime.reload_servers(loop, loop.tools)

    assert result["ok"] is True
    assert result["added"] == []
    assert result["changed"] == []
    assert result["retried"] == ["browserbase"]
    assert loop.tools.has("mcp_browserbase_navigate")
    await loop.close_mcp()


@pytest.mark.asyncio
async def test_mcp_tool_reconnects_after_session_terminated(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    loop = _make_loop(tmp_path, mcp_servers={"remote": object()})
    closed: list[str] = []
    sessions: list[Any] = []
    connect_count = 0

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    class _FakeSession:
        def __init__(self, index: int) -> None:
            self.index = index
            self.call_count = 0

        async def call_tool(self, _name: str, arguments: dict[str, Any]) -> Any:
            self.call_count += 1
            assert arguments == {"symbol": "AAPL"}
            if self.index == 1:
                raise McpError(ErrorData(code=-32000, message="Session terminated"))
            return SimpleNamespace(
                content=[mcp_types.TextContent(type="text", text="recovered")]
            )

    async def _fake_connect(servers, registry):
        nonlocal connect_count
        stacks = {}
        for name in servers:
            connect_count += 1
            session = _FakeSession(connect_count)
            sessions.append(session)
            tool_def = SimpleNamespace(
                name="quote",
                description="quote tool",
                inputSchema={"type": "object", "properties": {}},
            )
            registry.register(MCPToolWrapper(session, name, tool_def, tool_timeout=5))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stack.push_async_callback(_mark_closed, name)
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)

    await loop._connect_mcp()
    old_tool = loop.tools.get("mcp_remote_quote")
    assert isinstance(old_tool, MCPToolWrapper)

    output = await old_tool.execute(symbol="AAPL")

    assert output == "recovered"
    assert connect_count == 2
    assert closed == ["remote"]
    assert sessions[0].call_count == 1
    assert sessions[1].call_count == 1
    assert "remote" in loop._mcp_stacks
    assert loop.tools.get("mcp_remote_quote") is not old_tool


@pytest.mark.asyncio
async def test_mcp_reconnect_handler_uses_sanitized_server_prefix(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    loop = _make_loop(tmp_path, mcp_servers={"remote_": object()})
    connect_count = 0

    class _FakeSession:
        def __init__(self, index: int) -> None:
            self.index = index

        async def call_tool(self, _name: str, arguments: dict[str, Any]) -> Any:
            assert arguments == {}
            if self.index == 1:
                raise McpError(ErrorData(code=-32000, message="Session terminated"))
            return SimpleNamespace(
                content=[mcp_types.TextContent(type="text", text="recovered")]
            )

    async def _fake_connect(servers, registry):
        nonlocal connect_count
        stacks = {}
        for name in servers:
            connect_count += 1
            tool_def = SimpleNamespace(
                name="quote",
                description="quote tool",
                inputSchema={"type": "object", "properties": {}},
            )
            registry.register(MCPToolWrapper(_FakeSession(connect_count), name, tool_def))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)

    await loop._connect_mcp()
    old_tool = loop.tools.get("mcp_remote_quote")
    assert isinstance(old_tool, MCPToolWrapper)

    output = await old_tool.execute()

    assert output == "recovered"
    assert connect_count == 2
    assert loop.tools.get("mcp_remote_quote") is not old_tool


@pytest.mark.asyncio
async def test_concurrent_mcp_reconnect_reuses_fresh_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    loop = _make_loop(tmp_path, mcp_servers={"remote": object()})
    closed: list[str] = []
    connect_count = 0

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    class _DeadSession:
        async def read_resource(self, _uri: str) -> Any:
            raise McpError(ErrorData(code=-32000, message="Session terminated"))

    class _LiveSession:
        async def read_resource(self, uri: str) -> Any:
            await asyncio.sleep(0)
            return SimpleNamespace(
                contents=[
                    mcp_types.TextResourceContents(
                        uri=uri,
                        text=f"fresh:{uri.rsplit('/', maxsplit=1)[-1]}",
                    )
                ]
            )

    async def _fake_connect(servers, registry):
        nonlocal connect_count
        stacks = {}
        for name in servers:
            connect_count += 1
            session = _DeadSession() if connect_count == 1 else _LiveSession()
            for resource_name in ("alpha", "beta"):
                resource_def = SimpleNamespace(
                    name=resource_name,
                    uri=f"file:///{resource_name}",
                    description=f"{resource_name} resource",
                )
                registry.register(MCPResourceWrapper(session, name, resource_def))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stack.push_async_callback(_mark_closed, name)
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)

    await loop._connect_mcp()
    old_alpha = loop.tools.get("mcp_remote_resource_alpha")
    old_beta = loop.tools.get("mcp_remote_resource_beta")
    assert isinstance(old_alpha, MCPResourceWrapper)
    assert isinstance(old_beta, MCPResourceWrapper)

    outputs = await asyncio.gather(old_alpha.execute(), old_beta.execute())

    assert outputs == ["fresh:alpha", "fresh:beta"]
    assert connect_count == 2
    assert closed == ["remote"]
