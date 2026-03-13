"""Tests for SQLite memory provider."""

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Import SQLite provider from examples
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "examples" / "memory-plugin-sqlite"))

from sqlite_memory_provider import SQLiteMemoryProvider


class TestSQLiteMemoryProviderBasic:
    """Test basic operations of SQLiteMemoryProvider."""

    @pytest.fixture
    def provider(self):
        """Create a temporary SQLite provider for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path})
        yield provider
        
        # Cleanup
        provider.close()
        Path(db_path).unlink(missing_ok=True)

    def test_provider_name(self, provider):
        """Test provider returns correct name."""
        assert provider.name == "sqlite"

    def test_is_available(self, provider):
        """Test provider reports availability correctly."""
        assert provider.is_available is True

    def test_read_long_term_empty(self, provider):
        """Test reading empty long-term memory."""
        assert provider.read_long_term() == ""

    def test_write_and_read_long_term(self, provider):
        """Test writing and reading long-term memory."""
        content = "# User Info\n\nName: Alice"
        provider.write_long_term(content)
        assert provider.read_long_term() == content

    def test_long_term_overwrite(self, provider):
        """Test that writing overwrites previous content."""
        provider.write_long_term("First content")
        provider.write_long_term("Second content")
        assert provider.read_long_term() == "Second content"

    def test_append_history(self, provider):
        """Test appending history entries."""
        provider.append_history("[2024-01-15 10:00] Test entry")
        
        results = provider.search_history()
        assert len(results) == 1
        assert "Test entry" in results[0].content

    def test_append_multiple_history(self, provider):
        """Test appending multiple history entries."""
        entries = [
            "[2024-01-15 10:00] First",
            "[2024-01-15 11:00] Second",
            "[2024-01-15 12:00] Third",
        ]
        for entry in entries:
            provider.append_history(entry)
        
        results = provider.search_history()
        assert len(results) == 3

    def test_get_memory_context_empty(self, provider):
        """Test memory context when empty."""
        assert provider.get_memory_context() == ""

    def test_get_memory_context_with_content(self, provider):
        """Test memory context with content."""
        provider.write_long_term("# Test")
        context = provider.get_memory_context()
        assert "## Long-term Memory" in context
        assert "# Test" in context


class TestSQLiteMemoryProviderSearch:
    """Test search functionality."""

    @pytest.fixture
    def provider_with_data(self):
        """Create provider with sample data."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path})
        
        # Add test entries
        entries = [
            "[2024-01-15 09:00] Working on Python project",
            "[2024-01-15 10:00] Debugging SQLite issues",
            "[2024-01-15 11:00] Writing tests for provider",
            "[2024-01-15 12:00] Python testing complete",
        ]
        for entry in entries:
            provider.append_history(entry)
        
        yield provider
        
        # Cleanup
        provider.close()
        Path(db_path).unlink(missing_ok=True)

    def test_search_by_keyword(self, provider_with_data):
        """Test searching history by keyword."""
        results = provider_with_data.search_history(query="Python")
        assert len(results) == 2
        assert all("Python" in r.content for r in results)

    def test_search_by_keyword_case_insensitive(self, provider_with_data):
        """Test search is case insensitive."""
        results_lower = provider_with_data.search_history(query="python")
        results_upper = provider_with_data.search_history(query="PYTHON")
        assert len(results_lower) == len(results_upper)

    def test_search_no_match(self, provider_with_data):
        """Test search with no matches."""
        results = provider_with_data.search_history(query="nonexistent")
        assert len(results) == 0

    def test_search_with_limit(self, provider_with_data):
        """Test search with limit."""
        results = provider_with_data.search_history(query="Python", limit=1)
        assert len(results) == 1

    def test_search_by_time_range(self, provider_with_data):
        """Test searching by time range."""
        start = datetime(2024, 1, 15, 10, 0)
        end = datetime(2024, 1, 15, 11, 0)
        
        results = provider_with_data.search_history(start_time=start, end_time=end)
        assert len(results) == 2  # 10:00 and 11:00 entries

    def test_search_by_start_time_only(self, provider_with_data):
        """Test searching with only start time."""
        start = datetime(2024, 1, 15, 11, 0)
        results = provider_with_data.search_history(start_time=start)
        assert len(results) == 2  # 11:00 and 12:00 entries

    def test_search_by_end_time_only(self, provider_with_data):
        """Test searching with only end time."""
        end = datetime(2024, 1, 15, 10, 0)
        results = provider_with_data.search_history(end_time=end)
        assert len(results) == 2  # 09:00 and 10:00 entries

    def test_search_combined_filters(self, provider_with_data):
        """Test search with both keyword and time filters."""
        start = datetime(2024, 1, 15, 10, 0)
        results = provider_with_data.search_history(query="Python", start_time=start)
        assert len(results) == 1  # Only 12:00 entry matches both


