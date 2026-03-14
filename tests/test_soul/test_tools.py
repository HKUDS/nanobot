"""Tests for nanobot.soul.tools module."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch
from datetime import date

from nanobot.soul.tools import (
    MemoryManager,
    MemorySearchTool,
    MemoryGetTool,
    MemoryWriteTool,
    register_memory_tools,
    get_memory_manager,
)
from nanobot.agent.tools.registry import ToolRegistry


@pytest.fixture
def ws_dir(tmp_path):
    """Create a workspace directory with memory subdirectory."""
    ws = tmp_path / "agent"
    ws.mkdir()
    (ws / "memory").mkdir()
    return ws


@pytest.fixture
def manager(ws_dir):
    return MemoryManager(ws_dir)


class TestMemoryManager:
    """Tests for MemoryManager."""

    def test_write_daily_creates_file(self, manager, ws_dir):
        today = date.today().isoformat()
        rel = manager.write_daily("test content", "fact")
        assert rel == f"memory/{today}.md"
        path = ws_dir / "memory" / f"{today}.md"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "test content" in content
        assert "fact" in content

    def test_write_daily_appends(self, manager, ws_dir):
        manager.write_daily("first entry", "fact")
        manager.write_daily("second entry", "decision")
        today = date.today().isoformat()
        content = (ws_dir / "memory" / f"{today}.md").read_text(encoding="utf-8")
        assert "first entry" in content
        assert "second entry" in content

    def test_read_file_success(self, manager, ws_dir):
        (ws_dir / "MEMORY.md").write_text("line1\nline2\nline3", encoding="utf-8")
        result = manager.read_file("MEMORY.md")
        assert result["text"] == "line1\nline2\nline3"
        assert result["path"] == "MEMORY.md"
        assert "error" not in result

    def test_read_file_with_line_range(self, manager, ws_dir):
        (ws_dir / "MEMORY.md").write_text("line1\nline2\nline3\nline4", encoding="utf-8")
        result = manager.read_file("MEMORY.md", from_line=2, n_lines=2)
        assert result["text"] == "line2\nline3"

    def test_read_file_access_denied(self, manager):
        result = manager.read_file("../secret.txt")
        assert result["error"] == "Access denied"

    def test_read_file_not_found(self, manager):
        result = manager.read_file("MEMORY.md")
        assert "Not found" in result["error"]

    def test_read_file_rejects_traversal(self, manager):
        result = manager.read_file("memory/../../etc/passwd")
        assert result["error"] == "Access denied"

    def test_read_file_allows_memory_subdir(self, manager, ws_dir):
        (ws_dir / "memory" / "2026-03-14.md").write_text("daily log", encoding="utf-8")
        result = manager.read_file("memory/2026-03-14.md")
        assert result["text"] == "daily log"

    def test_load_evergreen(self, manager, ws_dir):
        (ws_dir / "MEMORY.md").write_text("  long term memory  \n", encoding="utf-8")
        assert manager.load_evergreen() == "long term memory"

    def test_load_evergreen_missing(self, manager):
        assert manager.load_evergreen() == ""

    def test_get_recent_daily(self, manager, ws_dir):
        today = date.today().isoformat()
        (ws_dir / "memory" / f"{today}.md").write_text("today's log", encoding="utf-8")
        results = manager.get_recent_daily(days=3)
        assert len(results) == 1
        assert results[0]["date"] == today

    def test_search_delegation(self, manager, ws_dir):
        (ws_dir / "MEMORY.md").write_text(
            "# Facts\n\nPython is a great programming language for building applications.\n",
            encoding="utf-8",
        )
        results = manager.search("Python language", min_score=0.1)
        assert len(results) > 0


class TestGetMemoryManager:
    """Tests for get_memory_manager cache."""

    def test_returns_same_instance(self, ws_dir):
        # Clear the cache first
        from nanobot.soul import tools
        tools._managers.clear()

        m1 = get_memory_manager("test", ws_dir)
        m2 = get_memory_manager("test", ws_dir)
        assert m1 is m2

    def test_different_agents_different_instances(self, tmp_path):
        from nanobot.soul import tools
        tools._managers.clear()

        ws1 = tmp_path / "agent1"
        ws1.mkdir()
        (ws1 / "memory").mkdir()
        ws2 = tmp_path / "agent2"
        ws2.mkdir()
        (ws2 / "memory").mkdir()

        m1 = get_memory_manager("agent1", ws1)
        m2 = get_memory_manager("agent2", ws2)
        assert m1 is not m2


class TestMemorySearchTool:
    """Tests for MemorySearchTool (Tool subclass)."""

    @pytest.fixture
    def tool(self, ws_dir):
        (ws_dir / "MEMORY.md").write_text(
            "# Memory\n\n## Preferences\n\nUser likes Python.\n", encoding="utf-8"
        )
        return MemorySearchTool(ws_dir)

    def test_tool_name(self, tool):
        assert tool.name == "memory_search"

    def test_tool_schema(self, tool):
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "memory_search"
        assert "query" in schema["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_execute_search(self, tool):
        result = json.loads(await tool.execute(query="Python"))
        assert "results" in result
        assert result["provider"] == "tfidf+bm25"

    @pytest.mark.asyncio
    async def test_execute_empty_query(self, tool):
        result = json.loads(await tool.execute(query=""))
        assert result.get("error") == "Empty query"

    def test_validate_params(self, tool):
        errors = tool.validate_params({"query": "test"})
        assert errors == []

    def test_validate_params_missing_required(self, tool):
        errors = tool.validate_params({})
        assert len(errors) > 0


class TestMemoryGetTool:
    """Tests for MemoryGetTool (Tool subclass)."""

    @pytest.fixture
    def tool(self, ws_dir):
        (ws_dir / "MEMORY.md").write_text("line1\nline2\nline3", encoding="utf-8")
        return MemoryGetTool(ws_dir)

    def test_tool_name(self, tool):
        assert tool.name == "memory_get"

    @pytest.mark.asyncio
    async def test_execute_read(self, tool):
        result = json.loads(await tool.execute(path="MEMORY.md"))
        assert "line1" in result["text"]

    @pytest.mark.asyncio
    async def test_execute_with_line_range(self, tool):
        result = json.loads(await tool.execute(path="MEMORY.md", **{"from": 2, "lines": 1}))
        assert result["text"] == "line2"

    @pytest.mark.asyncio
    async def test_execute_empty_path(self, tool):
        result = json.loads(await tool.execute(path=""))
        assert result["error"] == "Path required"


class TestMemoryWriteTool:
    """Tests for MemoryWriteTool (Tool subclass)."""

    @pytest.fixture
    def tool(self, ws_dir):
        return MemoryWriteTool(ws_dir)

    def test_tool_name(self, tool):
        assert tool.name == "memory_write"

    @pytest.mark.asyncio
    async def test_execute_write(self, tool):
        result = json.loads(await tool.execute(content="Remember this", category="fact"))
        assert result["status"] == "saved"
        assert result["category"] == "fact"

    @pytest.mark.asyncio
    async def test_execute_empty_content(self, tool):
        result = json.loads(await tool.execute(content=""))
        assert "error" in result


class TestRegisterMemoryTools:
    """Tests for register_memory_tools function."""

    def test_registers_all_tools(self, ws_dir):
        registry = ToolRegistry()
        register_memory_tools(registry, ws_dir)
        assert registry.has("memory_search")
        assert registry.has("memory_get")
        assert registry.has("memory_write")
        assert len(registry) == 3

    def test_tool_definitions(self, ws_dir):
        registry = ToolRegistry()
        register_memory_tools(registry, ws_dir)
        defs = registry.get_definitions()
        names = {d["function"]["name"] for d in defs}
        assert names == {"memory_search", "memory_get", "memory_write"}
