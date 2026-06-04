"""Tests for SubagentManager."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import LLMProvider


class _FakeTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "fake tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **_kwargs: Any) -> str:
        return "ok"


@pytest.mark.asyncio
async def test_subagent_uses_tool_loader():
    """Verify subagent registers tools via ToolLoader, not hard-coded imports."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        provider=provider,
        workspace=Path("/tmp"),
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
    )
    tools = sm._build_tools()
    assert tools.has("read_file")
    assert tools.has("write_file")
    assert not tools.has("message")
    assert not tools.has("spawn")


@pytest.mark.asyncio
async def test_subagent_build_tools_isolates_file_read_state(tmp_path):
    """Each spawned subagent needs a fresh file-state cache."""
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
    )

    first_read = sm._build_tools().get("read_file")
    second_read = sm._build_tools().get("read_file")

    assert first_read is not second_read
    assert (await first_read.execute(path="note.txt")).startswith("1| hello")
    second_result = await second_read.execute(path="note.txt")
    assert second_result.startswith("1| hello")
    assert "File unchanged" not in second_result


def test_subagent_does_not_inherit_parent_mcp_tools_by_default(tmp_path):
    """Subagents keep MCP access disabled unless explicitly configured."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    parent_tools = ToolRegistry()
    parent_tools.register(_FakeTool("mcp_test_demo"))
    sm = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
        parent_tools=parent_tools,
    )

    tools = sm._build_tools()

    assert not tools.has("mcp_test_demo")


def test_subagent_inherits_only_parent_mcp_tools_when_enabled(tmp_path):
    """The opt-in shares connected MCP wrappers without copying non-MCP parent tools."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    parent_tools = ToolRegistry()
    mcp_tool = _FakeTool("mcp_test_demo")
    parent_tools.register(mcp_tool)
    parent_tools.register(_FakeTool("parent_only"))
    sm = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
        tools_config=ToolsConfig(subagent_mcp_access=True),
        parent_tools=parent_tools,
    )

    tools = sm._build_tools()

    assert tools.get("mcp_test_demo") is mcp_tool
    assert not tools.has("parent_only")
