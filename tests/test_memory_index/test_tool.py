from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.tools.memory_search import MemorySearchTool
from nanobot.memory_index.search import SearchResult


def _make_tool(results: list[SearchResult]) -> MemorySearchTool:
    index = MagicMock()
    index.search = AsyncMock(return_value=results)
    return MemorySearchTool(index)


async def test_tool_formats_results():
    results = [
        SearchResult("The user prefers dark mode.", "MEMORY.md", 5, 5, 0.9),
        SearchResult("The user lives in Berlin.", "MEMORY.md", 10, 10, 0.7),
    ]
    tool = _make_tool(results)
    output = await tool.execute(query="preferences")
    assert "MEMORY.md" in output
    assert "dark mode" in output
    assert "Berlin" in output
    assert "---" in output  # separator between results


async def test_tool_returns_no_results_message():
    tool = _make_tool([])
    output = await tool.execute(query="something obscure")
    assert output == "No relevant memory found."


async def test_tool_passes_top_k():
    index = MagicMock()
    index.search = AsyncMock(return_value=[])
    tool = MemorySearchTool(index)
    await tool.execute(query="test", top_k=3)
    index.search.assert_called_once_with("test", top_k=3)


async def test_tool_default_top_k():
    index = MagicMock()
    index.search = AsyncMock(return_value=[])
    tool = MemorySearchTool(index)
    await tool.execute(query="test")
    index.search.assert_called_once_with("test", top_k=5)


def test_tool_schema():
    index = MagicMock()
    tool = MemorySearchTool(index)
    assert tool.name == "memory_search"
    schema = tool.to_schema()
    assert schema["function"]["name"] == "memory_search"
    assert "query" in schema["function"]["parameters"]["properties"]
    assert "query" in schema["function"]["parameters"]["required"]
