"""Regression test: read_session_metadata/read_session_file fall back to legacy paths.

Issue #4940: sessions stored in the legacy lossy filename format
(``websocket_*.jsonl``) are listed in the WebUI sidebar but their
``workspace_scope`` metadata is lost after restart because
``read_session_metadata()`` only checked the base64-encoded storage path
and returned ``None`` for legacy-format files.
"""
import json
from datetime import datetime
from pathlib import Path

from nanobot.session.manager import SessionManager


def _write_legacy_lossy_session(manager: SessionManager, key: str, metadata: dict) -> None:
    legacy_path = manager._get_legacy_lossy_path(key)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "_type": "metadata",
        "key": key,
        "created_at": datetime(2025, 1, 1).isoformat(),
        "updated_at": datetime(2025, 1, 1).isoformat(),
        "metadata": metadata,
    }
    legacy_path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_read_session_metadata_falls_back_to_legacy_lossy_path(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "workspace")

    key = "websocket:63136ad5-0000-0000-0000-000000000000"
    metadata = {"workspace_scope": {"project_path": "/custom/project", "access_mode": "tree"}}
    _write_legacy_lossy_session(manager, key, metadata)

    # Base64 storage path must not exist; the legacy file must be found.
    assert not manager._get_session_path(key).exists()

    result = manager.read_session_metadata(key)
    assert result is not None
    assert result["metadata"].get("workspace_scope") == metadata["workspace_scope"]


def test_read_session_file_falls_back_to_legacy_lossy_path(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "workspace")

    key = "websocket:63136ad5-1111-1111-1111-111111111111"
    metadata = {"workspace_scope": {"project_path": "/custom/project", "access_mode": "tree"}}
    _write_legacy_lossy_session(manager, key, metadata)

    assert not manager._get_session_path(key).exists()

    result = manager.read_session_file(key)
    assert result is not None
    assert result["metadata"].get("workspace_scope") == metadata["workspace_scope"]
