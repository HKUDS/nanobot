"""Unit tests for SimpleMemoryStore (SimpleMem adapter)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.memory.base import BaseMemoryStore


def _make_messages(count: int = 3) -> list[dict]:
    return [
        {"role": "user", "content": f"msg {i}", "timestamp": "2026-03-22T10:00:00"}
        for i in range(count)
    ]


def _mock_simplemem_module():
    """Create a mock SimpleMemSystem class."""
    mock_instance = MagicMock()
    mock_instance.add_dialogue.return_value = None
    mock_instance.finalize.return_value = None
    mock_instance.ask.return_value = "The user discussed AI and Python."

    mock_cls = MagicMock(return_value=mock_instance)
    return mock_cls, mock_instance


@pytest.fixture
def simple_store(tmp_path: Path):
    mock_cls, mock_inst = _mock_simplemem_module()
    with patch("nanobot.agent.memory.simple_memory._lazy_import_simplemem", return_value=mock_cls):
        from nanobot.agent.memory.simple_memory import SimpleMemoryStore
        store = SimpleMemoryStore(tmp_path, clear_db=True, enable_parallel=True, max_workers=2)
    store._mock_instance = mock_inst
    return store


class TestSimpleMemoryStoreInit:

    def test_is_subclass_of_base(self, simple_store):
        assert isinstance(simple_store, BaseMemoryStore)

    def test_import_error_without_library(self):
        from nanobot.agent.memory.simple_memory import _lazy_import_simplemem
        with patch.dict("sys.modules", {"main": None, "simplemem": None, "simplemem.main": None}):
            with pytest.raises(ImportError, match="simplemem"):
                _lazy_import_simplemem()

    def test_init_passes_config(self, tmp_path: Path):
        mock_cls, _ = _mock_simplemem_module()
        with patch("nanobot.agent.memory.simple_memory._lazy_import_simplemem", return_value=mock_cls):
            from nanobot.agent.memory.simple_memory import SimpleMemoryStore
            SimpleMemoryStore(tmp_path, clear_db=True, enable_parallel=True, max_workers=8)
        mock_cls.assert_called_once_with(
            clear_db=True,
            enable_parallel_processing=True,
            max_parallel_workers=8,
            enable_parallel_retrieval=True,
            max_retrieval_workers=8,
        )

    def test_starts_unfinalized(self, simple_store):
        assert simple_store._finalized is False


class TestSimpleMemoryStoreCRUD:

    @pytest.mark.asyncio
    async def test_add_creates_dialogues_and_finalizes(self, simple_store):
        messages = _make_messages(3)
        result = await simple_store.add(messages)
        assert result["status"] == "ok"
        assert result["count"] == 3
        assert simple_store._mock_instance.add_dialogue.call_count == 3
        simple_store._mock_instance.finalize.assert_called_once()
        assert simple_store._finalized is True

    @pytest.mark.asyncio
    async def test_add_passes_role_content_timestamp(self, simple_store):
        messages = [{"role": "assistant", "content": "Hello!", "timestamp": "2026-03-22T14:30:00"}]
        await simple_store.add(messages)
        simple_store._mock_instance.add_dialogue.assert_called_once_with(
            "assistant", "Hello!", "2026-03-22T14:30:00"
        )

    @pytest.mark.asyncio
    async def test_add_skips_empty_content(self, simple_store):
        messages = [{"role": "user", "content": ""}, {"role": "user", "content": "valid"}]
        result = await simple_store.add(messages)
        assert result["count"] == 1
        assert simple_store._mock_instance.add_dialogue.call_count == 1

    @pytest.mark.asyncio
    async def test_add_empty_messages_no_finalize(self, simple_store):
        result = await simple_store.add([])
        assert result["count"] == 0
        simple_store._mock_instance.finalize.assert_not_called()
        assert simple_store._finalized is False

    @pytest.mark.asyncio
    async def test_search_returns_answer_after_finalize(self, simple_store):
        simple_store._finalized = True
        results = await simple_store.search("Python")
        assert len(results) == 1
        assert results[0]["id"] == "simplemem_answer"
        assert "Python" in results[0]["memory"]
        assert results[0]["query"] == "Python"

    @pytest.mark.asyncio
    async def test_search_before_finalize_returns_empty(self, simple_store):
        results = await simple_store.search("anything")
        assert results == []
        simple_store._mock_instance.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_empty_answer_returns_empty(self, simple_store):
        simple_store._finalized = True
        simple_store._mock_instance.ask.return_value = None
        results = await simple_store.search("nothing")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_exception_returns_empty(self, simple_store):
        simple_store._finalized = True
        simple_store._mock_instance.ask.side_effect = RuntimeError("fail")
        results = await simple_store.search("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_all_returns_empty(self, simple_store):
        assert await simple_store.get_all() == []

    @pytest.mark.asyncio
    async def test_update_returns_false(self, simple_store):
        assert await simple_store.update("m1", "content") is False

    @pytest.mark.asyncio
    async def test_delete_returns_false(self, simple_store):
        assert await simple_store.delete("m1") is False


class TestSimpleMemoryStoreContext:

    def test_get_memory_context_with_query(self, simple_store):
        simple_store._finalized = True
        ctx = simple_store.get_memory_context(query="AI")
        assert "## Long-term Memory (SimpleMem)" in ctx
        assert "AI" in ctx

    def test_get_memory_context_no_query_returns_empty(self, simple_store):
        simple_store._finalized = True
        assert simple_store.get_memory_context() == ""

    def test_get_memory_context_not_finalized_returns_empty(self, simple_store):
        assert simple_store.get_memory_context(query="test") == ""

    def test_get_memory_context_empty_answer(self, simple_store):
        simple_store._finalized = True
        simple_store._mock_instance.ask.return_value = None
        assert simple_store.get_memory_context(query="test") == ""

    def test_get_memory_context_exception_returns_empty(self, simple_store):
        simple_store._finalized = True
        simple_store._mock_instance.ask.side_effect = RuntimeError("fail")
        assert simple_store.get_memory_context(query="test") == ""


class TestSimpleMemoryStoreConsolidation:

    @pytest.mark.asyncio
    async def test_consolidate_empty_returns_true(self, simple_store):
        provider = AsyncMock()
        assert await simple_store.consolidate([], provider, "model") is True

    @pytest.mark.asyncio
    async def test_consolidate_adds_dialogues(self, simple_store):
        provider = AsyncMock()
        result = await simple_store.consolidate(_make_messages(3), provider, "model")
        assert result is True
        assert simple_store._mock_instance.add_dialogue.call_count == 3
        simple_store._mock_instance.finalize.assert_called_once()
        assert simple_store._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_consolidate_failure_increments_counter(self, simple_store):
        provider = AsyncMock()
        simple_store._mock_instance.add_dialogue.side_effect = RuntimeError("fail")
        result = await simple_store.consolidate(_make_messages(), provider, "m")
        assert result is False
        assert simple_store._consecutive_failures == 1
