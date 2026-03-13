"""Tests for memory plugin system."""

import pytest
import tempfile
from datetime import datetime
from pathlib import Path

from nanobot.memory import (
    BaseMemoryProvider,
    MemoryEntry,
    MemoryProviderRegistry,
    create_memory_provider,
    FilesystemMemoryProvider,
)
from nanobot.memory.providers import InMemoryProvider
from nanobot.agent.memory import MemoryStore, MemoryConsolidator
from nanobot.agent.context import ContextBuilder


class TestBaseMemoryProvider:
    """Test BaseMemoryProvider interface."""

    def test_in_memory_provider_basic_operations(self):
        """Test basic CRUD operations with in-memory provider."""
        provider = InMemoryProvider()
        
        # Test long-term memory
        provider.write_long_term("# Test\n\nHello World")
        assert provider.read_long_term() == "# Test\n\nHello World"
        
        # Test history
        provider.append_history("[2024-01-15 10:30] Test entry")
        assert provider.history_count == 1
        
        # Test search
        results = provider.search_history(query="Test")
        assert len(results) == 1
        assert "Test entry" in results[0].content

    def test_in_memory_provider_search_with_filters(self):
        """Test history search with time filters."""
        provider = InMemoryProvider()
        
        # Add entries with different timestamps
        provider.append_history("[2024-01-15 10:00] Entry 1")
        provider.append_history("[2024-01-15 11:00] Entry 2")
        provider.append_history("[2024-01-15 12:00] Entry 3")
        
        # Test search with query
        results = provider.search_history(query="Entry 2")
        assert len(results) == 1
        
        # Test search with time filter
        start = datetime(2024, 1, 15, 11, 0)
        results = provider.search_history(start_time=start)
        assert len(results) == 2  # Entry 2 and 3

    def test_in_memory_provider_clear(self):
        """Test clearing memory."""
        provider = InMemoryProvider()
        provider.write_long_term("Content")
        provider.append_history("Entry")
        
        provider.clear()
        assert provider.read_long_term() == ""
        assert provider.history_count == 0


class TestFilesystemMemoryProvider:
    """Test FilesystemMemoryProvider."""

    def test_filesystem_provider_creates_files(self):
        """Test that filesystem provider creates memory files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = FilesystemMemoryProvider({"workspace": tmpdir})
            
            provider.write_long_term("# Long Term\n\nContent")
            provider.append_history("[2024-01-15 10:30] History")
            
            # Check files exist
            assert provider.memory_file.exists()
            assert provider.history_file.exists()
            
            # Check content
            assert "# Long Term" in provider.memory_file.read_text()
            assert "History" in provider.history_file.read_text()

    def test_filesystem_provider_read_write(self):
        """Test read/write operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = FilesystemMemoryProvider({"workspace": tmpdir})
            
            # Write and read long-term
            provider.write_long_term("Test content")
            assert provider.read_long_term() == "Test content"
            
            # Append history
            provider.append_history("Entry 1")
            provider.append_history("Entry 2")
            
            results = provider.search_history()
            assert len(results) == 2


class TestMemoryProviderRegistry:
    """Test MemoryProviderRegistry."""

    def test_list_providers_includes_builtins(self):
        """Test that built-in providers are registered."""
        providers = MemoryProviderRegistry.list_providers()
        assert "filesystem" in providers
        assert "in_memory" in providers

    def test_create_provider_by_name(self):
        """Test creating providers by name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = create_memory_provider("filesystem", {"workspace": tmpdir})
            assert isinstance(provider, FilesystemMemoryProvider)
            
            provider2 = create_memory_provider("in_memory")
            assert isinstance(provider2, InMemoryProvider)

    def test_create_unknown_provider_raises(self):
        """Test that creating unknown provider raises error."""
        with pytest.raises(ValueError, match="Unknown memory provider"):
            create_memory_provider("unknown_provider")

    def test_register_custom_provider(self):
        """Test registering a custom provider."""
        
        class CustomProvider(BaseMemoryProvider):
            @property
            def name(self):
                return "custom"
            
            def read_long_term(self):
                return "custom"
            
            def write_long_term(self, content):
                pass
            
            def append_history(self, entry):
                pass
            
            def search_history(self, **kwargs):
                return []
        
        MemoryProviderRegistry.register("custom_test", CustomProvider)
        
        provider = create_memory_provider("custom_test")
        assert isinstance(provider, CustomProvider)
        
        # Cleanup
        MemoryProviderRegistry.unregister("custom_test")


class TestMemoryStoreWithProvider:
    """Test MemoryStore with custom providers."""

    def test_memory_store_with_custom_provider(self):
        """Test MemoryStore delegates to custom provider."""
        provider = InMemoryProvider()
        store = MemoryStore(Path("/tmp"), provider=provider)
        
        assert store.provider == provider
        
        store.write_long_term("Test")
        assert provider.read_long_term() == "Test"

    def test_memory_store_default_provider(self):
        """Test MemoryStore uses filesystem provider by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir))
            assert isinstance(store.provider, FilesystemMemoryProvider)


class TestContextBuilderWithProvider:
    """Test ContextBuilder with custom providers."""

    def test_context_builder_with_custom_provider(self):
        """Test ContextBuilder accepts custom memory provider."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = InMemoryProvider()
            ctx = ContextBuilder(Path(tmpdir), memory_provider=provider)
            
            assert ctx.memory.provider == provider

    def test_context_builder_default_provider(self):
        """Test ContextBuilder uses default provider when none specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = ContextBuilder(Path(tmpdir))
            assert isinstance(ctx.memory.provider, FilesystemMemoryProvider)


class TestMemoryEntry:
    """Test MemoryEntry dataclass."""

    def test_memory_entry_to_dict(self):
        """Test serialization to dict."""
        entry = MemoryEntry(
            content="Test",
            timestamp=datetime(2024, 1, 15, 10, 30),
            metadata={"key": "value"},
            entry_type="history",
        )
        
        data = entry.to_dict()
        assert data["content"] == "Test"
        assert data["entry_type"] == "history"
        assert "timestamp" in data

    def test_memory_entry_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "content": "Test",
            "timestamp": "2024-01-15T10:30:00",
            "metadata": {},
            "entry_type": "long_term",
        }
        
        entry = MemoryEntry.from_dict(data)
        assert entry.content == "Test"
        assert entry.entry_type == "long_term"
