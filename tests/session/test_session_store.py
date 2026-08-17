from unittest.mock import MagicMock

import pytest

import nanobot.session as session_api
from nanobot.session import Session, SessionManager
from nanobot.session.manager import FILE_MAX_MESSAGES, SessionStore
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY


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


def test_manager_renames_model_preset_in_live_and_persisted_sessions(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    sessions_root = tmp_path / "sessions"
    manager = SessionManager(workspace, sessions_root=sessions_root)
    selected = manager.get_or_create("websocket:selected")
    selected.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "openai"
    manager.save(selected)
    other = manager.get_or_create("websocket:other")
    other.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "backup"
    manager.save(other)
    transient = manager.get_or_create_transient("websocket:temporary")
    transient.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "openai"

    assert manager.rename_model_preset("openai", "Codex") == 2
    assert selected.metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "Codex"
    assert transient.metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "Codex"

    reloaded = SessionManager(workspace, sessions_root=sessions_root)
    assert (
        reloaded.get_or_create("websocket:selected").metadata[
            SESSION_MODEL_PRESET_METADATA_KEY
        ]
        == "Codex"
    )
    assert (
        reloaded.get_or_create("websocket:other").metadata[
            SESSION_MODEL_PRESET_METADATA_KEY
        ]
        == "backup"
    )


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
