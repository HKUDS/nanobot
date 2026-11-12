"""Tests for SessionManager.delete_session and read_session_file."""

from pathlib import Path

from nanobot.session.manager import Session, SessionManager


def _seed(workspace: Path, key: str = "telegram:abc") -> SessionManager:
    sm = SessionManager(workspace)
    session = Session(key=key)
    session.add_message("user", "hello")
    session.add_message("assistant", "hi back")
    sm.save(session)
    return sm


def test_delete_session_removes_file_and_invalidates_cache(tmp_path: Path) -> None:
    sm = _seed(tmp_path, "telegram:abc")
    assert sm.read_session_snapshot("telegram:abc") is not None
    # Populate cache as a real consumer would.
    cached = sm.get_or_create("telegram:abc")
    assert cached.messages

    assert sm.delete_session("telegram:abc") is True
    assert sm.read_session_snapshot("telegram:abc") is None
    # Subsequent get_or_create returns a fresh, empty Session (no stale cache).
    fresh = sm.get_or_create("telegram:abc")
    assert fresh.messages == []


def test_delete_session_returns_false_when_missing(tmp_path: Path) -> None:
    sm = SessionManager(tmp_path)
    assert sm.delete_session("nope:none") is False


def test_delete_session_notifies_process_local_state_observer(tmp_path: Path) -> None:
    sm = _seed(tmp_path, "websocket:abc")
    deleted_keys: list[str] = []
    sm.set_delete_observer(deleted_keys.append)

    assert sm.delete_session("websocket:abc") is True
    assert sm.delete_session("websocket:missing") is False

    assert deleted_keys == ["websocket:abc", "websocket:missing"]


def test_read_session_file_returns_metadata_and_messages(tmp_path: Path) -> None:
    sm = _seed(tmp_path, "telegram:abc")
    data = sm.read_session_file("telegram:abc")
    assert data is not None
    assert data["key"] == "telegram:abc"
    assert isinstance(data["messages"], list)
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert data["created_at"]
    assert data["updated_at"]


def test_read_session_file_does_not_populate_cache(tmp_path: Path) -> None:
    sm = _seed(tmp_path, "telegram:abc")
    sm.invalidate("telegram:abc")
    assert sm.get_cached("telegram:abc") is None
    sm.read_session_file("telegram:abc")
    assert sm.get_cached("telegram:abc") is None


def test_read_session_file_missing(tmp_path: Path) -> None:
    sm = SessionManager(tmp_path)
    assert sm.read_session_file("nope:none") is None
