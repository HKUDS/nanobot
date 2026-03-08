from pathlib import Path

import pytest

from nanobot.session.manager import Session, SessionManager


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


def test_get_or_create_uses_cache(isolated_home):
    """Reuses cached session objects for repeated key lookups."""
    manager = SessionManager(Path("/unused"))
    s1 = manager.get_or_create("cli:abc")
    s2 = manager.get_or_create("cli:abc")
    assert s1 is s2


def test_invalidate_forces_reload(isolated_home):
    """Reloads a persisted session after cache invalidation."""
    manager = SessionManager(Path("/unused"))
    session = Session(key="cli:abc")
    session.add_message("user", "hello")
    manager.save(session)

    cached = manager.get_or_create("cli:abc")
    manager.invalidate("cli:abc")
    reloaded = manager.get_or_create("cli:abc")

    assert cached is not reloaded
    assert reloaded.messages[0]["content"] == "hello"


def test_load_invalid_jsonl_returns_new_session(isolated_home):
    """Falls back to a new empty session when JSONL is corrupt."""
    manager = SessionManager(Path("/unused"))
    bad_path = manager._get_session_path("cli:broken")
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("{not json}\n")

    session = manager.get_or_create("cli:broken")
    assert session.key == "cli:broken"
    assert session.messages == []


def test_get_session_path_sanitizes_key(isolated_home):
    """Sanitizes unsafe characters when deriving session file paths."""
    manager = SessionManager(Path("/unused"))
    path = manager._get_session_path("discord:chan/<bad>|name")
    assert "<" not in path.name
    assert ">" not in path.name
    assert "/" not in path.name


def test_save_roundtrip_metadata_and_last_consolidated(isolated_home):
    """Persists metadata and last_consolidated across save/load."""
    manager = SessionManager(Path("/unused"))
    session = Session(key="cli:roundtrip")
    session.metadata["foo"] = "bar"
    session.last_consolidated = 3
    for i in range(5):
        session.add_message("user", f"m{i}")

    manager.save(session)
    manager.invalidate(session.key)
    loaded = manager.get_or_create(session.key)

    assert loaded.metadata == {"foo": "bar"}
    assert loaded.last_consolidated == 3
    assert len(loaded.messages) == 5


def test_list_sessions_sorted_by_updated_at_desc(isolated_home):
    """Lists sessions sorted by updated_at in descending order."""
    manager = SessionManager(Path("/unused"))
    a = Session(key="cli:one")
    b = Session(key="cli:two")
    a.updated_at = b.updated_at.replace(year=b.updated_at.year - 1)
    manager.save(a)
    manager.save(b)

    sessions = manager.list_sessions()
    assert len(sessions) == 2
    assert sessions[0]["key"] == "cli:two"