class TestSQLiteMemoryProviderTimeParsing:
    """Test timestamp parsing from history entries."""

    @pytest.fixture
    def provider(self):
        """Create a temporary SQLite provider."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path})
        yield provider
        
        provider.close()
        Path(db_path).unlink(missing_ok=True)

    def test_timestamp_parsing_standard_format(self, provider):
        """Test parsing standard [YYYY-MM-DD HH:MM] format."""
        provider.append_history("[2024-01-15 10:30] Test entry")
        
        results = provider.search_history()
        assert len(results) == 1
        assert results[0].timestamp.year == 2024
        assert results[0].timestamp.month == 1
        assert results[0].timestamp.day == 15
        assert results[0].timestamp.hour == 10
        assert results[0].timestamp.minute == 30

    def test_timestamp_parsing_invalid_format(self, provider):
        """Test handling of invalid timestamp format."""
        provider.append_history("[invalid] Test entry")
        
        results = provider.search_history()
        assert len(results) == 1
        # Should still have a timestamp (current time)
        assert isinstance(results[0].timestamp, datetime)

    def test_timestamp_parsing_no_brackets(self, provider):
        """Test entry without timestamp brackets."""
        provider.append_history("Plain text entry without timestamp")
        
        results = provider.search_history()
        assert len(results) == 1
        assert isinstance(results[0].timestamp, datetime)


class TestSQLiteMemoryProviderStats:
    """Test statistics functionality."""

    @pytest.fixture
    def provider(self):
        """Create a temporary SQLite provider."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path})
        yield provider
        
        provider.close()
        Path(db_path).unlink(missing_ok=True)

    def test_stats_empty(self, provider):
        """Test stats with empty memory."""
        stats = provider.get_stats()
        assert stats["history_entries"] == 0
        assert stats["long_term_size_bytes"] == 0
        assert stats["fts5_enabled"] == provider._use_fts5
        assert "database_path" in stats

    def test_stats_with_data(self, provider):
        """Test stats with data."""
        provider.write_long_term("Test content")
        provider.append_history("Entry 1")
        provider.append_history("Entry 2")
        
        stats = provider.get_stats()
        assert stats["history_entries"] == 2
        assert stats["long_term_size_bytes"] == len("Test content")


class TestSQLiteMemoryProviderClear:
    """Test clear functionality."""

    @pytest.fixture
    def provider(self):
        """Create a temporary SQLite provider."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path})
        yield provider
        
        provider.close()
        Path(db_path).unlink(missing_ok=True)

    def test_clear_long_term(self, provider):
        """Test clearing long-term memory."""
        provider.write_long_term("Content")
        provider.clear()
        assert provider.read_long_term() == ""

    def test_clear_history(self, provider):
        """Test clearing history."""
        provider.append_history("Entry")
        provider.clear()
        assert len(provider.search_history()) == 0

    def test_clear_stats(self, provider):
        """Test stats after clear."""
        provider.write_long_term("Content")
        provider.append_history("Entry")
        provider.clear()
        
        stats = provider.get_stats()
        assert stats["history_entries"] == 0
        assert stats["long_term_size_bytes"] == 0


class TestSQLiteMemoryProviderFTS5:
    """Test FTS5 full-text search functionality."""

    def test_fts5_detection(self):
        """Test FTS5 availability detection."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path})
        
        # Should detect FTS5 support (available in most modern SQLite builds)
        # We just check that the detection ran without error
        assert isinstance(provider._use_fts5, bool)
        
        provider.close()
        Path(db_path).unlink(missing_ok=True)

    def test_fts5_search(self):
        """Test FTS5 search if available."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path, "use_fts5": True})
        
        # Add entries
        provider.append_history("Working on Python project with SQLite")
        provider.append_history("Debugging database connections")
        
        # Search should work regardless of FTS5 availability
        results = provider.search_history(query="Python")
        assert len(results) == 1
        
        provider.close()
        Path(db_path).unlink(missing_ok=True)

    def test_fallback_without_fts5(self):
        """Test fallback to LIKE search when FTS5 disabled."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path, "use_fts5": False})
        
        provider.append_history("Test entry with Python")
        results = provider.search_history(query="Python")
        assert len(results) == 1
        
        provider.close()
        Path(db_path).unlink(missing_ok=True)


