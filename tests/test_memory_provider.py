"""Tests for MemoryProvider ABC, FileMemoryProvider, and MemoryStats.

Validates the pluggable memory provider interface introduced to support
custom storage backends while maintaining backward compatibility.
"""

from pathlib import Path

import pytest

from nanobot.agent.memory import (
    FileMemoryProvider,
    MemoryProvider,
    MemoryStats,
    MemoryStore,
    create_memory_provider,
)


class TestMemoryProviderABC:
    """Verify the abstract interface contract."""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """MemoryProvider is abstract and cannot be instantiated directly."""
        with pytest.raises(TypeError):
            MemoryProvider()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_required_methods(self) -> None:
        """A subclass missing abstract methods cannot be instantiated."""

        class IncompleteProvider(MemoryProvider):
            def read_long_term(self) -> str:
                return ""

        with pytest.raises(TypeError):
            IncompleteProvider()  # type: ignore[abstract]

    def test_concrete_subclass_with_all_methods_works(self) -> None:
        """A complete subclass can be instantiated and used."""

        class InMemoryProvider(MemoryProvider):
            def __init__(self):
                self._memory = ""
                self._history: list[str] = []

            def read_long_term(self) -> str:
                return self._memory

            def write_long_term(self, content: str) -> None:
                self._memory = content

            def append_history(self, entry: str) -> None:
                self._history.append(entry)

        provider = InMemoryProvider()
        assert provider.read_long_term() == ""

        provider.write_long_term("fact: user likes Python")
        assert provider.read_long_term() == "fact: user likes Python"

        provider.append_history("[2026-01-01 00:00] User discussed Python.")
        assert len(provider._history) == 1

    def test_get_memory_context_default_implementation(self) -> None:
        """The default get_memory_context uses read_long_term."""

        class StubProvider(MemoryProvider):
            def read_long_term(self) -> str:
                return "# Facts\nUser is a developer."

            def write_long_term(self, content: str) -> None:
                pass

            def append_history(self, entry: str) -> None:
                pass

        provider = StubProvider()
        ctx = provider.get_memory_context()
        assert "## Long-term Memory" in ctx
        assert "User is a developer." in ctx

    def test_get_memory_context_empty_returns_empty(self) -> None:
        """Empty long-term memory returns empty string."""

        class EmptyProvider(MemoryProvider):
            def read_long_term(self) -> str:
                return ""

            def write_long_term(self, content: str) -> None:
                pass

            def append_history(self, entry: str) -> None:
                pass

        assert EmptyProvider().get_memory_context() == ""

    def test_get_stats_default_returns_empty_stats(self) -> None:
        """Default get_stats returns zeroed MemoryStats."""

        class MinimalProvider(MemoryProvider):
            def read_long_term(self) -> str:
                return ""

            def write_long_term(self, content: str) -> None:
                pass

            def append_history(self, entry: str) -> None:
                pass

        stats = MinimalProvider().get_stats()
        assert isinstance(stats, MemoryStats)
        assert stats.long_term_size_bytes == 0
        assert stats.history_entries == 0


class TestFileMemoryProvider:
    """Test the file-based memory provider."""

    def test_read_write_long_term(self, tmp_path: Path) -> None:
        provider = FileMemoryProvider(tmp_path)
        assert provider.read_long_term() == ""

        provider.write_long_term("# Memory\nUser prefers dark mode.")
        assert provider.read_long_term() == "# Memory\nUser prefers dark mode."

    def test_write_overwrites_previous(self, tmp_path: Path) -> None:
        provider = FileMemoryProvider(tmp_path)
        provider.write_long_term("version 1")
        provider.write_long_term("version 2")
        assert provider.read_long_term() == "version 2"

    def test_append_history(self, tmp_path: Path) -> None:
        provider = FileMemoryProvider(tmp_path)
        provider.append_history("[2026-01-01 10:00] First entry.")
        provider.append_history("[2026-01-02 10:00] Second entry.")

        content = provider.history_file.read_text(encoding="utf-8")
        assert "[2026-01-01 10:00] First entry." in content
        assert "[2026-01-02 10:00] Second entry." in content

    def test_append_history_strips_trailing_whitespace(self, tmp_path: Path) -> None:
        provider = FileMemoryProvider(tmp_path)
        provider.append_history("entry with trailing spaces   ")

        content = provider.history_file.read_text(encoding="utf-8")
        assert content == "entry with trailing spaces\n\n"

    def test_get_memory_context_with_content(self, tmp_path: Path) -> None:
        provider = FileMemoryProvider(tmp_path)
        provider.write_long_term("User is a data scientist.")
        ctx = provider.get_memory_context()
        assert "## Long-term Memory" in ctx
        assert "User is a data scientist." in ctx

    def test_get_memory_context_empty(self, tmp_path: Path) -> None:
        provider = FileMemoryProvider(tmp_path)
        assert provider.get_memory_context() == ""

    def test_creates_memory_directory(self, tmp_path: Path) -> None:
        workspace = tmp_path / "new_workspace"
        provider = FileMemoryProvider(workspace)
        assert provider.memory_dir.exists()
        assert provider.memory_dir == workspace / "memory"

    def test_get_stats_empty(self, tmp_path: Path) -> None:
        provider = FileMemoryProvider(tmp_path)
        stats = provider.get_stats()
        assert stats.long_term_size_bytes == 0
        assert stats.history_size_bytes == 0
        assert stats.long_term_token_estimate == 0
        assert stats.history_entries == 0

    def test_get_stats_with_content(self, tmp_path: Path) -> None:
        provider = FileMemoryProvider(tmp_path)
        provider.write_long_term("# Facts\nUser likes Python.\nUser works at ACME.")
        provider.append_history("[2026-01-01 10:00] Discussed Python preferences.")
        provider.append_history("[2026-01-02 10:00] Discussed work projects.")

        stats = provider.get_stats()
        assert stats.long_term_size_bytes > 0
        assert stats.history_size_bytes > 0
        assert stats.long_term_token_estimate > 0
        assert stats.history_entries == 2

    def test_get_stats_single_entry(self, tmp_path: Path) -> None:
        provider = FileMemoryProvider(tmp_path)
        provider.append_history("[2026-03-01 09:00] Single entry.")

        stats = provider.get_stats()
        assert stats.history_entries == 1


