from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.tool_search import ToolSearchTool


class _DummyTool(Tool):
    def __init__(self, name: str, description: str):
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


@pytest.mark.asyncio
async def test_tool_search_returns_ranked_matches() -> None:
    registry = ToolRegistry()
    registry.register(_DummyTool("read_file", "Read text from a file path"))
    registry.register(_DummyTool("web_search", "Search the web"))
    registry.register(_DummyTool("exec", "Run shell command"))

    tool = ToolSearchTool(registry)
    result = await tool.execute(query="read file")

    assert "Top tools for 'read file':" in result
    assert "read_file" in result


@pytest.mark.asyncio
async def test_tool_search_respects_max_results() -> None:
    registry = ToolRegistry()
    registry.register(_DummyTool("read_file", "Read files"))
    registry.register(_DummyTool("write_file", "Write files"))
    registry.register(_DummyTool("edit_file", "Edit files"))

    tool = ToolSearchTool(registry)
    result = await tool.execute(query="file", max_results=2)
    lines = [line for line in result.splitlines() if line[:1].isdigit()]

    assert len(lines) == 2


@pytest.mark.asyncio
async def test_tool_search_returns_help_when_no_matches() -> None:
    registry = ToolRegistry()
    registry.register(_DummyTool("web_fetch", "Fetch URL content"))

    tool = ToolSearchTool(registry)
    result = await tool.execute(query="database migrations")

    assert "No matching tools found" in result
