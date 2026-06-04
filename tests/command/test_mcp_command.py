"""Tests for the /mcp built-in command."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_mcp, register_builtin_commands
from nanobot.command.router import CommandContext, CommandRouter


def _cfg(transport: str = "stdio") -> SimpleNamespace:
    """Fake MCP server config object (models.MCPServerConfig-compatible shape)."""
    return SimpleNamespace(transport=transport)


def _loop(servers: dict | None = None, stacks: dict | None = None, tool_names: list | None = None):
    """Build a mock loop with the attributes cmd_mcp reads."""
    loop = MagicMock()
    loop._mcp_servers = servers or {}
    loop._mcp_stacks = stacks or {}
    mock_tools = MagicMock()
    mock_tools.tool_names = set(tool_names or [])
    loop.tools = mock_tools
    return loop


def _ctx(loop, raw: str = "/mcp"):
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=raw)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args="", loop=loop)


@pytest.mark.asyncio
async def test_no_servers_configured():
    """When no MCP servers are configured, show a helpful message."""
    loop = _loop()
    out = await cmd_mcp(_ctx(loop))
    assert "No MCP servers configured" in out.content


@pytest.mark.asyncio
async def test_one_connected_server():
    """One configured server that is connected — show it as connected."""
    loop = _loop(
        servers={"github": _cfg("stdio")},
        stacks={"github": MagicMock()},
        tool_names={"mcp_github_search_repos", "mcp_github_list_prs"},
    )
    out = await cmd_mcp(_ctx(loop))
    assert "MCP servers (1/1 connected)" in out.content
    assert "**github** (stdio) [connected]" in out.content
    assert "2 tool(s) (mcp_github_list_prs, mcp_github_search_repos)" in out.content


@pytest.mark.asyncio
async def test_one_offline_server():
    """One configured server that is not connected — show as offline."""
    loop = _loop(
        servers={"database": _cfg("sse")},
        stacks={},
    )
    out = await cmd_mcp(_ctx(loop))
    assert "MCP servers (0/1 connected)" in out.content
    assert "**database** (sse) [offline]" in out.content
    assert "0 tool(s)" in out.content


@pytest.mark.asyncio
async def test_mixed_connected_and_offline():
    """Multiple servers, some connected, some not."""
    loop = _loop(
        servers={
            "github": _cfg("stdio"),
            "database": _cfg("sse"),
            "filesystem": _cfg("stdio"),
        },
        stacks={"github": MagicMock(), "filesystem": MagicMock()},
        tool_names={
            "mcp_github_search_repos", "mcp_github_get_issue",
            "mcp_filesystem_read_file", "mcp_filesystem_write_file",
            "mcp_filesystem_list_dir",
        },
    )
    out = await cmd_mcp(_ctx(loop))
    assert "MCP servers (2/3 connected)" in out.content
    assert "**database** (sse) [offline]" in out.content
    assert "**filesystem** (stdio) [connected]" in out.content
    assert "**github** (stdio) [connected]" in out.content


@pytest.mark.asyncio
async def test_servers_listed_alphabetically():
    """Server names should be sorted."""
    loop = _loop(
        servers={"zzz": _cfg(), "aaa": _cfg(), "mmm": _cfg()},
        stacks={"zzz": MagicMock(), "aaa": MagicMock(), "mmm": MagicMock()},
    )
    out = await cmd_mcp(_ctx(loop))
    lines = out.content.split("\n")
    # Server entries start with "- **"
    server_lines = [line for line in lines if line.startswith("- **")]
    names = [line.split("**")[1] for line in server_lines]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_many_tools_are_truncated():
    """When a server has >5 tools, only list first 3 then '...'."""
    tools = {f"mcp_gh_{i}" for i in range(10)}
    loop = _loop(
        servers={"gh": _cfg()},
        stacks={"gh": MagicMock()},
        tool_names=tools,
    )
    out = await cmd_mcp(_ctx(loop))
    assert "10 tool(s) (mcp_gh_0, mcp_gh_1, mcp_gh_2, ...)" in out.content


@pytest.mark.asyncio
async def test_mcp_command_registered_on_router():
    """/mcp should be routed via the built-in command router."""
    router = CommandRouter()
    register_builtin_commands(router)
    loop = _loop()
    out = await router.dispatch(_ctx(loop, "/mcp"))
    assert out is not None
    assert "No MCP servers configured" in out.content
