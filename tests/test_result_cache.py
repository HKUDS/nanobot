"""Tests for tool result cache, summary generation, and retrieval tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.excel import ExcelFindTool, ExcelGetRowsTool
from nanobot.agent.tools.result_cache import (
    CacheGetSliceTool,
    ToolResultCache,
    _heuristic_summary,
    _make_cache_key,
    _slice_output,
    generate_summary,
)

# ---------------------------------------------------------------------------
# Cache key determinism
# ---------------------------------------------------------------------------


class TestCacheKey:
    def test_same_args_same_key(self):
        k1 = _make_cache_key("read_excel", {"path": "a.xlsx", "sheet": "S1"})
        k2 = _make_cache_key("read_excel", {"sheet": "S1", "path": "a.xlsx"})
        assert k1 == k2

    def test_different_args_different_key(self):
        k1 = _make_cache_key("read_excel", {"path": "a.xlsx"})
        k2 = _make_cache_key("read_excel", {"path": "b.xlsx"})
        assert k1 != k2

    def test_different_tool_different_key(self):
        k1 = _make_cache_key("read_excel", {"path": "a.xlsx"})
        k2 = _make_cache_key("read_file", {"path": "a.xlsx"})
        assert k1 != k2

    def test_key_length(self):
        k = _make_cache_key("tool", {"x": 1})
        assert len(k) == 12


# ---------------------------------------------------------------------------
# ToolResultCache store / retrieve / dedup
# ---------------------------------------------------------------------------


class TestToolResultCache:
    def test_store_and_get(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        key = cache.store("t", {"a": 1}, "full output", "summary", token_estimate=100)
        entry = cache.get(key)
        assert entry is not None
        assert entry.full_output == "full output"
        assert entry.summary == "summary"
        assert entry.token_estimate == 100

    def test_has_returns_key_on_hit(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        key = cache.store("t", {"a": 1}, "out", "sum")
        assert cache.has("t", {"a": 1}) == key

    def test_has_returns_none_on_miss(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        assert cache.has("t", {"a": 1}) is None

    def test_dedup_same_args(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        k1 = cache.store("t", {"a": 1}, "out1", "sum1")
        k2 = cache.store("t", {"a": 1}, "out2", "sum2")
        assert k1 == k2
        # Latest value wins
        assert cache.get(k1).full_output == "out2"

    def test_clear(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        key = cache.store("t", {"a": 1}, "out", "sum")
        cache.clear()
        assert cache.get(key) is None
        assert cache.has("t", {"a": 1}) is None

    def test_disk_persistence(self, tmp_path: Path):
        cache1 = ToolResultCache(workspace=tmp_path)
        key = cache1.store("t", {"a": 1}, "full", "sum")

        # New instance loads from disk
        cache2 = ToolResultCache(workspace=tmp_path)
        entry = cache2.get(key)
        assert entry is not None
        assert entry.full_output == "full"
        assert entry.summary == "sum"

    def test_large_entry_not_persisted_to_disk(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        big_output = "x" * 300_000  # > 200KB limit
        key = cache.store("t", {"a": 1}, big_output, "sum")

        # In-memory it's there
        assert cache.get(key) is not None

        # Disk should be empty (or not contain this entry)
        cache2 = ToolResultCache(workspace=tmp_path)
        assert cache2.get(key) is None

    def test_disk_eviction(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        # Store 55 entries (above 50 cap)
        for i in range(55):
            cache.store("t", {"i": i}, f"out-{i}", f"sum-{i}")

        # Reload — should have at most 50
        cache2 = ToolResultCache(workspace=tmp_path)
        count = sum(1 for k in range(55) if cache2.has("t", {"i": k}))
        assert count <= 50

    def test_store_only_caches_without_summary(self, tmp_path: Path):
        """store_only caches the full output but doesn't set summary on result."""
        cache = ToolResultCache(workspace=tmp_path)
        result = ToolResult.ok("x" * 5000)
        key = cache.store_only("web_fetch", {"url": "https://example.com"}, result)
        # Full output cached and retrievable
        entry = cache.get(key)
        assert entry is not None
        assert entry.full_output == "x" * 5000
        assert entry.summary == ""
        # Result has cache_key but NOT summary — to_llm_string returns raw output
        assert result.metadata["cache_key"] == key
        assert "summary" not in result.metadata
        assert result.to_llm_string() == "x" * 5000


