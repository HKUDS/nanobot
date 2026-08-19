from unittest.mock import MagicMock

import nanobot.session as session_api
from nanobot.session import Session, SessionManager
from nanobot.session.manager import SessionStore
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


def test_read_session_snapshot_does_not_populate_runtime_cache(tmp_path) -> None:
    stored = Session(key="websocket:context")
    store = MagicMock(spec=SessionStore)
    store.load.return_value = stored
    manager = SessionManager(tmp_path, store=store)

    assert manager.read_session_snapshot(stored.key) is stored
    assert manager.get_cached(stored.key) is None
    store.load.assert_called_once_with(stored.key)


def test_manager_preserves_full_session_before_store_save(tmp_path) -> None:
    store = MagicMock(spec=SessionStore)
    manager = SessionManager(tmp_path, store=store)
    session = Session(
        key="cli:large",
        messages=[
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": str(index),
            }
            for index in range(2_001)
        ],
    )

    manager.save(session)

    assert len(session.messages) == 2_001
    assert session.messages[0]["content"] == "0"
    assert session.messages[-1]["content"] == "2000"
    store.save.assert_called_once_with(session, fsync=False)