class TestSQLiteMemoryProviderSchema:
    """Test database schema creation."""

    def test_schema_created(self):
        """Test that schema is created on initialization."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path})
        provider.close()
        
        # Connect directly to verify schema
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        
        assert "long_term" in tables
        assert "history" in tables
        
        # FTS5 table may or may not exist depending on availability
        conn.close()
        Path(db_path).unlink(missing_ok=True)

    def test_long_term_constraint(self):
        """Test that long_term table only accepts id=1."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path})
        provider.close()
        
        conn = sqlite3.connect(db_path)
        # Should fail due to CHECK constraint
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO long_term (id, content) VALUES (2, 'test')")
        conn.close()
        
        Path(db_path).unlink(missing_ok=True)


class TestSQLiteMemoryProviderRegistration:
    """Test provider registration."""

    def test_provider_registered(self):
        """Test that provider is registered in MemoryProviderRegistry."""
        from nanobot.memory import MemoryProviderRegistry
        
        # Import should register the provider
        import sqlite_memory_provider  # noqa: F401
        
        assert "sqlite" in MemoryProviderRegistry.list_providers()

    def test_create_via_registry(self):
        """Test creating provider via registry."""
        from nanobot.memory import create_memory_provider
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = create_memory_provider("sqlite", {"db_path": db_path})
        assert isinstance(provider, SQLiteMemoryProvider)
        
        provider.close()
        Path(db_path).unlink(missing_ok=True)


class TestSQLiteMemoryProviderConfig:
    """Test configuration handling."""

    def test_default_db_path(self):
        """Test default database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Override home directory for testing
            import os
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = tmpdir
            
            try:
                provider = SQLiteMemoryProvider({})
                expected = Path(tmpdir) / ".nanobot" / "memory.db"
                assert provider._db_path == expected
                provider.close()
            finally:
                if old_home:
                    os.environ["HOME"] = old_home
                else:
                    del os.environ["HOME"]

    def test_custom_db_path(self):
        """Test custom database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "custom.db"
            provider = SQLiteMemoryProvider({"db_path": str(db_path)})
            assert provider._db_path == db_path
            provider.close()

    def test_expanded_user_path(self):
        """Test that ~ is expanded in db_path."""
        provider = SQLiteMemoryProvider({"db_path": "~/test.db"})
        assert "~" not in str(provider._db_path)
        assert provider._db_path.is_absolute()
        provider.close()
        # Cleanup
        if provider._db_path.exists():
            provider._db_path.unlink()


class TestSQLiteMemoryProviderEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def provider(self):
        """Create a temporary SQLite provider."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = SQLiteMemoryProvider({"db_path": db_path})
        yield provider
        
        provider.close()
        Path(db_path).unlink(missing_ok=True)

    def test_empty_string_long_term(self, provider):
        """Test writing empty string to long-term."""
        provider.write_long_term("")
        assert provider.read_long_term() == ""

    def test_unicode_content(self, provider):
        """Test handling unicode content."""
        content = "# 用户信息\n\n名字: 张三 🎉"
        provider.write_long_term(content)
        assert provider.read_long_term() == content

    def test_large_content(self, provider):
        """Test handling large content."""
        content = "Large content\n" * 10000
        provider.write_long_term(content)
        assert provider.read_long_term() == content

    def test_special_characters_in_history(self, provider):
        """Test special characters in history entries."""
        entry = "[2024-01-15 10:00] Special chars: ' \" \\ % _ *"
        provider.append_history(entry)
        results = provider.search_history()
        assert len(results) == 1
        assert "Special chars" in results[0].content

    def test_newlines_in_history(self, provider):
        """Test newlines in history entries."""
        entry = "[2024-01-15 10:00] Line 1\nLine 2\nLine 3"
        provider.append_history(entry)
        results = provider.search_history()
        assert len(results) == 1
        assert "Line 1" in results[0].content

    def test_very_long_history_entry(self, provider):
        """Test very long history entry."""
        entry = "[2024-01-15 10:00] " + "x" * 100000
        provider.append_history(entry)
        results = provider.search_history()
        assert len(results) == 1
        assert len(results[0].content) > 100000

    def test_multiple_consecutive_appends(self, provider):
        """Test multiple consecutive appends."""
        for i in range(100):
            provider.append_history(f"[2024-01-15 {i:02d}:00] Entry {i}")
        
        results = provider.search_history(limit=1000)
        assert len(results) == 100
