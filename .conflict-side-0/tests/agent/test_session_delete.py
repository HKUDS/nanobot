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
    file_path = sm._get_session_path("telegram:abc")
    assert file_path.exists()
    # Populate cache as a real consumer would.
    cached = sm.get_or_create("telegram:abc")
    assert cached.messages

    assert sm.delete_session("telegram:abc") is True
    assert not file_path.exists()
    # Subsequent get_or_create returns a fresh, empty Session (no stale cache).
    fresh = sm.get_or_create("telegram:abc")
    assert fresh.messages == []


def test_delete_session_returns_false_when_missing(tmp_path: Path) -> None:
    sm = SessionManager(tmp_path)
    assert sm.delete_session("nope:none") is False


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
    assert "telegram:abc" not in sm._cache
    sm.read_session_file("telegram:abc")
    assert "telegram:abc" not in sm._cache


def test_read_session_file_missing(tmp_path: Path) -> None:
    sm = SessionManager(tmp_path)
    assert sm.read_session_file("nope:none") is None


def test_safe_key_matches_internal_path(tmp_path: Path) -> None:
    sm = SessionManager(tmp_path)
    key = "telegram:abc/def"
    expected = sm._get_session_path(key).name
    assert SessionManager.safe_key(key) + ".jsonl" == expected
