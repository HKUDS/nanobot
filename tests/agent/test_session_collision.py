"""Regression tests for collision-resistant session filenames."""

import json
from datetime import datetime
from pathlib import Path

from nanobot.session.manager import Session, SessionManager
from nanobot.utils.helpers import safe_filename


def _manager(tmp_path: Path, monkeypatch) -> SessionManager:
    monkeypatch.setattr(
        "nanobot.session.manager.get_legacy_sessions_dir",
        lambda: tmp_path / "legacy_sessions",
    )
    return SessionManager(tmp_path / "workspace")


def _write_session_file(path: Path, key: str, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "_type": "metadata",
        "key": key,
        "created_at": datetime(2025, 1, 1).isoformat(),
        "updated_at": datetime(2025, 1, 1).isoformat(),
        "metadata": {"source": "test"},
        "last_consolidated": 0,
    }
    message = {"role": "user", "content": content}
    path.write_text(
        json.dumps(metadata) + "\n" + json.dumps(message) + "\n",
        encoding="utf-8",
    )


def test_distinct_keys_have_distinct_filenames(tmp_path: Path, monkeypatch) -> None:
    sm = _manager(tmp_path, monkeypatch)

    first = sm._get_session_path("telegram:a_b")
    second = sm._get_session_path("telegram:a:b")

    assert first.name != second.name
    assert sm.safe_key("telegram:a_b") == sm.safe_key("telegram:a:b")
    assert sm._storage_key("telegram:a_b") != sm._storage_key("telegram:a:b")


def test_save_uses_new_path_not_lossy(tmp_path: Path, monkeypatch) -> None:
    sm = _manager(tmp_path, monkeypatch)
    key = "telegram:a:b"
    session = Session(key=key)
    session.add_message("user", "first")
    sm.save(session)

    new_path = sm._get_session_path(key)
    lossy_path = sm._get_legacy_lossy_path(key)
    _write_session_file(lossy_path, key, "stale lossy content")
    stale_lossy = lossy_path.read_text(encoding="utf-8")

    session.add_message("assistant", "latest content")
    sm.save(session)

    assert new_path.exists()
    assert lossy_path.exists()
    assert "latest content" in new_path.read_text(encoding="utf-8")
    assert lossy_path.read_text(encoding="utf-8") == stale_lossy


def test_load_falls_back_to_lossy_path(tmp_path: Path, monkeypatch) -> None:
    sm = _manager(tmp_path, monkeypatch)
    key = "telegram:legacy:lossy"
    lossy_path = sm._get_legacy_lossy_path(key)
    _write_session_file(lossy_path, key, "loaded from lossy")

    session = sm._load(key)

    assert session is not None
    assert session.metadata == {"source": "test"}
    assert session.messages[0]["content"] == "loaded from lossy"


def test_load_migrates_lossy_to_new_path(tmp_path: Path, monkeypatch) -> None:
    sm = _manager(tmp_path, monkeypatch)
    key = "telegram:migrate:lossy"
    new_path = sm._get_session_path(key)
    lossy_path = sm._get_legacy_lossy_path(key)
    _write_session_file(lossy_path, key, "migrate me")

    session = sm._load(key)

    assert session is not None
    assert session.messages[0]["content"] == "migrate me"
    assert new_path.exists()
    assert not lossy_path.exists()


def test_safe_key_is_lossy() -> None:
    assert SessionManager.safe_key("telegram:a_b") == SessionManager.safe_key("telegram:a:b")


def test_storage_key_is_collision_resistant() -> None:
    encoded = {
        SessionManager._storage_key("a:b"),
        SessionManager._storage_key("a_b"),
        SessionManager._storage_key("a:b:c"),
    }

    assert len(encoded) == 3
    assert SessionManager._storage_key("telegram:a_b") != SessionManager._storage_key("telegram:a:b")


def test_lossy_path_helper_returns_expected_path(tmp_path: Path, monkeypatch) -> None:
    sm = _manager(tmp_path, monkeypatch)
    key = "telegram:a:b"
    expected = sm.sessions_dir / f"{safe_filename(key.replace(':', '_'))}.jsonl"

    assert sm._get_legacy_lossy_path(key) == expected


def test_storage_paths_are_distinct_when_keys_collide_under_safe_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sm = _manager(tmp_path, monkeypatch)
    first = Session(key="telegram:a_b")
    first.add_message("user", "underscore history")
    second = Session(key="telegram:a:b")
    second.add_message("user", "colon history")

    sm.save(first)
    sm.save(second)

    assert sm.safe_key(first.key) == sm.safe_key(second.key)
    assert sm._get_session_path(first.key).exists()
    assert sm._get_session_path(second.key).exists()
    assert sm._get_session_path(first.key) != sm._get_session_path(second.key)

    sm.invalidate(first.key)
    sm.invalidate(second.key)
    loaded_first = sm._load(first.key)
    loaded_second = sm._load(second.key)

    assert loaded_first is not None
    assert loaded_second is not None
    assert loaded_first.messages[0]["content"] == "underscore history"
    assert loaded_second.messages[0]["content"] == "colon history"
