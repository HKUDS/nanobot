from unittest.mock import MagicMock

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
