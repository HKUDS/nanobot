"""Tests for MemorySearchTool interface and output format."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.tools.memory import MemorySearchTool
from nanobot.agent.memory import MemoryStore, SearchResult


def _make_tool(search_results=None):
    """Create a MemorySearchTool with a mocked store."""
    store = MagicMock(spec=MemoryStore)
    store.search = AsyncMock(return_value=search_results or [])
    return MemorySearchTool(memory_store=store, max_results=5), store


# ============================================================================
# Tool schema
# ============================================================================


def test_tool_schema():
    """Tool has correct name, description, and parameter schema."""
    tool, _ = _make_tool()

    assert tool.name == "memory_search"
    assert "memory" in tool.description.lower()

    schema = tool.parameters
    assert schema["type"] == "object"
    assert "query" in schema["properties"]
    assert "query" in schema["required"]

    # Validate it produces valid OpenAI function schema
    fn_schema = tool.to_schema()
    assert fn_schema["type"] == "function"
    assert fn_schema["function"]["name"] == "memory_search"


def test_tool_validate_params():
    """Parameter validation works correctly."""
    tool, _ = _make_tool()

    # Missing required query
    errors = tool.validate_params({})
    assert any("query" in e for e in errors)

    # Valid params
    errors = tool.validate_params({"query": "test"})
    assert errors == []

    # max_results out of range
    errors = tool.validate_params({"query": "test", "max_results": 0})
    assert any("max_results" in e for e in errors)

    errors = tool.validate_params({"query": "test", "max_results": 25})
    assert any("max_results" in e for e in errors)


# ============================================================================
# Tool execution
# ============================================================================


async def test_tool_execute_with_results():
    """Tool formats search results correctly."""
    results = [
        SearchResult(
            text="- [preference] User prefers Python",
            path="/workspace/memory/MEMORY.md",
            start_line=5, end_line=5,
            score=0.85, section="## Preferences",
        ),
        SearchResult(
            text="Discussed Python vs JavaScript for the new project.",
            path="/workspace/memory/2026-02-08.md",
            start_line=3, end_line=5,
            score=0.62,
        ),
    ]
    tool, store = _make_tool(search_results=results)

    output = await tool.execute(query="Python")

    assert "Found 2 result(s)" in output
    assert "score: 0.85" in output
    assert "MEMORY.md" in output
    assert "score: 0.62" in output
    assert "2026-02-08" in output
    assert "User prefers Python" in output

    store.search.assert_called_once_with("Python", max_results=5)


async def test_tool_execute_no_results():
    """Tool returns appropriate message when no results found."""
    tool, _ = _make_tool(search_results=[])

    output = await tool.execute(query="quantum computing")

    assert "No memories found" in output
    assert "quantum computing" in output


async def test_tool_execute_custom_max_results():
    """Tool passes custom max_results to store."""
    tool, store = _make_tool()

    await tool.execute(query="test", max_results=3)

    store.search.assert_called_once_with("test", max_results=3)


async def test_tool_execute_long_snippet_truncated():
    """Long text in results is truncated to 300 chars."""
    long_text = "x" * 500
    results = [
        SearchResult(
            text=long_text,
            path="/workspace/memory/MEMORY.md",
            start_line=1, end_line=1,
            score=0.5,
        ),
    ]
    tool, _ = _make_tool(search_results=results)

    output = await tool.execute(query="test")

    # Should be truncated with "..."
    assert "..." in output
    # Should not contain the full 500 chars
    assert long_text not in output
