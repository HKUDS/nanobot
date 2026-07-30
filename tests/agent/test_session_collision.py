"""Regression tests for session keys that collide under legacy filenames."""

import json
from datetime import datetime
from pathlib import Path

from nanobot.session.manager import JsonlSessionFiles, Session, SessionManager


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


def test_safe_key_is_lossy() -> None:
    assert SessionManager.safe_key("telegram:a_b") == SessionManager.safe_key("telegram:a:b")


def test_migration_preserves_keys_that_collide_under_legacy_filename(
    tmp_path: Path,
) -> None:
    source = JsonlSessionFiles(tmp_path)
    first_key = "telegram:a_b"
    second_key = "telegram:a:b"
    _write_session_file(source.get_session_path(first_key), first_key, "underscore history")
    _write_session_file(source.get_session_path(second_key), second_key, "colon history")

    manager = SessionManager(tmp_path)

    assert manager.read_session_file(first_key)["messages"][0]["content"] == "underscore history"
    assert manager.read_session_file(second_key)["messages"][0]["content"] == "colon history"


def test_sqlite_save_does_not_touch_legacy_lossy_file(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    source = JsonlSessionFiles(tmp_path)
    key = "telegram:a:b"
    lossy_path = source.get_legacy_lossy_path(key)
    _write_session_file(lossy_path, key, "stale lossy content")
    stale_lossy = lossy_path.read_text(encoding="utf-8")
    session = Session(key=key)
    session.add_message("user", "latest content")

    manager.save(session)

    assert manager.read_session_file(key)["messages"][0]["content"] == "latest content"
    assert lossy_path.read_text(encoding="utf-8") == stale_lossy


def test_migration_ignores_legacy_lossy_file(tmp_path: Path) -> None:
    source = JsonlSessionFiles(tmp_path)
    key = "telegram:legacy:lossy"
    lossy_path = source.get_legacy_lossy_path(key)
    _write_session_file(lossy_path, key, "legacy content")

    manager = SessionManager(tmp_path)

    assert manager.read_session_file(key) is None
    assert lossy_path.exists()
