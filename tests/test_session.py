"""Tests for session management."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from nanobot.session.manager import Session, SessionManager


class TestSession:
    """Test cases for Session class."""

    def test_session_creation(self):
        """Test Session dataclass initialization."""
        session = Session(key="test:123")
        assert session.key == "test:123"
        assert session.messages == []
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.updated_at, datetime)
        assert session.metadata == {}
        assert session.last_consolidated == 0

    def test_add_message(self):
        """Test adding messages to a session."""
        session = Session(key="test:123")
        session.add_message("user", "Hello, world!")

        assert len(session.messages) == 1
        assert session.messages[0]["role"] == "user"
        assert session.messages[0]["content"] == "Hello, world!"
        assert "timestamp" in session.messages[0]
        assert isinstance(session.updated_at, datetime)

    def test_add_message_with_kwargs(self):
        """Test adding messages with additional metadata."""
        session = Session(key="test:123")
        session.add_message("user", "Test", extra="data", number=42)

        assert session.messages[0]["extra"] == "data"
        assert session.messages[0]["number"] == 42

    def test_add_multiple_messages(self):
        """Test adding multiple messages."""
        session = Session(key="test:123")
        session.add_message("user", "First")
        session.add_message("assistant", "Second")
        session.add_message("user", "Third")

        assert len(session.messages) == 3
        assert session.messages[0]["content"] == "First"
        assert session.messages[1]["content"] == "Second"
        assert session.messages[2]["content"] == "Third"

    def test_get_history_empty(self):
        """Test history retrieval from empty session."""
        session = Session(key="test:123")
        history = session.get_history()
        assert history == []

    def test_get_history_basic(self):
        """Test basic history retrieval."""
        session = Session(key="test:123")
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there")

        history = session.get_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_get_history_max_messages(self):
        """Test history retrieval with max_messages limit."""
        session = Session(key="test:123")
        for i in range(10):
            session.add_message("user", f"Message {i}")

        history = session.get_history(max_messages=5)
        assert len(history) == 5
        assert history[0]["content"] == "Message 5"
        assert history[4]["content"] == "Message 9"

    def test_get_history_alignment_to_user_turn(self):
        """Test that history aligns to user turns."""
        session = Session(key="test:123")
        session.add_message("assistant", "Orphaned message")
        session.add_message("user", "User message")
        session.add_message("assistant", "Assistant response")

        history = session.get_history()
        # Should drop the leading assistant message
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_get_history_with_tool_calls(self):
        """Test history retrieval preserves tool call information."""
        session = Session(key="test:123")
        session.add_message("user", "Search for something")
        session.add_message(
            "assistant",
            "I'll search for that",
            tool_calls=[{"id": "call_1", "name": "search", "arguments": {}}],
        )
        session.add_message("tool", "Search results", tool_call_id="call_1", name="search")

        history = session.get_history()
        assert len(history) == 3
        assert "tool_calls" in history[1]
        assert "tool_call_id" in history[2]
        assert "name" in history[2]

    def test_get_history_with_consolidation(self):
        """Test history retrieval respects consolidation point."""
        session = Session(key="test:123")
        # Add some messages
        for i in range(5):
            session.add_message("user", f"Message {i}")

        # Mark first 2 as consolidated
        session.last_consolidated = 2

        history = session.get_history()
        # Should only return unconsolidated messages
        assert len(history) == 3
        assert history[0]["content"] == "Message 2"

    def test_clear_session(self):
        """Test session clearing functionality."""
        session = Session(key="test:123")
        session.add_message("user", "Test")
        session.add_message("assistant", "Response")

        session.clear()

        assert session.messages == []
        assert session.last_consolidated == 0
        assert isinstance(session.updated_at, datetime)

    def test_clear_session_with_consolidation(self):
        """Test clearing session with consolidation."""
        session = Session(key="test:123")
        session.add_message("user", "Test")
        session.last_consolidated = 1

        session.clear()

        assert session.messages == []
        assert session.last_consolidated == 0


class TestSessionManager:
    """Test cases for SessionManager class."""

    def test_session_manager_init(self, mock_workspace):
        """Test SessionManager initialization."""
        manager = SessionManager(mock_workspace)

        assert manager.workspace == mock_workspace
        assert manager.sessions_dir == mock_workspace / "sessions"
        assert manager._cache == {}
        assert isinstance(manager.legacy_sessions_dir, Path)

    def test_get_or_create_new_session(self, mock_workspace):
        """Test creating a new session."""
        manager = SessionManager(mock_workspace)

        session = manager.get_or_create("test:123")

        assert session.key == "test:123"
        assert session.messages == []
        assert "test:123" in manager._cache

    def test_get_or_create_existing_session(self, mock_workspace):
        """Test retrieving an existing session."""
        manager = SessionManager(mock_workspace)

        # Create session first
        session1 = manager.get_or_create("test:123")
        session1.add_message("user", "Test message")

        # Retrieve same session
        session2 = manager.get_or_create("test:123")

        assert session1 is session2
        assert len(session2.messages) == 1

    def test_get_or_create_from_cache(self, mock_workspace):
        """Test that sessions are cached."""
        manager = SessionManager(mock_workspace)

        session1 = manager.get_or_create("test:123")
        session2 = manager.get_or_create("test:123")

        # Should return the same cached instance
        assert session1 is session2

    def test_save_session(self, mock_workspace):
        """Test saving a session to disk."""
        manager = SessionManager(mock_workspace)
        session = manager.get_or_create("test:123")
        session.add_message("user", "Test message")

        manager.save(session)

        # Check file was created
        session_file = manager.sessions_dir / "test_123.jsonl"
        assert session_file.exists()

        # Check file content
        content = session_file.read_text()
        assert "metadata" in content
        assert "Test message" in content

    def test_save_session_with_metadata(self, mock_workspace):
        """Test saving session with metadata."""
        manager = SessionManager(mock_workspace)
        session = manager.get_or_create("test:123")
        session.metadata = {"user_id": "test_user", "platform": "telegram"}
        session.add_message("user", "Test")

        manager.save(session)

        session_file = manager.sessions_dir / "test_123.jsonl"
        content = session_file.read_text()
        assert "user_id" in content
        assert "test_user" in content

    def test_load_session(self, mock_workspace):
        """Test loading a session from disk."""
        manager = SessionManager(mock_workspace)

        # Create and save a session
        session1 = manager.get_or_create("test:123")
        session1.add_message("user", "Test message")
        manager.save(session1)

        # Clear cache
        manager.invalidate("test:123")

        # Load session
        session2 = manager.get_or_create("test:123")

        assert session2.key == "test:123"
        assert len(session2.messages) == 1
        assert session2.messages[0]["content"] == "Test message"

    def test_load_session_with_consolidation(self, mock_workspace):
        """Test loading session with consolidation state."""
        manager = SessionManager(mock_workspace)

        # Create session with consolidation
        session1 = manager.get_or_create("test:123")
        session1.add_message("user", "Message 1")
        session1.add_message("user", "Message 2")
        session1.last_consolidated = 1
        manager.save(session1)

        # Clear cache and reload
        manager.invalidate("test:123")
        session2 = manager.get_or_create("test:123")

        assert session2.last_consolidated == 1

    def test_invalidate_cache(self, mock_workspace):
        """Test cache invalidation."""
        manager = SessionManager(mock_workspace)

        session = manager.get_or_create("test:123")
        manager.invalidate("test:123")

        assert "test:123" not in manager._cache

    def test_list_sessions_empty(self, mock_workspace):
        """Test listing sessions when none exist."""
        manager = SessionManager(mock_workspace)
        sessions = manager.list_sessions()

        assert sessions == []

    def test_list_sessions(self, mock_workspace):
        """Test listing all sessions."""
        manager = SessionManager(mock_workspace)

        # Create multiple sessions
        session1 = manager.get_or_create("test:123")
        session1.add_message("user", "Message 1")
        manager.save(session1)

        session2 = manager.get_or_create("test:456")
        session2.add_message("user", "Message 2")
        manager.save(session2)

        # Clear cache
        manager.invalidate("test:123")
        manager.invalidate("test:456")

        # List sessions
        sessions = manager.list_sessions()

        assert len(sessions) == 2
        session_keys = [s["key"] for s in sessions]
        assert "test:123" in session_keys
        assert "test:456" in session_keys

    def test_list_sessions_sorted_by_updated(self, mock_workspace):
        """Test that sessions are sorted by updated time."""
        manager = SessionManager(mock_workspace)

        # Create sessions with different update times
        session1 = manager.get_or_create("test:123")
        manager.save(session1)

        import time

        time.sleep(0.01)  # Small delay

        session2 = manager.get_or_create("test:456")
        manager.save(session2)

        # Clear cache
        manager.invalidate("test:123")
        manager.invalidate("test:456")

        # List sessions
        sessions = manager.list_sessions()

        # Most recently updated should be first
        assert sessions[0]["key"] == "test:456"
        assert sessions[1]["key"] == "test:123"

    def test_close_session(self, mock_workspace):
        """Test closing a specific session."""
        manager = SessionManager(mock_workspace)

        session = manager.get_or_create("test:123")
        session.add_message("user", "Test")
        manager.save(session)

        success = manager.close_session("test:123")

        assert success is True
        assert "test:123" not in manager._cache

    def test_close_nonexistent_session(self, mock_workspace):
        """Test closing a session that doesn't exist."""
        manager = SessionManager(mock_workspace)

        success = manager.close_session("nonexistent")

        assert success is False

    def test_session_file_path_generation(self, mock_workspace):
        """Test session file path generation."""
        manager = SessionManager(mock_workspace)

        path = manager._get_session_path("test:123")

        assert path == manager.sessions_dir / "test_123.jsonl"

    def test_legacy_session_path_generation(self, mock_workspace):
        """Test legacy session path generation."""
        manager = SessionManager(mock_workspace)

        path = manager._get_legacy_session_path("test:123")

        assert "test_123.jsonl" in str(path)

    def test_load_nonexistent_session(self, mock_workspace):
        """Test loading a session that doesn't exist."""
        manager = SessionManager(mock_workspace)

        session = manager.get_or_create("nonexistent:123")

        assert session.key == "nonexistent:123"
        assert session.messages == []

    def test_save_updates_cache(self, mock_workspace):
        """Test that save updates the cache."""
        manager = SessionManager(mock_workspace)

        session = manager.get_or_create("test:123")
        session.add_message("user", "Test")
        manager.save(session)

        # Session should be in cache
        cached = manager._cache.get("test:123")
        assert cached is not None
        assert len(cached.messages) == 1

    def test_multiple_managers_same_workspace(self, mock_workspace):
        """Test multiple managers with same workspace."""
        manager1 = SessionManager(mock_workspace)
        manager2 = SessionManager(mock_workspace)

        session1 = manager1.get_or_create("test:123")
        session1.add_message("user", "Test")
        manager1.save(session1)

        # Second manager should be able to load the session
        session2 = manager2.get_or_create("test:123")

        assert len(session2.messages) == 1

    def test_session_with_special_characters_in_key(self, mock_workspace):
        """Test session with special characters in key."""
        manager = SessionManager(mock_workspace)

        session = manager.get_or_create("test:123@domain.com")
        session.add_message("user", "Test")
        manager.save(session)

        # Should be able to load it back
        manager.invalidate("test:123@domain.com")
        loaded = manager.get_or_create("test:123@domain.com")

        assert len(loaded.messages) == 1

    def test_session_with_unicode_content(self, mock_workspace):
        """Test session with unicode content."""
        manager = SessionManager(mock_workspace)

        session = manager.get_or_create("test:123")
        session.add_message("user", "Hello 世界 🌍")
        manager.save(session)

        # Load and verify
        manager.invalidate("test:123")
        loaded = manager.get_or_create("test:123")

        assert loaded.messages[0]["content"] == "Hello 世界 🌍"

    def test_large_message_truncation(self, mock_workspace):
        """Test that large tool results are truncated."""
        manager = SessionManager(mock_workspace)

        session = manager.get_or_create("test:123")
        # Add a very large message
        large_content = "x" * 20000
        session.add_message("tool", large_content, tool_call_id="call_1", name="test")

        # Get history with truncation
        history = session.get_history()

        # Tool results should be truncated
        assert len(history[0]["content"]) < 20000
        assert "truncated" in history[0]["content"].lower()

    def test_session_persistence_across_restarts(self, mock_workspace):
        """Test that sessions persist across manager restarts."""
        # Create and save session
        manager1 = SessionManager(mock_workspace)
        session1 = manager1.get_or_create("test:123")
        session1.add_message("user", "Persistent message")
        manager1.save(session1)

        # Create new manager instance
        manager2 = SessionManager(mock_workspace)
        session2 = manager2.get_or_create("test:123")

        # Session should be loaded from disk
        assert len(session2.messages) == 1
        assert session2.messages[0]["content"] == "Persistent message"
