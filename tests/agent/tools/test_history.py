"""Tests for SearchHistoryTool and MemoryStore.search_history."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.history import SearchHistoryTool
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


@pytest.fixture
def tool(store):
    return SearchHistoryTool(store=store)


class TestEnabledAndCreate:
    def test_disabled_without_store(self):
        ctx = ToolContext(config=None, workspace="/tmp")
        assert SearchHistoryTool.enabled(ctx) is False

    def test_enabled_with_store(self, store):
        ctx = ToolContext(
            config=None, workspace=str(store.workspace), memory_store=store
        )
        assert SearchHistoryTool.enabled(ctx) is True
        created = SearchHistoryTool.create(ctx)
        assert isinstance(created, SearchHistoryTool)

    def test_is_read_only_and_concurrency_safe(self, tool):
        # The tool must never write: construction injects the live store rather
        # than building one (which could trigger a legacy-history migration).
        assert tool.read_only is True
        assert tool.concurrency_safe is True

    def test_limit_bounds_in_schema(self, tool):
        limit_schema = tool.parameters["properties"]["limit"]
        assert limit_schema["minimum"] == 1
        assert limit_schema["maximum"] == 50


class TestDiscoveryAndRegistration:
    def test_tool_is_discovered(self):
        names = {cls.__name__ for cls in ToolLoader().discover()}
        assert "SearchHistoryTool" in names

    def test_registers_only_with_memory_store(self, tmp_path):
        # enabled() only checks `memory_store is not None`, so a sentinel is
        # enough — no real store needed to prove the registration gate.
        with_store = ToolContext(
            config=MagicMock(), workspace=str(tmp_path), memory_store=object()
        )
        assert "search_history" in ToolLoader().load(with_store, ToolRegistry())

        without_store = ToolContext(config=MagicMock(), workspace=str(tmp_path))
        assert "search_history" not in ToolLoader().load(without_store, ToolRegistry())


class TestExecute:
    async def test_empty_history(self, tool):
        result = await tool.execute()
        assert "No conversation history" in result

    async def test_returns_recent_newest_first(self, store, tool):
        store.append_history("first thing")
        store.append_history("second thing")
        store.append_history("third thing")
        result = await tool.execute()
        assert "3 matching entries" in result
        assert result.index("third thing") < result.index("first thing")

    async def test_single_entry_uses_singular_noun(self, store, tool):
        store.append_history("only one")
        result = await tool.execute()
        assert "1 matching entry" in result

    async def test_query_substring_is_case_insensitive(self, store, tool):
        store.append_history("Booked the FLIGHT to Tokyo")
        store.append_history("ordered lunch")
        result = await tool.execute(query="flight")
        assert "Tokyo" in result
        assert "lunch" not in result

    async def test_query_no_match(self, store, tool):
        store.append_history("hello world")
        result = await tool.execute(query="zzz")
        assert "No history entries matching" in result

    async def test_limit_caps_results(self, store, tool):
        for i in range(10):
            store.append_history(f"entry {i}")
        result = await tool.execute(limit=3)
        assert "3 matching entries" in result
        assert "entry 9" in result   # newest kept
        assert "entry 6" not in result  # older dropped

    async def test_long_entry_is_truncated(self, store, tool):
        store.append_history("x" * 5000)
        result = await tool.execute()
        # Per-entry cap (1000) keeps the response far below the raw length.
        assert len(result) < 2000


class TestStoreSearchHistory:
    def test_skips_malformed_rows(self, store):
        store.append_history("valid one")
        with open(store.history_file, "a", encoding="utf-8") as f:
            f.write('{"cursor": "bad", "content": "x", "timestamp": "t"}\n')
            f.write("not json at all\n")
        results = store.search_history()
        assert [e["content"] for e in results] == ["valid one"]

    def test_oldest_first_option(self, store):
        store.append_history("a")
        store.append_history("b")
        results = store.search_history(newest_first=False)
        assert [e["content"] for e in results] == ["a", "b"]

    def test_non_positive_limit_returns_all(self, store):
        for i in range(5):
            store.append_history(f"e{i}")
        assert len(store.search_history(limit=0)) == 5
