from copy import deepcopy
from unittest.mock import MagicMock

import pytest

import nanobot.session as session_api
from nanobot.session import Session, SessionManager
from nanobot.session.manager import FILE_MAX_MESSAGES, SessionStore


def test_store_types_are_not_public_session_api() -> None:
    assert not hasattr(session_api, "SessionStore")
    assert not hasattr(session_api, "JsonlSessionStore")


def test_manager_delegates_persistence_to_store(tmp_path) -> None:
    stored = Session(key="cli:test")
    stored.add_message("user", "hello")
    payload = {
        "key": stored.key,
        "created_at": stored.created_at.isoformat(),
        "updated_at": stored.updated_at.isoformat(),
        "metadata": {},
        "messages": stored.messages,
    }
    metadata = {
        "key": stored.key,
        "created_at": stored.created_at.isoformat(),
        "updated_at": stored.updated_at.isoformat(),
        "metadata": {},
    }
    listing = [
        {
            "key": stored.key,
            "created_at": stored.created_at.isoformat(),
            "updated_at": stored.updated_at.isoformat(),
            "title": "",
            "preview": "hello",
            "path": "session.db",
        }
    ]
    store = MagicMock(spec=SessionStore)
    store.load.return_value = stored
    store.read.return_value = payload
    store.read_metadata.return_value = metadata
    store.list_sessions.return_value = listing
    store.delete.return_value = True
    manager = SessionManager(tmp_path, store=store)

    assert manager.get_or_create(stored.key) is stored
    assert manager.get_or_create(stored.key) is stored
    store.load.assert_called_once_with(stored.key)

    manager.save(stored, fsync=True)
    store.save.assert_called_once_with(stored, fsync=True)
    assert manager.read_session_file(stored.key) == payload
    assert manager.read_session_metadata(stored.key) == metadata
    assert manager.list_sessions() == listing

    assert manager.delete_session(stored.key) is True
    store.delete.assert_called_once_with(stored.key)
    assert manager.get_cached(stored.key) is None


def test_manager_applies_file_cap_before_store_save(tmp_path) -> None:
    store = MagicMock(spec=SessionStore)
    archiver = MagicMock()
    manager = SessionManager(tmp_path, store=store)
    manager.set_file_cap_archiver(archiver)
    session = Session(
        key="cli:large",
        messages=[
            {"role": "user", "content": str(index)}
            for index in range(FILE_MAX_MESSAGES + 1)
        ],
    )

    manager.save(session)

    assert len(session.messages) == FILE_MAX_MESSAGES
    archiver.assert_called_once()
    store.save.assert_called_once_with(session, fsync=False)


def test_manager_retries_file_cap_archive_after_failure(tmp_path) -> None:
    store = MagicMock(spec=SessionStore)
    archiver = MagicMock(side_effect=[RuntimeError("history unavailable"), None])
    manager = SessionManager(tmp_path, store=store)
    manager.set_file_cap_archiver(archiver)
    session = Session(
        key="cli:retry-large",
        messages=[
            {"role": "user", "content": str(index)}
            for index in range(FILE_MAX_MESSAGES + 1)
        ],
    )

    with pytest.raises(RuntimeError, match="history unavailable"):
        manager.save(session)

    assert len(session.messages) == FILE_MAX_MESSAGES + 1
    store.save.assert_not_called()

    manager.save(session)

    assert len(session.messages) == FILE_MAX_MESSAGES
    assert archiver.call_count == 2
    assert archiver.call_args_list[0].args[0][0]["content"] == "0"
    assert archiver.call_args_list[1].args[0][0]["content"] == "0"
    store.save.assert_called_once_with(session, fsync=False)


def test_save_discards_stale_reference_after_invalidate(tmp_path) -> None:
    """save() must reject a Session object that is no longer in the cache."""
    store = MagicMock(spec=SessionStore)
    original = Session(key="test:stale")
    original.add_message("user", "hello")
    replacement = Session(key="test:stale")
    replacement.add_message("user", "new message")
    store.load.side_effect = [original, replacement]
    manager = SessionManager(tmp_path, store=store)

    # First get_or_create loads original.
    assert manager.get_or_create("test:stale") is original
    # Simulate /new: invalidate then create a new session.
    manager.invalidate("test:stale")
    assert manager.get_or_create("test:stale") is replacement

    store.save.reset_mock()
    manager.save(original)

    # The stale save must be discarded.
    store.save.assert_not_called()
    # The replacement must still be in cache.
    assert manager.get_cached("test:stale") is replacement


def test_save_accepts_current_cached_object(tmp_path) -> None:
    """save() of the currently-cached object must proceed normally."""
    store = MagicMock(spec=SessionStore)
    store.load.return_value = None
    manager = SessionManager(tmp_path, store=store)

    session = manager.get_or_create("test:current")
    session.add_message("user", "hello")

    store.save.reset_mock()
    manager.save(session)

    store.save.assert_called_once_with(session, fsync=False)


def test_save_discards_invalidated_reference_even_if_cache_is_empty(tmp_path) -> None:
    """Invalidation must revoke the old object even before a replacement is loaded."""
    store = MagicMock(spec=SessionStore)
    store.load.return_value = None
    manager = SessionManager(tmp_path, store=store)

    session = manager.get_or_create("test:orphan")
    manager.invalidate("test:orphan")
    store.save.reset_mock()

    manager.save(session)

    store.save.assert_not_called()
    assert manager.get_cached("test:orphan") is None


def test_save_discards_rejected_competing_reference_after_invalidate(tmp_path) -> None:
    """A rejected runtime copy stays stale without poisoning the current object."""
    store = MagicMock(spec=SessionStore)
    store.load.return_value = None
    manager = SessionManager(tmp_path, store=store)

    current = manager.get_or_create("test:competing")
    competing = deepcopy(current)
    competing.add_message("user", "stale alternate data")

    manager.save(competing)
    store.save.assert_not_called()

    manager.save(current)
    store.save.assert_called_once_with(current, fsync=False)

    store.save.reset_mock()
    manager.invalidate(current.key)
    manager.save(competing)

    store.save.assert_not_called()


def test_save_accepts_unmanaged_replacement_for_compatibility(tmp_path) -> None:
    """Callers may still intentionally replace a cached session with a fresh object."""
    store = MagicMock(spec=SessionStore)
    store.load.return_value = None
    manager = SessionManager(tmp_path, store=store)

    original = manager.get_or_create("test:replacement")
    replacement = Session(key=original.key)
    replacement.add_message("user", "replacement data")

    manager.save(replacement)

    store.save.assert_called_once_with(replacement, fsync=False)
    assert manager.get_cached(original.key) is replacement

    store.save.reset_mock()
    manager.save(original)
    store.save.assert_not_called()


def test_invalidate_revokes_runtime_copy_of_cached_session(tmp_path) -> None:
    """Copying a managed object must not create an invalidation escape hatch."""
    store = MagicMock(spec=SessionStore)
    store.load.return_value = None
    manager = SessionManager(tmp_path, store=store)

    current = manager.get_or_create("test:copied")
    copied = deepcopy(current)
    copied.add_message("user", "stale copied data")
    manager.invalidate(current.key)
    manager.save(copied)

    store.save.assert_not_called()
