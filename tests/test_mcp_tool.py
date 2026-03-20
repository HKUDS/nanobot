from __future__ import annotations

import asyncio
import sys
import types
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from nanobot.agent.tools.mcp import MCPToolWrapper, connect_mcp_servers
from nanobot.agent.tools.registry import ToolRegistry


class _FakeText:
    def __init__(self, text: str) -> None:
        self.text = text


def _install_fake_mcp(monkeypatch: pytest.MonkeyPatch, *, tools: list[SimpleNamespace]) -> None:
    mcp_mod = types.ModuleType("mcp")
    mcp_types_mod = types.ModuleType("mcp.types")
    mcp_types_mod.TextContent = _FakeText
    mcp_mod.types = mcp_types_mod

    class _Params:
        def __init__(self, command: str, args: list[str] | None = None, env: dict | None = None):
            self.command = command
            self.args = args
            self.env = env

    class _Session:
        def __init__(self, _read: object, _write: object):
            self._closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            self._closed = True
            return False

        async def initialize(self) -> None:
            return None

        async def list_tools(self):
            return SimpleNamespace(tools=tools)

    mcp_mod.StdioServerParameters = _Params
    mcp_mod.ClientSession = _Session

    mcp_client_mod = types.ModuleType("mcp.client")
    mcp_stdio_mod = types.ModuleType("mcp.client.stdio")
    mcp_http_mod = types.ModuleType("mcp.client.streamable_http")

    @asynccontextmanager
    async def _stdio_client(_params):
        yield ("read", "write")

    @asynccontextmanager
    async def _stream_client(_url: str, http_client: object | None = None):
        assert http_client is not None
        yield ("read", "write", object())

    mcp_stdio_mod.stdio_client = _stdio_client
    mcp_http_mod.streamable_http_client = _stream_client

    monkeypatch.setitem(sys.modules, "mcp", mcp_mod)
    monkeypatch.setitem(sys.modules, "mcp.types", mcp_types_mod)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", mcp_stdio_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", mcp_http_mod)


async def test_mcp_wrapper_execute_success_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_def = SimpleNamespace(name="echo", description="Echo", inputSchema={"type": "object"})

    class _Session:
        async def call_tool(self, _name: str, arguments: dict):
            return SimpleNamespace(content=[_FakeText(arguments["x"]), 7])

    mcp_types_mod = types.ModuleType("mcp.types")
    mcp_types_mod.TextContent = _FakeText
    mcp_mod = types.ModuleType("mcp")
    mcp_mod.types = mcp_types_mod
    monkeypatch.setitem(sys.modules, "mcp", mcp_mod)
    monkeypatch.setitem(sys.modules, "mcp.types", mcp_types_mod)

    wrapper = MCPToolWrapper(_Session(), "demo", tool_def, tool_timeout=1)
    out = await wrapper.execute(x="hello")
    assert out.output == "hello\n7"  # type: ignore[union-attr]
    assert out.success is True  # type: ignore[union-attr]

    class _SlowSession:
        async def call_tool(self, _name: str, arguments: dict):
            await asyncio.sleep(0.05)
            return SimpleNamespace(content=[_FakeText(arguments["x"])])

    slow_wrapper = MCPToolWrapper(_SlowSession(), "demo", tool_def, tool_timeout=0)
    timeout_out = await slow_wrapper.execute(x="x")
    assert not timeout_out.success  # type: ignore[union-attr]
    assert "timed out" in (timeout_out.error or "")  # type: ignore[union-attr]


async def test_connect_mcp_servers_command_url_skip_and_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = [SimpleNamespace(name="t1", description="d", inputSchema={"type": "object"})]
    _install_fake_mcp(monkeypatch, tools=tools)

    registry = ToolRegistry()

    class _Cfg(SimpleNamespace):
        pass

    mcp_servers = {
        "cmd": _Cfg(command="srv", args=["--x"], env={}, url=None, headers=None, tool_timeout=5),
        "http": _Cfg(
            command=None, args=None, env=None, url="https://x", headers={}, tool_timeout=7
        ),
        "skip": _Cfg(command=None, args=None, env=None, url=None, headers=None, tool_timeout=3),
    }

    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        await connect_mcp_servers(mcp_servers, registry, stack)

    names = {t.name for t in registry._tools.values()}
    assert "mcp_cmd_t1" in names
    assert "mcp_http_t1" in names

    async def _boom_stdio(_params):
        raise RuntimeError("boom")
        yield

    monkeypatch.setattr(sys.modules["mcp.client.stdio"], "stdio_client", _boom_stdio)
    async with AsyncExitStack() as stack:
        await connect_mcp_servers(
            {
                "bad": _Cfg(
                    command="srv",
                    args=[],
                    env={},
                    url=None,
                    headers=None,
                    tool_timeout=1,
                )
            },
            registry,
            stack,
        )