# ---------------------------------------------------------------------------
# store_with_summary — LLM integration
# ---------------------------------------------------------------------------


class TestStoreWithSummary:
    @pytest.fixture
    def mock_provider(self):
        provider = AsyncMock()
        resp = AsyncMock()
        resp.content = "LLM generated summary for the tool output."
        provider.chat.return_value = resp
        return provider

    async def test_llm_summary_stored(self, tmp_path: Path, mock_provider: AsyncMock):
        cache = ToolResultCache(workspace=tmp_path)
        result = ToolResult.ok("x" * 5000)
        key = await cache.store_with_summary(
            "read_excel",
            {"path": "a.xlsx"},
            result,
            provider=mock_provider,
            model="gpt-4o-mini",
        )
        entry = cache.get(key)
        assert entry is not None
        assert entry.summary == "LLM generated summary for the tool output."
        # Result metadata annotated
        assert result.metadata["cache_key"] == key
        assert result.metadata["summary"] == entry.summary

    async def test_heuristic_fallback_on_provider_failure(self, tmp_path: Path):
        provider = AsyncMock()
        provider.chat.side_effect = RuntimeError("LLM unavailable")

        cache = ToolResultCache(workspace=tmp_path)
        result = ToolResult.ok("x" * 5000)
        key = await cache.store_with_summary(
            "read_excel",
            {"path": "a.xlsx"},
            result,
            provider=provider,
            model="gpt-4o-mini",
        )
        entry = cache.get(key)
        assert entry is not None
        # Should be heuristic summary (contains "chars")
        assert "chars" in entry.summary
        assert key in entry.summary

    async def test_heuristic_when_no_provider(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        result = ToolResult.ok("x" * 5000)
        key = await cache.store_with_summary("tool", {"a": 1}, result)
        entry = cache.get(key)
        assert "chars" in entry.summary


# ---------------------------------------------------------------------------
# generate_summary
# ---------------------------------------------------------------------------


class TestGenerateSummary:
    async def test_llm_path(self):
        provider = AsyncMock()
        resp = AsyncMock()
        resp.content = "Great summary"
        provider.chat.return_value = resp

        result = await generate_summary("t", "big output", "abc123", provider, "gpt-4o-mini")
        assert result == "Great summary"
        provider.chat.assert_called_once()

    async def test_llm_empty_response_falls_back(self):
        provider = AsyncMock()
        resp = AsyncMock()
        resp.content = ""
        provider.chat.return_value = resp

        result = await generate_summary("t", "big output", "abc123", provider, "gpt-4o-mini")
        assert "abc123" in result  # heuristic fallback

    async def test_no_provider_uses_heuristic(self):
        result = await generate_summary("t", "big output", "abc123")
        assert "abc123" in result

    def test_heuristic_summary(self):
        s = _heuristic_summary("read_excel", "x" * 5000, "key123")
        assert "5,000 chars" in s
        assert "key123" in s
        assert "cache_get_slice" in s


# ---------------------------------------------------------------------------
# Slice output
# ---------------------------------------------------------------------------


class TestSliceOutput:
    def test_json_array(self):
        data = json.dumps([{"a": i} for i in range(50)])
        result = _slice_output(data, 5, 10)
        parsed = json.loads(result)
        assert len(parsed) == 5
        assert parsed[0]["a"] == 5

    def test_excel_json_with_sheets(self):
        data = json.dumps(
            {
                "sheets": {
                    "Sheet1": {
                        "rows": [{"col": i} for i in range(30)],
                        "headers": ["col"],
                    }
                }
            }
        )
        result = _slice_output(data, 0, 5)
        parsed = json.loads(result)
        assert len(parsed) == 5
        assert parsed[0]["col"] == 0

    def test_line_based_fallback(self):
        lines = "\n".join(f"line {i}" for i in range(50))
        result = _slice_output(lines, 10, 15)
        assert "line 10" in result
        assert "line 14" in result
        assert "line 15" not in result


# ---------------------------------------------------------------------------
# ToolResult.to_llm_string
# ---------------------------------------------------------------------------


class TestToLlmString:
    def test_default_returns_output(self):
        r = ToolResult.ok("hello world")
        assert r.to_llm_string() == "hello world"

    def test_with_cache_key_returns_summary(self):
        r = ToolResult.ok("very long output...", cache_key="abc", summary="short summary")
        assert r.to_llm_string() == "short summary"

    def test_cache_key_without_summary_returns_output(self):
        r = ToolResult.ok("fallback output", cache_key="abc")
        assert r.to_llm_string() == "fallback output"


# ---------------------------------------------------------------------------
# CacheGetSliceTool
# ---------------------------------------------------------------------------


class TestCacheGetSliceTool:
    @pytest.fixture
    def cache_with_data(self, tmp_path: Path) -> ToolResultCache:
        cache = ToolResultCache(workspace=tmp_path)
        data = json.dumps([{"name": f"item-{i}", "value": i} for i in range(50)])
        cache.store("list_tool", {"x": 1}, data, "50 items cached")
        return cache

    async def test_slice_retrieval(self, cache_with_data: ToolResultCache):
        tool = CacheGetSliceTool(cache=cache_with_data)
        key = cache_with_data.has("list_tool", {"x": 1})
        result = await tool.execute(cache_key=key, start=0, end=5)
        assert result.success
        parsed = json.loads(result.output)
        assert len(parsed) == 5

    async def test_missing_key(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        tool = CacheGetSliceTool(cache=cache)
        result = await tool.execute(cache_key="nonexistent")
        assert not result.success
        assert "not_found" in result.metadata.get("error_type", "")


# ---------------------------------------------------------------------------
# ExcelGetRowsTool
# ---------------------------------------------------------------------------

_EXCEL_CACHE_DATA = json.dumps(
    {
        "file": "test.xlsx",
        "sheets": {
            "Sheet1": {
                "headers": ["Name", "Status", "Hours"],
                "row_count": 10,
                "total_rows": 10,
                "rows": [
                    {
                        "Name": f"Task {i}",
                        "Status": "Active" if i % 2 == 0 else "Done",
                        "Hours": i * 8,
                    }
                    for i in range(10)
                ],
            },
            "Sheet2": {
                "headers": ["X"],
                "row_count": 3,
                "total_rows": 3,
                "rows": [{"X": j} for j in range(3)],
            },
        },
    }
)


class TestExcelGetRowsTool:
    @pytest.fixture
    def cache(self, tmp_path: Path) -> ToolResultCache:
        c = ToolResultCache(workspace=tmp_path)
        c.store("read_excel", {"path": "test.xlsx"}, _EXCEL_CACHE_DATA, "summary")
        return c

    async def test_get_rows_default_sheet(self, cache: ToolResultCache):
        tool = ExcelGetRowsTool(cache=cache)
        key = cache.has("read_excel", {"path": "test.xlsx"})
        result = await tool.execute(cache_key=key, start_row=0, end_row=3)
        assert result.success
        parsed = json.loads(result.output)
        assert len(parsed["rows"]) == 3
        assert parsed["rows"][0]["Name"] == "Task 0"

    async def test_get_rows_specific_sheet(self, cache: ToolResultCache):
        tool = ExcelGetRowsTool(cache=cache)
        key = cache.has("read_excel", {"path": "test.xlsx"})
        result = await tool.execute(cache_key=key, sheet="Sheet2")
        assert result.success
        parsed = json.loads(result.output)
        assert len(parsed["rows"]) == 3

    async def test_get_rows_invalid_sheet(self, cache: ToolResultCache):
        tool = ExcelGetRowsTool(cache=cache)
        key = cache.has("read_excel", {"path": "test.xlsx"})
        result = await tool.execute(cache_key=key, sheet="Nonexistent")
        assert not result.success

    async def test_get_rows_missing_key(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        tool = ExcelGetRowsTool(cache=cache)
        result = await tool.execute(cache_key="bad")
        assert not result.success


# ---------------------------------------------------------------------------
# ExcelFindTool
# ---------------------------------------------------------------------------


class TestExcelFindTool:
    @pytest.fixture
    def cache(self, tmp_path: Path) -> ToolResultCache:
        c = ToolResultCache(workspace=tmp_path)
        c.store("read_excel", {"path": "test.xlsx"}, _EXCEL_CACHE_DATA, "summary")
        return c

    async def test_find_all_columns(self, cache: ToolResultCache):
        tool = ExcelFindTool(cache=cache)
        key = cache.has("read_excel", {"path": "test.xlsx"})
        result = await tool.execute(cache_key=key, query="Task 3")
        assert result.success
        parsed = json.loads(result.output)
        assert parsed["matches"] == 1
        assert parsed["rows"][0]["Name"] == "Task 3"

    async def test_find_specific_column(self, cache: ToolResultCache):
        tool = ExcelFindTool(cache=cache)
        key = cache.has("read_excel", {"path": "test.xlsx"})
        result = await tool.execute(cache_key=key, query="Active", column="Status")
        assert result.success
        parsed = json.loads(result.output)
        assert parsed["matches"] == 5  # Tasks 0, 2, 4, 6, 8

    async def test_find_case_insensitive(self, cache: ToolResultCache):
        tool = ExcelFindTool(cache=cache)
        key = cache.has("read_excel", {"path": "test.xlsx"})
        result = await tool.execute(cache_key=key, query="active", column="Status")
        assert result.success
        parsed = json.loads(result.output)
        assert parsed["matches"] == 5

    async def test_find_no_matches(self, cache: ToolResultCache):
        tool = ExcelFindTool(cache=cache)
        key = cache.has("read_excel", {"path": "test.xlsx"})
        result = await tool.execute(cache_key=key, query="nonexistent")
        assert result.success
        parsed = json.loads(result.output)
        assert parsed["matches"] == 0

    async def test_find_missing_key(self, tmp_path: Path):
        cache = ToolResultCache(workspace=tmp_path)
        tool = ExcelFindTool(cache=cache)
        result = await tool.execute(cache_key="bad", query="x")
        assert not result.success


# ---------------------------------------------------------------------------
# ToolRegistry duplicate-call guard integration
# ---------------------------------------------------------------------------


class TestRegistryCacheIntegration:
    """Test that ToolRegistry uses the cache for dedup."""

    async def test_duplicate_call_returns_cached(self, tmp_path: Path):
        from nanobot.agent.tools.base import Tool
        from nanobot.agent.tools.registry import ToolRegistry

        call_count = 0

        class CountingTool(Tool):
            readonly = True

            @property
            def name(self) -> str:
                return "counting"

            @property
            def description(self) -> str:
                return "test"

            @property
            def parameters(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                nonlocal call_count
                call_count += 1
                return ToolResult.ok("x" * 5000)

        cache = ToolResultCache(workspace=tmp_path)
        # Pre-populate cache with a summary
        cache.store("counting", {}, "x" * 5000, "cached summary")

        registry = ToolRegistry()
        registry.register(CountingTool())
        registry.set_cache(cache)

        result = await registry.execute("counting", {})
        assert result.success
        assert result.to_llm_string() == "cached summary"
        assert call_count == 0  # Tool was NOT executed — cache hit

    async def test_cache_miss_executes_and_caches(self, tmp_path: Path):
        from nanobot.agent.tools.base import Tool
        from nanobot.agent.tools.registry import ToolRegistry

        class BigTool(Tool):
            readonly = True

            @property
            def name(self) -> str:
                return "big_tool"

            @property
            def description(self) -> str:
                return "test"

            @property
            def parameters(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("y" * 5000)

        cache = ToolResultCache(workspace=tmp_path)
        registry = ToolRegistry()
        registry.register(BigTool())
        registry.set_cache(cache)

        result = await registry.execute("big_tool", {})
        assert result.success
        # After execution, result should have been cached with summary
        assert cache.has("big_tool", {}) is not None
        assert result.metadata.get("cache_key") is not None

    async def test_small_result_not_cached(self, tmp_path: Path):
        from nanobot.agent.tools.base import Tool
        from nanobot.agent.tools.registry import ToolRegistry

        class SmallTool(Tool):
            readonly = True

            @property
            def name(self) -> str:
                return "small"

            @property
            def description(self) -> str:
                return "test"

            @property
            def parameters(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("short output")

        cache = ToolResultCache(workspace=tmp_path)
        registry = ToolRegistry()
        registry.register(SmallTool())
        registry.set_cache(cache)

        result = await registry.execute("small", {})
        assert result.success
        # Small result should NOT be cached
        assert cache.has("small", {}) is None
        assert "cache_key" not in result.metadata