class TestMemoryStats:
    """Test the MemoryStats dataclass."""

    def test_default_values(self) -> None:
        stats = MemoryStats()
        assert stats.long_term_size_bytes == 0
        assert stats.history_size_bytes == 0
        assert stats.long_term_token_estimate == 0
        assert stats.history_entries == 0
        assert stats.last_consolidation is None

    def test_custom_values(self) -> None:
        stats = MemoryStats(
            long_term_size_bytes=1024,
            history_size_bytes=2048,
            long_term_token_estimate=256,
            history_entries=10,
            last_consolidation="2026-03-19 10:00",
        )
        assert stats.long_term_size_bytes == 1024
        assert stats.history_entries == 10
        assert stats.last_consolidation == "2026-03-19 10:00"


class TestMemoryStoreBackwardCompat:
    """Ensure MemoryStore is fully backward compatible after refactor."""

    def test_is_subclass_of_file_memory_provider(self) -> None:
        assert issubclass(MemoryStore, FileMemoryProvider)

    def test_is_subclass_of_memory_provider(self) -> None:
        assert issubclass(MemoryStore, MemoryProvider)

    def test_constructor_unchanged(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        assert store.memory_dir == tmp_path / "memory"
        assert store.memory_file == tmp_path / "memory" / "MEMORY.md"
        assert store.history_file == tmp_path / "memory" / "HISTORY.md"

    def test_read_write_long_term(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        assert store.read_long_term() == ""
        store.write_long_term("test content")
        assert store.read_long_term() == "test content"

    def test_append_history(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        store.append_history("[2026-01-01 00:00] Test entry.")
        assert store.history_file.exists()
        assert "[2026-01-01 00:00] Test entry." in store.history_file.read_text()

    def test_get_memory_context(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        store.write_long_term("User is a developer.")
        ctx = store.get_memory_context()
        assert "## Long-term Memory" in ctx

    def test_has_consolidation_attributes(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        assert hasattr(store, "_consecutive_failures")
        assert store._consecutive_failures == 0
        assert hasattr(store, "consolidate")
        assert hasattr(store, "_fail_or_raw_archive")
        assert hasattr(store, "_raw_archive")

    def test_format_messages_static_method(self) -> None:
        messages = [
            {"role": "user", "content": "Hello", "timestamp": "2026-01-01 10:00:00"},
            {"role": "assistant", "content": "Hi there!", "timestamp": "2026-01-01 10:01:00"},
        ]
        result = MemoryStore._format_messages(messages)
        assert "[2026-01-01 10:00] USER: Hello" in result
        assert "[2026-01-01 10:01] ASSISTANT: Hi there!" in result

    def test_get_stats_via_memory_store(self, tmp_path: Path) -> None:
        """MemoryStore inherits get_stats from FileMemoryProvider."""
        store = MemoryStore(tmp_path)
        store.write_long_term("Some facts.")
        store.append_history("[2026-01-01 00:00] Entry.")

        stats = store.get_stats()
        assert isinstance(stats, MemoryStats)
        assert stats.long_term_size_bytes > 0
        assert stats.history_entries == 1


class TestCreateMemoryProvider:
    """Test the factory function."""

    def test_file_provider_returns_memory_store(self, tmp_path: Path) -> None:
        provider = create_memory_provider(tmp_path, "file")
        assert isinstance(provider, MemoryStore)
        assert isinstance(provider, FileMemoryProvider)
        assert isinstance(provider, MemoryProvider)

    def test_default_is_file(self, tmp_path: Path) -> None:
        provider = create_memory_provider(tmp_path)
        assert isinstance(provider, MemoryStore)

    def test_unknown_provider_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unknown memory provider"):
            create_memory_provider(tmp_path, "redis")

    def test_factory_creates_working_provider(self, tmp_path: Path) -> None:
        provider = create_memory_provider(tmp_path)
        provider.write_long_term("test content")
        assert provider.read_long_term() == "test content"


class TestMemoryConfig:
    """Test the MemoryConfig schema integration."""

    def test_default_config_has_memory(self) -> None:
        from nanobot.config.schema import Config

        config = Config()
        assert config.memory.provider == "file"

    def test_config_accepts_memory_section(self) -> None:
        from nanobot.config.schema import Config

        config = Config(memory={"provider": "file"})
        assert config.memory.provider == "file"
