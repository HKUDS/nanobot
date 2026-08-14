"""Tests for retired legacy session storage paths."""

import json
from datetime import datetime
from pathlib import Path

from nanobot.session.manager import SessionManager


def test_list_sessions_ignores_legacy_stem(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "workspace")

    # A legacy lossy-path filename must not be treated as current session storage,
    # even when the file contains otherwise recoverable records.
    legacy_stem = "telegram_12345"
    corrupt_path = manager.sessions_dir / f"{legacy_stem}.jsonl"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = json.dumps({
        "_type": "metadata",
        "key": "telegram:12345",
        "created_at": datetime(2025, 1, 1).isoformat(),
        "updated_at": datetime(2025, 1, 1).isoformat(),
    })
    corrupt_path.write_text(
        metadata + "\n{INVALID JSON LINE\n"
        + json.dumps({"role": "user", "content": "recoverable message"}) + "\n",
        encoding="utf-8",
    )

    sessions = manager.list_sessions()

    assert sessions == []
    assert corrupt_path.exists()


def test_read_session_methods_ignore_legacy_lossy_stem(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "nanobot.session.manager.get_legacy_sessions_dir",
        lambda: tmp_path / "legacy_sessions",
    )
    manager = SessionManager(tmp_path / "workspace")
    session_id = "123e4567-e89b-12d3-a456-426614174000"
    key = f"websocket:{session_id}"
    legacy_path = manager._get_legacy_lossy_path(key)
    assert legacy_path.name == f"websocket_{session_id}.jsonl"

    metadata = {
        "_type": "metadata",
        "key": key,
        "created_at": datetime(2025, 1, 1).isoformat(),
        "updated_at": datetime(2025, 1, 1).isoformat(),
        "metadata": {
            "workspace_scope": "project",
            "project_path": "/tmp/example-project",
        },
    }
    legacy_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")

    metadata_result = manager.read_session_metadata(key)
    file_result = manager.read_session_file(key)

    assert metadata_result is None
    assert file_result is None
