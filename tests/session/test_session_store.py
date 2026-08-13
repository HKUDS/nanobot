from unittest.mock import MagicMock

import pytest

import nanobot.session as session_api
import nanobot.session.manager as manager_module
from nanobot.session import Session, SessionManager
from nanobot.session.manager import (
    FILE_MAX_MESSAGES,
    JsonlSessionStore,
    SessionStore,
    _replace_with_retry,
)


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


def test_jsonl_store_save_and_load_round_trip(tmp_path) -> None:
    store = JsonlSessionStore(tmp_path)
    session = Session(key="cli:round-trip")
    session.add_message("user", "hello")

    store.save(session)
    loaded = store.load(session.key)

    assert loaded is not None
    assert loaded.messages == session.messages


def test_replace_with_retry_recovers_from_transient_permission_error(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(manager_module.sys, "platform", "win32")
    monkeypatch.setattr(manager_module.time, "sleep", lambda _seconds: None)
    attempts = {"count": 0}
    real_replace = manager_module.os.replace

    def flaky_replace(src, dst):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("[WinError 5] Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(manager_module.os, "replace", flaky_replace)

    tmp_path_file = tmp_path / "session.jsonl.tmp"
    target_path = tmp_path / "session.jsonl"
    tmp_path_file.write_text("data", encoding="utf-8")

    _replace_with_retry(tmp_path_file, target_path)

    assert attempts["count"] == 3
    assert target_path.read_text(encoding="utf-8") == "data"


def test_replace_with_retry_reraises_after_exhausting_attempts(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(manager_module.sys, "platform", "win32")
    monkeypatch.setattr(manager_module.time, "sleep", lambda _seconds: None)
    attempts = {"count": 0}

    def always_fails(src, dst):
        attempts["count"] += 1
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(manager_module.os, "replace", always_fails)

    tmp_path_file = tmp_path / "session.jsonl.tmp"
    target_path = tmp_path / "session.jsonl"
    tmp_path_file.write_text("data", encoding="utf-8")

    with pytest.raises(PermissionError):
        _replace_with_retry(tmp_path_file, target_path)

    assert attempts["count"] == manager_module._REPLACE_RETRY_ATTEMPTS


def test_replace_with_retry_no_retry_on_non_windows(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(manager_module.sys, "platform", "linux")
    attempts = {"count": 0}

    def always_fails(src, dst):
        attempts["count"] += 1
        raise PermissionError("simulated")

    monkeypatch.setattr(manager_module.os, "replace", always_fails)

    tmp_path_file = tmp_path / "session.jsonl.tmp"
    target_path = tmp_path / "session.jsonl"
    tmp_path_file.write_text("data", encoding="utf-8")

    with pytest.raises(PermissionError):
        _replace_with_retry(tmp_path_file, target_path)

    assert attempts["count"] == 1
