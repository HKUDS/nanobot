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


def _write_legacy_session(legacy_dir: Path, key: str, roles: list[str]) -> Path:
    legacy_dir.mkdir(parents=True, exist_ok=True)
    safe = SessionManager.safe_key(key)
    path = legacy_dir / f"{safe}.jsonl"
    metadata_line = (
        '{"_type":"metadata","key":"' + key + '",'
        '"created_at":"2025-01-01T00:00:00",'
        '"updated_at":"2025-01-01T00:00:00",'
        '"metadata":{}}'
    )
    lines = [metadata_line]
    for role in roles:
        lines.append('{"role":"' + role + '","content":"msg"}')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_delete_session_cleans_legacy_file(tmp_path: Path, monkeypatch) -> None:
    """A session that only exists at the legacy location must also be deleted."""
    legacy = tmp_path / "legacy_sessions"
    monkeypatch.setattr(
        "nanobot.session.manager.get_legacy_sessions_dir",
        lambda: legacy,
    )
    key = "telegram:only-legacy"
    legacy_path = _write_legacy_session(legacy, key, ["user", "assistant"])
    assert legacy_path.exists()

    sm = SessionManager(tmp_path / "workspace")
    new_path = sm._get_session_path(key)
    assert not new_path.exists()

    assert sm.delete_session(key) is True
    assert not legacy_path.exists(), "legacy session file should have been removed"


def test_delete_session_cleans_both_locations(tmp_path: Path, monkeypatch) -> None:
    """When files exist at both the new and legacy paths, both must be removed."""
    legacy = tmp_path / "legacy_sessions"
    monkeypatch.setattr(
        "nanobot.session.manager.get_legacy_sessions_dir",
        lambda: legacy,
    )
    workspace = tmp_path / "workspace"
    key = "telegram:both-paths"
    _write_legacy_session(legacy, key, ["user", "assistant"])

    sm = SessionManager(workspace)
    session = Session(key=key)
    session.add_message("user", "recent")
    sm.save(session)

    assert sm._get_session_path(key).exists()
    assert (legacy / f"{SessionManager.safe_key(key)}.jsonl").exists()

    assert sm.delete_session(key) is True

    assert not sm._get_session_path(key).exists()
    assert not (legacy / f"{SessionManager.safe_key(key)}.jsonl").exists()


def test_delete_session_prevents_legacy_revival(tmp_path: Path, monkeypatch) -> None:
    """After delete_session, a subsequent get_or_create must not resurrect history."""
    legacy = tmp_path / "legacy_sessions"
    monkeypatch.setattr(
        "nanobot.session.manager.get_legacy_sessions_dir",
        lambda: legacy,
    )
    workspace = tmp_path / "workspace"
    key = "telegram:no-revival"
    _write_legacy_session(legacy, key, ["user", "assistant"])

    sm = SessionManager(workspace)
    assert sm.delete_session(key) is True
    assert not (legacy / f"{SessionManager.safe_key(key)}.jsonl").exists()

    fresh = sm.get_or_create(key)
    assert fresh.messages == []
