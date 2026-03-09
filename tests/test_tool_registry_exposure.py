import sys
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.mcp import connect_mcp_servers
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


class HiddenTool(Tool):
    @property
    def name(self) -> str:
        return "hidden"

    @property
    def description(self) -> str:
        return "hidden tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


def test_registry_hides_inactive_tools_from_active_definitions() -> None:
    reg = ToolRegistry()

    reg.register(HiddenTool(), source="test", active=False)

    assert reg.get_active_definitions() == []
    assert [tool["function"]["name"] for tool in reg.get_definitions()] == ["hidden"]


def test_registry_default_registration_remains_active_and_visible_everywhere() -> None:
    reg = ToolRegistry()

    reg.register(HiddenTool())

    assert [tool["function"]["name"] for tool in reg.get_definitions()] == ["hidden"]
    assert [tool["function"]["name"] for tool in reg.get_active_definitions()] == ["hidden"]


async def test_inactive_registered_tool_remains_executable() -> None:
    reg = ToolRegistry()

    reg.register(HiddenTool(), source="test", active=False)

    assert await reg.execute("hidden", {}) == "ok"


def test_registry_can_activate_and_deactivate_registered_tools() -> None:
    reg = ToolRegistry()

    reg.register(HiddenTool(), source="test", active=False)

    assert reg.activate("hidden") is True
    assert [tool["function"]["name"] for tool in reg.get_active_definitions()] == ["hidden"]
    assert reg.deactivate("hidden") is True
    assert reg.get_active_definitions() == []


def test_registry_entries_include_source_metadata() -> None:
    reg = ToolRegistry()

    reg.register(HiddenTool(), source="test", active=False)

    entry = reg.get_entry("hidden")
    assert entry is not None
    assert entry.source == "test"
    assert entry.active is False


def test_default_tools_are_registered_with_builtin_source(tmp_path, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    expected_names = {
        "read_file",
        "write_file",
        "edit_file",
        "list_dir",
        "exec",
        "web_search",
        "web_fetch",
        "message",
        "spawn",
    }

    original_register = ToolRegistry.register

    def capture_register(self, tool: Tool, *, source: str, active: bool = True) -> None:
        calls.append((tool.name, source))
        original_register(self, tool, source=source, active=active)

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    monkeypatch.setattr(ToolRegistry, "register", capture_register)

    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")

    builtin_names = {name for name, source in calls if source == "builtin"}

    assert all(loop.tools.get_entry(name) is not None for name in expected_names)
    assert builtin_names == expected_names


def test_registry_preserves_mcp_source_metadata() -> None:
    reg = ToolRegistry()

    reg.register(HiddenTool(), source="mcp:filesystem", active=True)

    entry = reg.get_entry("hidden")
    assert entry is not None
    assert entry.source == "mcp:filesystem"


@pytest.mark.asyncio
async def test_connect_mcp_servers_registers_mcp_source_metadata(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    original_register = ToolRegistry.register

    def capture_register(self, tool: Tool, *, source: str, active: bool = True) -> None:
        calls.append((tool.name, source))
        original_register(self, tool, source=source, active=active)

    class FakeClientSession:
        def __init__(self, read: object, write: object):
            self.read = read
            self.write = write

        async def __aenter__(self) -> "FakeClientSession":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def initialize(self) -> None:
            return None

        async def list_tools(self) -> SimpleNamespace:
            tool_def = SimpleNamespace(
                name="list_files",
                description="List files",
                inputSchema={"type": "object", "properties": {}},
            )
            return SimpleNamespace(tools=[tool_def])

    @asynccontextmanager
    async def fake_stdio_client(params: object):
        yield object(), object()

    monkeypatch.setattr(ToolRegistry, "register", capture_register)

    mcp_module = ModuleType("mcp")
    setattr(mcp_module, "ClientSession", FakeClientSession)
    setattr(mcp_module, "StdioServerParameters", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)

    stdio_module = ModuleType("mcp.client.stdio")
    setattr(stdio_module, "stdio_client", fake_stdio_client)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio_module)

    sse_module = ModuleType("mcp.client.sse")
    setattr(sse_module, "sse_client", None)
    monkeypatch.setitem(sys.modules, "mcp.client.sse", sse_module)

    streamable_http_module = ModuleType("mcp.client.streamable_http")
    setattr(streamable_http_module, "streamable_http_client", None)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_http_module)

    registry = ToolRegistry()
    cfg = SimpleNamespace(
        type="stdio",
        command="server",
        args=[],
        env=None,
        url=None,
        headers=None,
        tool_timeout=30,
    )

    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        await connect_mcp_servers({"filesystem": cfg}, registry, stack)

    assert calls == [("mcp_filesystem_list_files", "mcp:filesystem")]


@pytest.mark.asyncio
async def test_subagent_registers_builtin_tools_with_builtin_source(tmp_path, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    expected_names = {
        "read_file",
        "write_file",
        "edit_file",
        "list_dir",
        "exec",
        "web_search",
        "web_fetch",
    }

    original_register = ToolRegistry.register

    def capture_register(self, tool: Tool, *, source: str, active: bool = True) -> None:
        calls.append((tool.name, source))
        original_register(self, tool, source=source, active=active)

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))

    manager = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test-model",
    )
    manager._announce_result = AsyncMock()

    monkeypatch.setattr(ToolRegistry, "register", capture_register)

    await manager._run_subagent(
        "task1", "do the thing", "label", {"channel": "cli", "chat_id": "direct"}
    )

    builtin_names = {name for name, source in calls if source == "builtin"}

    assert builtin_names == expected_names


@pytest.mark.asyncio
async def test_run_agent_loop_only_sends_active_tools(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.tools.register(HiddenTool(), source="test", active=False)

    await loop._run_agent_loop([{"role": "user", "content": "hi"}])

    tool_names = [tool["function"]["name"] for tool in provider.chat.await_args.kwargs["tools"]]
    assert "hidden" not in tool_names


@pytest.mark.asyncio
async def test_run_subagent_uses_active_definitions(tmp_path, monkeypatch) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))

    manager = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test-model",
    )
    manager._announce_result = AsyncMock()

    active_calls: list[int] = []
    original_get_active_definitions = ToolRegistry.get_active_definitions

    def fail_get_definitions(self) -> list[dict[str, Any]]:
        raise AssertionError("subagent runtime should use get_active_definitions")

    def record_get_active_definitions(self) -> list[dict[str, Any]]:
        active_calls.append(1)
        return original_get_active_definitions(self)

    monkeypatch.setattr(ToolRegistry, "get_definitions", fail_get_definitions)
    monkeypatch.setattr(ToolRegistry, "get_active_definitions", record_get_active_definitions)

    await manager._run_subagent(
        "task1", "do the thing", "label", {"channel": "cli", "chat_id": "direct"}
    )

    assert active_calls == [1]
    assert provider.chat.await_count == 1
    manager._announce_result.assert_awaited_once()
    announce_args = manager._announce_result.await_args
    assert announce_args is not None
    assert announce_args.args[-1] == "ok"
