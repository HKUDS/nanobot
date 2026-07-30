"""Tests for session fsync and flush_all on graceful shutdown."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from nanobot.session.manager import SessionManager, SQLiteSessionStore


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    return tmp_path


@pytest.fixture
def manager(sessions_dir: Path) -> SessionManager:
    return SessionManager(workspace=sessions_dir)


class TestSaveFsync:
    """Verify that durable saves use SQLite FULL synchronous mode."""

    def test_save_without_fsync_uses_normal_durability(self, manager: SessionManager):
        session = manager.get_or_create("test:no-fsync")
        session.add_message("user", "hello")
        store = cast(SQLiteSessionStore, manager._store)  # pyright: ignore[reportPrivateUsage]

        with patch.object(store, "_connection", wraps=store._connection) as connection:
            manager.save(session, fsync=False)
        connection.assert_called_once_with(durable=False)

    def test_save_with_fsync_uses_full_durability(self, manager: SessionManager):
        session = manager.get_or_create("test:with-fsync")
        session.add_message("user", "hello")
        store = cast(SQLiteSessionStore, manager._store)  # pyright: ignore[reportPrivateUsage]

        with patch.object(store, "_connection", wraps=store._connection) as connection:
            manager.save(session, fsync=True)
        connection.assert_called_once_with(durable=True)

    def test_save_default_no_fsync(self, manager: SessionManager):
        """Default save() should not fsync (backward compat)."""
        session = manager.get_or_create("test:default")
        session.add_message("user", "hello")
        store = cast(SQLiteSessionStore, manager._store)  # pyright: ignore[reportPrivateUsage]

        with patch.object(store, "_connection", wraps=store._connection) as connection:
            manager.save(session)
        connection.assert_called_once_with(durable=False)


class TestFlushAll:
    """Verify flush_all re-saves all cached sessions with fsync."""

    def test_flush_all_empty_cache(self, manager: SessionManager):
        assert manager.flush_all() == 0

    def test_flush_all_saves_cached_sessions(self, manager: SessionManager):
        s1 = manager.get_or_create("test:session-1")
        s1.add_message("user", "msg 1")
        manager.save(s1)

        s2 = manager.get_or_create("test:session-2")
        s2.add_message("user", "msg 2")
        manager.save(s2)

        flushed = manager.flush_all()
        assert flushed == 2

    def test_flush_all_uses_fsync(self, manager: SessionManager):
        session = manager.get_or_create("test:fsync-check")
        session.add_message("user", "important")
        manager.save(session)
        store = cast(SQLiteSessionStore, manager._store)  # pyright: ignore[reportPrivateUsage]

        with patch.object(store, "_connection", wraps=store._connection) as connection:
            manager.flush_all()
        connection.assert_called_once_with(durable=True)

    def test_flush_all_continues_on_error(self, manager: SessionManager):
        """One broken session should not prevent others from flushing."""
        s1 = manager.get_or_create("test:good")
        s1.add_message("user", "ok")
        manager.save(s1)

        s2 = manager.get_or_create("test:bad")
        s2.add_message("user", "ok")
        manager.save(s2)

        original_save = manager.save
        call_count = {"n": 0}

        def patched_save(session, *, fsync=False):
            call_count["n"] += 1
            if session.key == "test:bad":
                raise OSError("disk on fire")
            original_save(session, fsync=fsync)

        manager.save = patched_save
        flushed = manager.flush_all()

        # One succeeded, one failed — flush_all returns successful count
        assert flushed == 1
        assert call_count["n"] == 2

    def test_flush_all_data_survives_reload(self, sessions_dir: Path):
        """Data flushed by flush_all should survive a fresh SessionManager load."""
        mgr1 = SessionManager(workspace=sessions_dir)
        session = mgr1.get_or_create("test:persist")
        session.add_message("user", "remember this")
        session.add_message("assistant", "noted")
        mgr1.save(session)
        mgr1.flush_all()

        # Simulate process restart — new manager, cold cache
        mgr2 = SessionManager(workspace=sessions_dir)
        reloaded = mgr2.get_or_create("test:persist")
        history = reloaded.get_history(max_messages=100)

        assert len(history) == 2
        assert history[0]["content"] == "remember this"
        assert history[1]["content"] == "noted"


class TestLoadErrors:
    @pytest.mark.parametrize(
        "operation",
        ("get_or_create", "read_session_file", "read_session_metadata", "list_sessions"),
    )
    def test_permission_error_is_not_treated_as_corrupt_data(
        self,
        sessions_dir: Path,
        operation: str,
    ) -> None:
        writer = SessionManager(workspace=sessions_dir)
        session = writer.get_or_create("test:permission")
        session.add_message("user", "must not disappear")
        writer.save(session)

        reader = SessionManager(workspace=sessions_dir)
        store = cast(SQLiteSessionStore, reader._store)  # pyright: ignore[reportPrivateUsage]
        with patch.object(store, "_connection", side_effect=PermissionError("access denied")):
            with pytest.raises(PermissionError, match="access denied"):
                if operation == "list_sessions":
                    reader.list_sessions()
                else:
                    getattr(reader, operation)("test:permission")
