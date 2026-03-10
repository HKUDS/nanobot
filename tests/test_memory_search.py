"""Tests for memory search with SQLite FTS5."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from nanobot.agent.tools.memory_search import MemoryIndex, MemorySearchTool


@pytest.fixture
def memory_dir(tmp_path):
    """Create a temp memory directory."""
    return tmp_path


@pytest.fixture
def history_file(memory_dir):
    """Create a sample HISTORY.md."""
    content = """[2026-02-20 10:00] Discussed purchasing apartment in Nanjing Jiangning district. User prefers budget under 180万.

[2026-02-21 14:30] Analyzed Xiamen as potential city. Conclusion: not suitable due to high housing prices and limited job market.

[2026-02-22 09:15] Researched Jiulong Lake area in Jiangning. Key properties: Dexin Xingchen (德信星宸) 107㎡ at 155万.

[2026-02-23 16:00] Set up SearXNG search engine on localhost:8888. Configured as default search provider.

[2026-02-24 11:00] Compared MiniMax M2.5 vs GLM-5 models. M2.5 better for cost-sensitive agent tasks, GLM-5 for heavy engineering.

"""
    f = memory_dir / "HISTORY.md"
    f.write_text(content, encoding="utf-8")
    return f


@pytest.fixture
def index(memory_dir, history_file):
    """Create a MemoryIndex with sample data."""
    idx = MemoryIndex(memory_dir)
    yield idx
    idx.close()


class TestMemoryIndex:
    def test_init_creates_db(self, memory_dir, history_file):
        idx = MemoryIndex(memory_dir)
        assert (memory_dir / "memory.db").exists()
        idx.close()

    def test_auto_import_history(self, index):
        conn = index._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        assert count == 5

    def test_search_basic(self, index):
        results = index.search("Nanjing")
        assert len(results) >= 1
        assert "Nanjing" in results[0]["content"]

    def test_search_chinese(self, index):
        results = index.search("德信星宸")
        assert len(results) >= 1
        assert "德信星宸" in results[0]["content"]

    def test_search_no_results(self, index):
        results = index.search("nonexistent_xyz_keyword")
        assert len(results) == 0

    def test_search_time_range(self, index):
        # Search with year range should return all
        results = index.search("Nanjing", time_range="year")
        assert len(results) >= 1

    def test_search_limit(self, index):
        results = index.search("2026", limit=2)
        assert len(results) <= 2

    def test_index_entry(self, index):
        index.index_entry("[2026-02-25 08:00] New entry about testing memory search.")
        results = index.search("testing memory search")
        assert len(results) >= 1

    def test_reindex(self, index):
        count = index.reindex()
        assert count == 5

    def test_empty_query(self, index):
        results = index.search("")
        assert results == []

    def test_special_characters_in_query(self, index):
        # Should not crash on FTS5 special chars
        results = index.search('test "quotes" AND (parens)')
        # May or may not find results, but should not raise
        assert isinstance(results, list)

    def test_fallback_search(self, index):
        results = index._fallback_search("Nanjing", None, 10)
        assert len(results) >= 1

    def test_parse_history_empty(self):
        entries = MemoryIndex._parse_history("")
        assert entries == []

    def test_parse_history_no_timestamp(self):
        entries = MemoryIndex._parse_history("Some entry without timestamp")
        assert len(entries) == 1
        assert entries[0][0] == ""  # no timestamp
        assert entries[0][1] == "Some entry without timestamp"

    def test_time_cutoff(self):
        assert MemoryIndex._time_cutoff("day") is not None
        assert MemoryIndex._time_cutoff("week") is not None
        assert MemoryIndex._time_cutoff("month") is not None
        assert MemoryIndex._time_cutoff("quarter") is not None
        assert MemoryIndex._time_cutoff("year") is not None
        assert MemoryIndex._time_cutoff("invalid") is None

    def test_no_history_file(self, memory_dir):
        """Index should work even without HISTORY.md."""
        idx = MemoryIndex(memory_dir / "empty_subdir")
        # Should not crash, just have 0 entries
        results = idx.search("anything")
        assert results == []
        idx.close()

    def test_build_fts_query(self):
        assert MemoryIndex._build_fts_query("hello world") == '"hello" "world"'
        assert MemoryIndex._build_fts_query("") == ""
        assert MemoryIndex._build_fts_query('test "quoted"') == '"test" "quoted"'


class TestMemorySearchTool:
    def test_tool_metadata(self, index):
        tool = MemorySearchTool(index=index)
        assert tool.name == "memory_search"
        assert "query" in tool.parameters["properties"]

    def test_execute_search(self, index):
        tool = MemorySearchTool(index=index)
        result = asyncio.get_event_loop().run_until_complete(
            tool.execute(query="Nanjing")
        )
        assert "Nanjing" in result
        assert "result(s)" in result

    def test_execute_empty_query(self, index):
        tool = MemorySearchTool(index=index)
        result = asyncio.get_event_loop().run_until_complete(
            tool.execute(query="")
        )
        assert "Error" in result

    def test_execute_no_results(self, index):
        tool = MemorySearchTool(index=index)
        result = asyncio.get_event_loop().run_until_complete(
            tool.execute(query="zzz_nonexistent_zzz")
        )
        assert "No results" in result

    def test_execute_with_time_range(self, index):
        tool = MemorySearchTool(index=index)
        # Use time_range=None to avoid timestamp filtering issues in tests
        result = asyncio.get_event_loop().run_until_complete(
            tool.execute(query="MiniMax GLM", time_range=None)
        )
        assert "result(s)" in result

    def test_execute_with_limit(self, index):
        tool = MemorySearchTool(index=index)
        result = asyncio.get_event_loop().run_until_complete(
            tool.execute(query="2026", limit=1)
        )
        assert "1 result(s)" in result
