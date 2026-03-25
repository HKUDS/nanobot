"""Unit tests for LongTermMemoryStore (file-based MEMORY.md + HISTORY.md)."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.memory.long_term_memory import LongTermMemoryStore
from nanobot.agent.memory.base import BaseMemoryStore
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_messages(count: int = 5) -> list[dict]:
    return [
        {"role": "user", "content": f"message {i}", "timestamp": "2026-03-22 10:00"}
        for i in range(count)
    ]


def _make_tool_response(history_entry: str, memory_update: str) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(
                id="call_1",
                name="save_memory",
                arguments={"history_entry": history_entry, "memory_update": memory_update},
            )
        ],
    )


class TestLongTermMemoryStoreInheritance:

    def test_is_subclass_of_base(self):
        assert issubclass(LongTermMemoryStore, BaseMemoryStore)

    def test_init_creates_memory_dir(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        assert store.memory_dir.exists()
        assert store.memory_dir == tmp_path / "memory"


class TestLongTermMemoryStoreFileIO:

    def test_read_long_term_empty(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        assert store.read_long_term() == ""

    def test_write_and_read_long_term(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        store.write_long_term("User likes cats.")
        assert store.read_long_term() == "User likes cats."

    def test_append_history(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        store.append_history("[2026-03-22] Event A")
        store.append_history("[2026-03-22] Event B")
        content = store.history_file.read_text(encoding="utf-8")
        assert "[2026-03-22] Event A" in content
        assert "[2026-03-22] Event B" in content

    def test_get_memory_context_empty(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        assert store.get_memory_context() == ""

    def test_get_memory_context_with_content(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        store.write_long_term("# Facts\nUser likes cats.")
        ctx = store.get_memory_context()
        assert "## Long-term Memory" in ctx
        assert "User likes cats." in ctx


class TestLongTermMemoryStoreCRUD:

    @pytest.mark.asyncio
    async def test_add_appends_to_history(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        result = await store.add(_make_messages(3))
        assert result["status"] == "ok"
        assert result["count"] == 3
        assert store.history_file.exists()
        content = store.history_file.read_text(encoding="utf-8")
        assert "message 0" in content
        assert "message 2" in content

    @pytest.mark.asyncio
    async def test_add_skips_empty_content(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        messages = [{"role": "user", "content": ""}, {"role": "user", "content": "hello"}]
        await store.add(messages)
        content = store.history_file.read_text(encoding="utf-8")
        assert "hello" in content

    @pytest.mark.asyncio
    async def test_search_finds_in_long_term(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        store.write_long_term("User prefers dark mode.")
        results = await store.search("dark mode")
        assert len(results) == 1
        assert results[0]["source"] == "MEMORY.md"
        assert "dark mode" in results[0]["memory"]

    @pytest.mark.asyncio
    async def test_search_finds_in_history(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        store.append_history("[2026-03-22] Discussed Python project")
        store.append_history("[2026-03-22] Talked about weather")
        results = await store.search("Python")
        assert len(results) >= 1
        assert any("Python" in r["memory"] for r in results)

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        for i in range(10):
            store.append_history(f"[2026-03-22] keyword event {i}")
        results = await store.search("keyword", limit=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_search_no_match_returns_empty(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        store.write_long_term("nothing relevant here")
        results = await store.search("nonexistent_xyz")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_all_includes_both_sources(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        store.write_long_term("Long-term fact")
        store.append_history("[2026-03-22] History entry")
        entries = await store.get_all()
        sources = {e["source"] for e in entries}
        assert "MEMORY.md" in sources
        assert "HISTORY.md" in sources

    @pytest.mark.asyncio
    async def test_get_all_empty(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        assert await store.get_all() == []

    @pytest.mark.asyncio
    async def test_update_long_term(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        store.write_long_term("old content")
        result = await store.update("long_term", "new content")
        assert result is True
        assert store.read_long_term() == "new content"

    @pytest.mark.asyncio
    async def test_update_invalid_id_returns_false(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        result = await store.update("history_0", "should fail")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_long_term(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        store.write_long_term("will be deleted")
        result = await store.delete("long_term")
        assert result is True
        assert store.read_long_term() == ""

    @pytest.mark.asyncio
    async def test_delete_invalid_id_returns_false(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        result = await store.delete("history_0")
        assert result is False


class TestLongTermMemoryStoreConsolidation:

    @pytest.mark.asyncio
    async def test_consolidate_empty_returns_true(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        provider = AsyncMock()
        assert await store.consolidate([], provider, "model") is True
        provider.chat_with_retry.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidate_success(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(
            return_value=_make_tool_response(
                "[2026-03-22] User discussed cats.",
                "# Memory\nUser likes cats.",
            )
        )
        result = await store.consolidate(_make_messages(5), provider, "model")
        assert result is True
        assert "User discussed cats." in store.history_file.read_text()
        assert "User likes cats." in store.memory_file.read_text()

    @pytest.mark.asyncio
    async def test_consolidate_no_tool_call_returns_false(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="Summary text", tool_calls=[])
        )
        result = await store.consolidate(_make_messages(5), provider, "model")
        assert result is False

    @pytest.mark.asyncio
    async def test_consolidate_raw_archive_after_failures(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        provider = AsyncMock()
        no_tool = LLMResponse(content="No tool.", finish_reason="stop", tool_calls=[])
        provider.chat_with_retry = AsyncMock(return_value=no_tool)
        messages = _make_messages(3)

        assert await store.consolidate(messages, provider, "m") is False
        assert await store.consolidate(messages, provider, "m") is False
        assert await store.consolidate(messages, provider, "m") is True

        content = store.history_file.read_text()
        assert "[RAW]" in content
        assert "3 messages" in content

    @pytest.mark.asyncio
    async def test_consolidate_exception_triggers_failure_handling(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(side_effect=RuntimeError("LLM down"))
        result = await store.consolidate(_make_messages(5), provider, "model")
        assert result is False
        assert store._consecutive_failures == 1
