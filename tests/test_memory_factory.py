"""Unit tests for the memory factory function, base class, and backward compatibility."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.memory import (
    BaseMemoryStore,
    LongTermMemoryStore,
    MemoryConsolidator,
    MemoryStore,
    create_memory_store,
    create_memory_store_from_config,
    MEMORY_BACKENDS,
)
from nanobot.config.schema import MemoryConfig


class TestBackwardCompatibility:

    def test_memory_store_alias_is_long_term(self):
        assert MemoryStore is LongTermMemoryStore

    def test_memory_store_creates_correct_instance(self, tmp_path: Path):
        store = MemoryStore(tmp_path)
        assert isinstance(store, LongTermMemoryStore)
        assert isinstance(store, BaseMemoryStore)

    def test_memory_consolidator_importable(self):
        assert MemoryConsolidator is not None

    def test_memory_consolidator_default_store(self, tmp_path: Path):
        provider = MagicMock()
        sessions = MagicMock()
        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test",
            sessions=sessions,
            context_window_tokens=4096,
            build_messages=MagicMock(),
            get_tool_definitions=MagicMock(return_value=[]),
        )
        assert isinstance(consolidator.store, LongTermMemoryStore)

    def test_memory_consolidator_custom_store(self, tmp_path: Path):
        provider = MagicMock()
        sessions = MagicMock()
        custom_store = LongTermMemoryStore(tmp_path)
        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test",
            sessions=sessions,
            context_window_tokens=4096,
            build_messages=MagicMock(),
            get_tool_definitions=MagicMock(return_value=[]),
            store=custom_store,
        )
        assert consolidator.store is custom_store


class TestMemoryBackendsRegistry:

    def test_all_backends_registered(self):
        expected = {"long_term", "mem0", "graphiti", "memobase"}
        assert set(MEMORY_BACKENDS.keys()) == expected

    def test_backend_values_are_importable_paths(self):
        for name, path in MEMORY_BACKENDS.items():
            parts = path.rsplit(".", 1)
            assert len(parts) == 2, f"Backend {name} path should be module.ClassName"
            assert parts[0].startswith("nanobot.agent.memory.")


class TestCreateMemoryStore:

    def test_create_long_term(self, tmp_path: Path):
        store = create_memory_store("long_term", workspace=tmp_path)
        assert isinstance(store, LongTermMemoryStore)

    def test_create_unknown_backend_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Unknown memory backend 'nonexistent'"):
            create_memory_store("nonexistent", workspace=tmp_path)

    def test_create_default_is_long_term(self, tmp_path: Path):
        store = create_memory_store(workspace=tmp_path)
        assert isinstance(store, LongTermMemoryStore)

    def test_create_mem0_import_error(self, tmp_path: Path):
        with patch(
            "nanobot.agent.memory.mem0_store._lazy_import_mem0",
            side_effect=ImportError("mem0ai is required for Mem0MemoryStore."),
        ):
            with pytest.raises(ImportError, match="mem0ai"):
                create_memory_store("mem0", workspace=tmp_path)

    def test_create_graphiti_succeeds_with_library(self, tmp_path: Path):
        store = create_memory_store("graphiti", workspace=tmp_path)
        from nanobot.agent.memory.graphiti_store import GraphitiMemoryStore
        assert isinstance(store, GraphitiMemoryStore)

    def test_create_memobase_succeeds_with_library(self, tmp_path: Path):
        store = create_memory_store("memobase", workspace=tmp_path)
        from nanobot.agent.memory.memobase_store import MemobaseMemoryStore
        assert isinstance(store, MemobaseMemoryStore)

    def test_graphiti_lazy_import_fails_without_library(self):
        from nanobot.agent.memory.graphiti_store import _lazy_import_graphiti
        with patch.dict("sys.modules", {"graphiti_core": None}):
            with pytest.raises(ImportError, match="graphiti-core"):
                _lazy_import_graphiti()

    def test_memobase_lazy_import_fails_without_library(self):
        from nanobot.agent.memory.memobase_store import _lazy_import_memobase
        with patch.dict("sys.modules", {"memobase": None, "memobase.core": None, "memobase.core.async_entry": None}):
            with pytest.raises(ImportError, match="memobase"):
                _lazy_import_memobase()

    def test_create_mem0_with_mock(self, tmp_path: Path):
        mock_mem0_cls = MagicMock()
        mock_mem0_cls.return_value = MagicMock()
        with patch("nanobot.agent.memory.mem0_store._lazy_import_mem0", return_value=mock_mem0_cls):
            store = create_memory_store("mem0", workspace=tmp_path)
        from nanobot.agent.memory.mem0_store import Mem0MemoryStore
        assert isinstance(store, Mem0MemoryStore)

    def test_create_passes_kwargs(self, tmp_path: Path):
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        with patch("nanobot.agent.memory.mem0_store._lazy_import_mem0", return_value=mock_cls):
            store = create_memory_store(
                "mem0", workspace=tmp_path, config={"llm": {"provider": "openai"}}
            )
        assert store is not None

    def test_create_without_workspace_defaults_to_dot(self):
        store = create_memory_store("long_term")
        assert store.workspace == Path(".")


class TestBaseMemoryStoreShared:

    def test_format_messages(self):
        messages = [
            {"role": "user", "content": "hello", "timestamp": "2026-03-22 10:00"},
            {"role": "assistant", "content": "hi", "timestamp": "2026-03-22 10:01"},
        ]
        formatted = BaseMemoryStore._format_messages(messages)
        assert "USER: hello" in formatted
        assert "ASSISTANT: hi" in formatted

    def test_format_messages_skips_empty_content(self):
        messages = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "valid"},
        ]
        formatted = BaseMemoryStore._format_messages(messages)
        assert "valid" in formatted
        assert formatted.count("USER") == 1

    def test_format_messages_includes_tools(self):
        messages = [
            {"role": "assistant", "content": "result", "timestamp": "2026-03-22", "tools_used": ["web_search", "read_file"]},
        ]
        formatted = BaseMemoryStore._format_messages(messages)
        assert "[tools: web_search, read_file]" in formatted

    def test_fail_or_raw_archive_increments(self, tmp_path: Path):
        store = LongTermMemoryStore(tmp_path)
        messages = [{"role": "user", "content": "test", "timestamp": "2026-03-22"}]

        assert store._fail_or_raw_archive(messages) is False
        assert store._consecutive_failures == 1
        assert store._fail_or_raw_archive(messages) is False
        assert store._consecutive_failures == 2
        assert store._fail_or_raw_archive(messages) is True
        assert store._consecutive_failures == 0

        content = store.history_file.read_text()
        assert "[RAW]" in content


class TestCreateMemoryStoreFromConfig:

    def test_no_enabled_backend_falls_back_to_long_term(self, tmp_path: Path):
        cfg = MemoryConfig.model_validate({
            "mem0": {"enabled": False},
        })
        store = create_memory_store_from_config(cfg, tmp_path)
        assert isinstance(store, LongTermMemoryStore)

    def test_empty_config_falls_back_to_long_term(self, tmp_path: Path):
        cfg = MemoryConfig()
        store = create_memory_store_from_config(cfg, tmp_path)
        assert isinstance(store, LongTermMemoryStore)

    def test_long_term_enabled(self, tmp_path: Path):
        cfg = MemoryConfig.model_validate({
            "longTerm": {"enabled": True},
        })
        store = create_memory_store_from_config(cfg, tmp_path)
        assert isinstance(store, LongTermMemoryStore)

    def test_long_term_enabled_snake_case(self, tmp_path: Path):
        cfg = MemoryConfig.model_validate({
            "long_term": {"enabled": True},
        })
        store = create_memory_store_from_config(cfg, tmp_path)
        assert isinstance(store, LongTermMemoryStore)

    def test_mem0_enabled_with_config(self, tmp_path: Path):
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        cfg = MemoryConfig.model_validate({
            "mem0": {
                "enabled": True,
                "config": {"llm": {"provider": "openai"}},
            },
        })
        with patch("nanobot.agent.memory.mem0_store._lazy_import_mem0", return_value=mock_cls):
            store = create_memory_store_from_config(cfg, tmp_path)
        from nanobot.agent.memory.mem0_store import Mem0MemoryStore
        assert isinstance(store, Mem0MemoryStore)

    def test_graphiti_enabled_with_config(self, tmp_path: Path):
        cfg = MemoryConfig.model_validate({
            "graphiti": {
                "enabled": True,
                "graphDb": {
                    "falkordb": {"enable": True, "host": "localhost", "port": 6380},
                },
                "llm": {"model": "gpt-4.1-mini", "apiKey": "sk-x"},
            },
        })
        with (
            patch("nanobot.agent.memory.graphiti_store._lazy_import_graphiti", return_value=MagicMock()),
        ):
            store = create_memory_store_from_config(cfg, tmp_path)
        from nanobot.agent.memory.graphiti_store import GraphitiMemoryStore
        assert isinstance(store, GraphitiMemoryStore)

    def test_memobase_enabled_with_config(self, tmp_path: Path):
        cfg = MemoryConfig.model_validate({
            "memobase": {
                "enabled": True,
                "projectUrl": "http://localhost:8019",
                "apiKey": "secret",
                "maxTokenSize": 300,
            },
        })
        with patch(
            "nanobot.agent.memory.memobase_store._lazy_import_memobase",
            return_value=(MagicMock(), MagicMock()),
        ):
            store = create_memory_store_from_config(cfg, tmp_path)
        from nanobot.agent.memory.memobase_store import MemobaseMemoryStore
        assert isinstance(store, MemobaseMemoryStore)

    def test_multiple_enabled_raises_error(self, tmp_path: Path):
        cfg = MemoryConfig.model_validate({
            "long_term": {"enabled": True},
            "mem0": {"enabled": True},
        })
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        with patch("nanobot.agent.memory.mem0_store._lazy_import_mem0", return_value=mock_cls):
            with pytest.raises(ValueError, match="Multiple memory backends enabled"):
                create_memory_store_from_config(cfg, tmp_path)

    def test_unknown_backend_key_warns(self, tmp_path: Path):
        cfg = MemoryConfig.model_validate({
            "unknownBackend": {"enabled": True},
        })
        store = create_memory_store_from_config(cfg, tmp_path)
        assert isinstance(store, LongTermMemoryStore)

    def test_non_dict_extra_fields_ignored(self, tmp_path: Path):
        cfg = MemoryConfig.model_validate({
            "someString": "not_a_dict",
            "longTerm": {"enabled": True},
        })
        store = create_memory_store_from_config(cfg, tmp_path)
        assert isinstance(store, LongTermMemoryStore)
