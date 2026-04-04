from __future__ import annotations

import asyncio
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from types import ModuleType, SimpleNamespace

import pytest

from janniebot.agent.tools.mcp import MCPToolWrapper, connect_mcp_servers
from janniebot.agent.tools.registry import ToolRegistry
from janniebot.config.schema import MCPServerConfig


class _FakeTextContent:
    def __init__(self, text: str) -> None:
        self.text = text


@pytest.fixture
def fake_mcp_runtime() -> dict[str, object | None]:
    return {"session": None}


@pytest.fixture(autouse=True)
def _fake_mcp_module(
    monkeypatch: pytest.MonkeyPatch, fake_mcp_runtime: dict[str, object | None]
) -> None:
    mod = ModuleType("mcp")
    mod.types = SimpleNamespace(TextContent=_FakeTextContent)

    class _FakeStdioServerParameters:
        def __init__(self, command: str, args: list[str], env: dict | None = None) -> None:
            self.command = command
            self.args = args
            self.env = env

    class _FakeClientSession:
        def __init__(self, _read: object, _write: object) -> None:
            self._session = fake_mcp_runtime["session"]

        async def __aenter__(self) -> object:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    @asynccontextmanager
    async def _fake_stdio_client(_params: object):
        yield object(), object()

    @asynccontextmanager
    async def _fake_sse_client(_url: str, httpx_client_factory=None):
        yield object(), object()

    @asynccontextmanager
    async def _fake_streamable_http_client(_url: str, http_client=None):
        yield object(), object(), object()

    mod.ClientSession = _FakeClientSession
    mod.StdioServerParameters = _FakeStdioServerParameters
    monkeypatch.setitem(sys.modules, "mcp", mod)

    client_mod = ModuleType("mcp.client")
    stdio_mod = ModuleType("mcp.client.stdio")
    stdio_mod.stdio_client = _fake_stdio_client
    sse_mod = ModuleType("mcp.client.sse")
    sse_mod.sse_client = _fake_sse_client
    streamable_http_mod = ModuleType("mcp.client.streamable_http")
    streamable_http_mod.streamable_http_client = _fake_streamable_http_client

    monkeypatch.setitem(sys.modules, "mcp.client", client_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.sse", sse_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_http_mod)


def _make_wrapper(session: object, *, timeout: float = 0.1) -> MCPToolWrapper:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={"type": "object", "properties": {}},
    )
    return MCPToolWrapper(session, "test", tool_def, tool_timeout=timeout)


def test_wrapper_preserves_non_nullable_unions() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "value": {
                    "anyOf": [{"type": "string"}, {"type": "integer"}],
                }
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["value"]["anyOf"] == [
        {"type": "string"},
        {"type": "integer"},
    ]


def test_wrapper_normalizes_nullable_property_type_union() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["name"] == {"type": "string", "nullable": True}


def test_wrapper_normalizes_nullable_property_anyof() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "optional name",
                },
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["name"] == {
        "type": "string",
        "description": "optional name",
        "nullable": True,
    }


@pytest.mark.asyncio
async def test_execute_returns_text_blocks() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        assert arguments == {"value": 1}
        return SimpleNamespace(content=[_FakeTextContent("hello"), 42])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute(value=1)

    assert result == "hello\n42"


@pytest.mark.asyncio
async def test_execute_returns_timeout_message() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        await asyncio.sleep(1)
        return SimpleNamespace(content=[])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool), timeout=0.01)

    result = await wrapper.execute()

    assert result == "(MCP tool call timed out after 0.01s)"


@pytest.mark.asyncio
async def test_execute_handles_server_cancelled_error() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        raise asyncio.CancelledError()

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute()

    assert result == "(MCP tool call was cancelled)"


@pytest.mark.asyncio
async def test_execute_re_raises_external_cancellation() -> None:
    started = asyncio.Event()

    async def call_tool(_name: str, arguments: dict) -> object:
        started.set()
        await asyncio.sleep(60)
        return SimpleNamespace(content=[])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool), timeout=10)
    task = asyncio.create_task(wrapper.execute())
    await asyncio.wait_for(started.wait(), timeout=1.0)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_execute_handles_generic_exception() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        raise RuntimeError("boom")

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute()

    assert result == "(MCP tool call failed: RuntimeError)"


def _make_tool_def(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"{name} tool",
        inputSchema={"type": "object", "properties": {}},
    )


def _make_fake_session(tool_names: list[str]) -> SimpleNamespace:
    async def initialize() -> None:
        return None

    async def list_tools() -> SimpleNamespace:
        return SimpleNamespace(tools=[_make_tool_def(name) for name in tool_names])

    return SimpleNamespace(initialize=initialize, list_tools=list_tools)


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_supports_raw_names(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        await connect_mcp_servers(
            {"test": MCPServerConfig(command="fake", enabled_tools=["demo"])},
            registry,
            stack,
        )
    finally:
        await stack.aclose()

    assert registry.tool_names == ["mcp_test_demo"]


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_defaults_to_all(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        await connect_mcp_servers(
            {"test": MCPServerConfig(command="fake")},
            registry,
            stack,
        )
    finally:
        await stack.aclose()

    assert registry.tool_names == ["mcp_test_demo", "mcp_test_other"]


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_supports_wrapped_names(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        await connect_mcp_servers(
            {"test": MCPServerConfig(command="fake", enabled_tools=["mcp_test_demo"])},
            registry,
            stack,
        )
    finally:
        await stack.aclose()

    assert registry.tool_names == ["mcp_test_demo"]


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_empty_list_registers_none(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        await connect_mcp_servers(
            {"test": MCPServerConfig(command="fake", enabled_tools=[])},
            registry,
            stack,
        )
    finally:
        await stack.aclose()

    assert registry.tool_names == []


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_warns_on_unknown_entries(
    fake_mcp_runtime: dict[str, object | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo"])
    registry = ToolRegistry()
    warnings: list[str] = []

    def _warning(message: str, *args: object) -> None:
        warnings.append(message.format(*args))

    monkeypatch.setattr("janniebot.agent.tools.mcp.logger.warning", _warning)

    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        await connect_mcp_servers(
            {"test": MCPServerConfig(command="fake", enabled_tools=["unknown"])},
            registry,
            stack,
        )
    finally:
        await stack.aclose()

    assert registry.tool_names == []
    assert warnings
    assert "enabledTools entries not found: unknown" in warnings[-1]
    assert "Available raw names: demo" in warnings[-1]
    assert "Available wrapped names: mcp_test_demo" in warnings[-1]
