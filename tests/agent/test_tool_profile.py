from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus


def _make_loop(tmp_path, *, tool_profile: str = "default") -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"):
        return AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            tool_profile=tool_profile,
        )


def test_safe_tool_profile_filters_mutating_and_shell_tools(tmp_path) -> None:
    loop = _make_loop(tmp_path, tool_profile="safe")

    assert "read_file" in loop.tools.tool_names
    assert "list_dir" in loop.tools.tool_names
    assert "web_search" in loop.tools.tool_names
    assert "web_fetch" in loop.tools.tool_names
    assert "message" in loop.tools.tool_names

    assert "exec" not in loop.tools.tool_names
    assert "write_file" not in loop.tools.tool_names
    assert "edit_file" not in loop.tools.tool_names
    assert "spawn" not in loop.tools.tool_names


def test_default_tool_profile_keeps_exec_tool(tmp_path) -> None:
    loop = _make_loop(tmp_path, tool_profile="default")
    assert "exec" in loop.tools.tool_names


@pytest.mark.asyncio
async def test_safe_tool_profile_skips_mcp_connection(tmp_path, monkeypatch) -> None:
    loop = _make_loop(tmp_path, tool_profile="safe")
    loop._mcp_servers = {"demo": {"command": "fake"}}

    connect_mock = AsyncMock()
    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", connect_mock)

    await loop._connect_mcp()

    connect_mock.assert_not_called()
