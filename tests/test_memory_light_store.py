"""Unit tests for LightMemoryStore (LightMem adapter)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.memory.base import BaseMemoryStore


def _make_messages(count: int = 3) -> list[dict]:
    return [
        {"role": "user", "content": f"msg {i}", "timestamp": "2026-03-22 10:00"}
        for i in range(count)
    ]


def _mock_lightmem_module():
    """Create a mock LightMemory class."""
    mock_instance = MagicMock()
    mock_instance.add_memory.return_value = {"status": "ok"}
    mock_instance.retrieve.return_value = [
        "User likes hiking",
        "User works in AI",
    ]
    mock_instance.summarize.return_value = {"summaries": ["Summary A"]}
    mock_instance.construct_update_queue_all_entries.return_value = None
    mock_instance.offline_update_all_entries.return_value = None

    mock_cls = MagicMock()
    mock_cls.from_config.return_value = mock_instance
    return mock_cls, mock_instance


@pytest.fixture
def light_store(tmp_path: Path):
    mock_cls, mock_inst = _mock_lightmem_module()
    with patch("nanobot.agent.memory.light_memory._lazy_import_lightmem", return_value=mock_cls):
        from nanobot.agent.memory.light_memory import LightMemoryStore
        store = LightMemoryStore(tmp_path)
    store._mock_instance = mock_inst
    return store


class TestLightMemoryStoreInit:

    def test_is_subclass_of_base(self, light_store):
        assert isinstance(light_store, BaseMemoryStore)

    def test_import_error_without_library(self):
        from nanobot.agent.memory.light_memory import _lazy_import_lightmem
        with patch.dict("sys.modules", {"lightmem": None, "lightmem.memory": None, "lightmem.memory.lightmem": None}):
            with pytest.raises(ImportError, match="lightmem"):
                _lazy_import_lightmem()

    def test_init_uses_custom_config(self, tmp_path: Path):
        mock_cls, _ = _mock_lightmem_module()
        custom_cfg = {"pre_compress": True, "topic_segment": True}
        with patch("nanobot.agent.memory.light_memory._lazy_import_lightmem", return_value=mock_cls):
            from nanobot.agent.memory.light_memory import LightMemoryStore
            LightMemoryStore(tmp_path, config=custom_cfg)
        mock_cls.from_config.assert_called_once_with(custom_cfg)

    def test_init_generates_default_config(self, tmp_path: Path):
        mock_cls, _ = _mock_lightmem_module()
        with patch("nanobot.agent.memory.light_memory._lazy_import_lightmem", return_value=mock_cls):
            from nanobot.agent.memory.light_memory import LightMemoryStore
            LightMemoryStore(tmp_path)
        call_args = mock_cls.from_config.call_args[0][0]
        assert "memory_manager" in call_args
        assert "retrieve_strategy" in call_args


class TestLightMemoryStoreCRUD:

    @pytest.mark.asyncio
    async def test_add_delegates_to_add_memory(self, light_store):
        messages = _make_messages(2)
        await light_store.add(messages)
        light_store._mock_instance.add_memory.assert_called_once_with(
            messages=messages, force_segment=True, force_extract=True
        )

    @pytest.mark.asyncio
    async def test_add_with_custom_flags(self, light_store):
        messages = _make_messages(1)
        await light_store.add(messages, force_segment=False, force_extract=False)
        light_store._mock_instance.add_memory.assert_called_once_with(
            messages=messages, force_segment=False, force_extract=False
        )

    @pytest.mark.asyncio
    async def test_search_returns_formatted_results(self, light_store):
        results = await light_store.search("hiking", limit=5)
        light_store._mock_instance.retrieve.assert_called_once_with("hiking", limit=5)
        assert len(results) == 2
        assert results[0]["id"] == "0"
        assert "hiking" in results[0]["memory"]

    @pytest.mark.asyncio
    async def test_search_handles_empty_result(self, light_store):
        light_store._mock_instance.retrieve.return_value = []
        results = await light_store.search("nothing")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_non_list_result(self, light_store):
        light_store._mock_instance.retrieve.return_value = "single result"
        results = await light_store.search("test")
        assert len(results) == 1
        assert results[0]["memory"] == "single result"

    @pytest.mark.asyncio
    async def test_get_all_uses_broad_search(self, light_store):
        results = await light_store.get_all()
        light_store._mock_instance.retrieve.assert_called_once_with("*", limit=1000)

    @pytest.mark.asyncio
    async def test_update_triggers_offline_update(self, light_store):
        result = await light_store.update("m1", "new content")
        assert result is True
        light_store._mock_instance.construct_update_queue_all_entries.assert_called_once()
        light_store._mock_instance.offline_update_all_entries.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_failure_returns_false(self, light_store):
        light_store._mock_instance.construct_update_queue_all_entries.side_effect = RuntimeError("err")
        result = await light_store.update("m1", "fail")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_returns_false(self, light_store):
        result = await light_store.delete("m1")
        assert result is False

    @pytest.mark.asyncio
    async def test_summarize(self, light_store):
        result = await light_store.summarize()
        light_store._mock_instance.summarize.assert_called_once()
        assert "summaries" in result


class TestLightMemoryStoreContext:

    def test_get_memory_context_with_query(self, light_store):
        ctx = light_store.get_memory_context(query="hiking")
        assert "## Long-term Memory (LightMem)" in ctx
        assert "hiking" in ctx

    def test_get_memory_context_no_query_returns_empty(self, light_store):
        assert light_store.get_memory_context() == ""

    def test_get_memory_context_exception_returns_empty(self, light_store):
        light_store._mock_instance.retrieve.side_effect = RuntimeError("fail")
        assert light_store.get_memory_context(query="test") == ""

    def test_get_memory_context_handles_non_list(self, light_store):
        light_store._mock_instance.retrieve.return_value = "single"
        ctx = light_store.get_memory_context(query="test")
        assert "single" in ctx


class TestLightMemoryStoreConsolidation:

    @pytest.mark.asyncio
    async def test_consolidate_empty_returns_true(self, light_store):
        provider = AsyncMock()
        assert await light_store.consolidate([], provider, "model") is True

    @pytest.mark.asyncio
    async def test_consolidate_feeds_to_add_memory(self, light_store):
        provider = AsyncMock()
        messages = _make_messages(3)
        result = await light_store.consolidate(messages, provider, "model")
        assert result is True
        assert light_store._mock_instance.add_memory.called
        assert light_store._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_consolidate_preserves_timestamp(self, light_store):
        provider = AsyncMock()
        messages = [{"role": "user", "content": "hi", "timestamp": "2026-03-22"}]
        await light_store.consolidate(messages, provider, "model")
        call_args = light_store._mock_instance.add_memory.call_args
        passed_msgs = call_args[1]["messages"]
        assert passed_msgs[0]["time_stamp"] == "2026-03-22"

    @pytest.mark.asyncio
    async def test_consolidate_skips_empty_content(self, light_store):
        provider = AsyncMock()
        messages = [{"role": "user", "content": ""}, {"role": "user", "content": "valid"}]
        await light_store.consolidate(messages, provider, "model")
        call_args = light_store._mock_instance.add_memory.call_args
        passed_msgs = call_args[1]["messages"]
        assert len(passed_msgs) == 1
        assert passed_msgs[0]["content"] == "valid"

    @pytest.mark.asyncio
    async def test_consolidate_failure_increments_counter(self, light_store):
        provider = AsyncMock()
        light_store._mock_instance.add_memory.side_effect = RuntimeError("fail")
        result = await light_store.consolidate(_make_messages(), provider, "m")
        assert result is False
        assert light_store._consecutive_failures == 1
