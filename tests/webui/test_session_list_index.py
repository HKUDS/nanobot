from __future__ import annotations

from pathlib import Path

import blackcat.webui.session_list_index as session_list_index
from blackcat.session.manager import SessionManager


def test_webui_session_list_reuses_valid_index_without_scanning_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:indexed")
    session.add_message("user", "indexed preview")
    manager.save(session)

    assert list_webui_sessions(manager)[0]["preview"] == "indexed preview"

    def fail_scan(session_manager: SessionManager, path: Path) -> None:
        raise AssertionError(f"unexpected session file scan: {path}")

    monkeypatch.setattr(session_list_index, "_scan_session_row", fail_scan)

    rows = list_webui_sessions(manager)

    assert rows[0]["key"] == "websocket:indexed"
    assert rows[0]["preview"] == "indexed preview"


def test_webui_session_list_rescans_only_changed_file(tmp_path: Path, monkeypatch) -> None:
    manager = SessionManager(tmp_path)
    first = manager.get_or_create("websocket:first")
    first.add_message("user", "first")
    manager.save(first)
    second = manager.get_or_create("websocket:second")
    second.add_message("user", "second before")
    manager.save(second)

    assert {row["preview"] for row in list_webui_sessions(manager)} == {"first", "second before"}

    second.messages.clear()
    second.add_message("user", "second after")
    manager.save(second)

    original_scan = session_list_index._scan_session_row
    scanned: list[str] = []

    def record_scan(session_manager: SessionManager, path: Path) -> dict | None:
        scanned.append(path.name)
        return original_scan(session_manager, path)

    monkeypatch.setattr(session_list_index, "_scan_session_row", record_scan)

    rows = list_webui_sessions(manager)

    assert scanned == [manager._get_session_path("websocket:second").name]
    assert {row["preview"] for row in rows} == {"first", "second after"}


def test_webui_session_list_drops_deleted_index_rows(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:deleted")
    session.add_message("user", "gone")
    manager.save(session)

    assert list_webui_sessions(manager)[0]["key"] == "websocket:deleted"

    assert manager.delete_session("websocket:deleted") is True

    assert list_webui_sessions(manager) == []


def list_webui_sessions(manager: SessionManager) -> list[dict]:
    return session_list_index.list_webui_sessions(manager)
