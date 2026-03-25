"""Unit tests for AgenticMemoryStore (A-MEM adapter)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.memory.base import BaseMemoryStore


def _make_messages(count: int = 3) -> list[dict]:
    return [
        {"role": "user", "content": f"msg {i}", "timestamp": "2026-03-22 10:00"}
        for i in range(count)
    ]


def _mock_amem_module():
    """Create a mock AgenticMemorySystem class."""
    mock_instance = MagicMock()
    mock_instance.add_note.return_value = "note_001"
    mock_instance.search_agentic.return_value = [
        {"id": "n1", "content": "User likes cats", "tags": ["pets"], "context": "personal"},
        {"id": "n2", "content": "Project uses Python", "tags": ["tech"], "context": "work"},
    ]
    mock_instance.read.return_value = MagicMock(
        content="User likes cats", tags=["pets"], context="personal", keywords=["cats"]
    )
    mock_instance.update.return_value = None
    mock_instance.delete.return_value = None

    mock_cls = MagicMock(return_value=mock_instance)
    return mock_cls, mock_instance


@pytest.fixture
def agentic_store(tmp_path: Path):
    mock_cls, mock_inst = _mock_amem_module()
    with patch("nanobot.agent.memory.agentic_memory._lazy_import_amem", return_value=mock_cls):
        from nanobot.agent.memory.agentic_memory import AgenticMemoryStore
        store = AgenticMemoryStore(
            tmp_path,
            embedding_model="test-model",
            llm_backend="openai",
            llm_model="gpt-test",
        )
    store._mock_instance = mock_inst
    return store


class TestAgenticMemoryStoreInit:

    def test_is_subclass_of_base(self, agentic_store):
        assert isinstance(agentic_store, BaseMemoryStore)

    def test_import_error_without_library(self):
        from nanobot.agent.memory.agentic_memory import _lazy_import_amem
        with patch.dict("sys.modules", {"agentic_memory": None, "agentic_memory.memory_system": None}):
            with pytest.raises(ImportError, match="agentic_memory"):
                _lazy_import_amem()

    def test_init_passes_config_to_system(self, tmp_path: Path):
        mock_cls, _ = _mock_amem_module()
        with patch("nanobot.agent.memory.agentic_memory._lazy_import_amem", return_value=mock_cls):
            from nanobot.agent.memory.agentic_memory import AgenticMemoryStore
            AgenticMemoryStore(
                tmp_path,
                embedding_model="custom-embed",
                llm_backend="ollama",
                llm_model="llama3",
            )
        mock_cls.assert_called_once_with(
            model_name="custom-embed",
            llm_backend="ollama",
            llm_model="llama3",
        )


class TestAgenticMemoryStoreCRUD:

    @pytest.mark.asyncio
    async def test_add_creates_notes_for_each_message(self, agentic_store):
        messages = _make_messages(3)
        ids = await agentic_store.add(messages)
        assert len(ids) == 3
        assert all(id_ == "note_001" for id_ in ids)
        assert agentic_store._mock_instance.add_note.call_count == 3

    @pytest.mark.asyncio
    async def test_add_skips_empty_content(self, agentic_store):
        messages = [{"role": "user", "content": ""}, {"role": "user", "content": "valid"}]
        ids = await agentic_store.add(messages)
        assert len(ids) == 1
        assert agentic_store._mock_instance.add_note.call_count == 1

    @pytest.mark.asyncio
    async def test_add_passes_tags_and_category(self, agentic_store):
        messages = [{"role": "user", "content": "hello"}]
        await agentic_store.add(messages, tags=["greet"], category="chat")
        call_kwargs = agentic_store._mock_instance.add_note.call_args[1]
        assert call_kwargs["tags"] == ["greet"]
        assert call_kwargs["category"] == "chat"

    @pytest.mark.asyncio
    async def test_add_formats_timestamp(self, agentic_store):
        messages = [{"role": "user", "content": "hi", "timestamp": "2026-03-22 10:30"}]
        await agentic_store.add(messages)
        call_kwargs = agentic_store._mock_instance.add_note.call_args[1]
        assert call_kwargs["timestamp"] == "202603221030"

    @pytest.mark.asyncio
    async def test_add_handles_missing_timestamp(self, agentic_store):
        messages = [{"role": "user", "content": "hi"}]
        await agentic_store.add(messages)
        call_kwargs = agentic_store._mock_instance.add_note.call_args[1]
        assert "timestamp" not in call_kwargs

    @pytest.mark.asyncio
    async def test_search_returns_formatted_results(self, agentic_store):
        results = await agentic_store.search("cats", limit=5)
        agentic_store._mock_instance.search_agentic.assert_called_once_with("cats", k=5)
        assert len(results) == 2
        assert results[0]["id"] == "n1"
        assert results[0]["memory"] == "User likes cats"
        assert results[0]["tags"] == ["pets"]

    @pytest.mark.asyncio
    async def test_search_handles_empty_result(self, agentic_store):
        agentic_store._mock_instance.search_agentic.return_value = []
        results = await agentic_store.search("nothing")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_non_dict_items(self, agentic_store):
        mock_note = MagicMock()
        mock_note.id = "x1"
        mock_note.__str__ = lambda self: "note text"
        agentic_store._mock_instance.search_agentic.return_value = [mock_note]
        results = await agentic_store.search("test")
        assert len(results) == 1
        assert results[0]["id"] == "x1"

    @pytest.mark.asyncio
    async def test_get_all_uses_broad_search(self, agentic_store):
        await agentic_store.get_all()
        agentic_store._mock_instance.search_agentic.assert_called_once_with("*", k=10000)

    @pytest.mark.asyncio
    async def test_update_success(self, agentic_store):
        result = await agentic_store.update("n1", "updated content")
        assert result is True
        agentic_store._mock_instance.update.assert_called_once_with("n1", content="updated content")

    @pytest.mark.asyncio
    async def test_update_failure_returns_false(self, agentic_store):
        agentic_store._mock_instance.update.side_effect = KeyError("not found")
        result = await agentic_store.update("n1", "fail")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_success(self, agentic_store):
        result = await agentic_store.delete("n1")
        assert result is True
        agentic_store._mock_instance.delete.assert_called_once_with("n1")

    @pytest.mark.asyncio
    async def test_delete_failure_returns_false(self, agentic_store):
        agentic_store._mock_instance.delete.side_effect = KeyError("not found")
        result = await agentic_store.delete("n1")
        assert result is False


class TestAgenticMemoryStoreContext:

    def test_get_memory_context_with_query(self, agentic_store):
        ctx = agentic_store.get_memory_context(query="cats")
        assert "## Long-term Memory (A-MEM)" in ctx
        assert "User likes cats" in ctx
        assert "[pets]" in ctx

    def test_get_memory_context_no_query_uses_default(self, agentic_store):
        agentic_store.get_memory_context()
        agentic_store._mock_instance.search_agentic.assert_called_with(
            "recent important information", k=10
        )

    def test_get_memory_context_empty_result(self, agentic_store):
        agentic_store._mock_instance.search_agentic.return_value = []
        assert agentic_store.get_memory_context(query="test") == ""

    def test_get_memory_context_exception_returns_empty(self, agentic_store):
        agentic_store._mock_instance.search_agentic.side_effect = RuntimeError("fail")
        assert agentic_store.get_memory_context(query="test") == ""


class TestAgenticMemoryStoreConsolidation:

    @pytest.mark.asyncio
    async def test_consolidate_empty_returns_true(self, agentic_store):
        provider = AsyncMock()
        assert await agentic_store.consolidate([], provider, "model") is True

    @pytest.mark.asyncio
    async def test_consolidate_creates_notes(self, agentic_store):
        provider = AsyncMock()
        result = await agentic_store.consolidate(_make_messages(3), provider, "model")
        assert result is True
        assert agentic_store._mock_instance.add_note.call_count == 3
        assert agentic_store._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_consolidate_failure_increments_counter(self, agentic_store):
        provider = AsyncMock()
        agentic_store._mock_instance.add_note.side_effect = RuntimeError("fail")
        result = await agentic_store.consolidate(_make_messages(), provider, "m")
        assert result is False
        assert agentic_store._consecutive_failures == 1
