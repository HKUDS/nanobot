from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import blackcat.webui.session_list_index as session_list_index
from blackcat.cron.session_turns import CRON_HISTORY_META
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


def test_webui_session_list_skips_cron_internal_user_preview(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:cron-preview")
    session.add_message(
        "user",
        "Scheduled cron job triggered: 30s-test\n\nInternal reminder prompt",
        **{CRON_HISTORY_META: True},
    )
    session.add_message("assistant", "提醒已经到期。")
    manager.save(session)

    assert list_webui_sessions(manager)[0]["preview"] == "提醒已经到期。"


def test_webui_session_list_uses_webui_transcript_activity_for_sort(
    tmp_path: Path,
    monkeypatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir()
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)

    manager = SessionManager(tmp_path)
    old_session = manager.get_or_create("websocket:old-metadata")
    old_session.created_at = datetime(2026, 6, 15, 10, 0, 0)
    old_session.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    old_session.add_message("user", "old metadata")
    old_session.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    manager.save(old_session)

    newer_metadata = manager.get_or_create("websocket:newer-metadata")
    newer_metadata.created_at = datetime(2026, 6, 15, 11, 0, 0)
    newer_metadata.updated_at = datetime(2026, 6, 15, 11, 0, 0)
    newer_metadata.add_message("user", "newer metadata")
    newer_metadata.updated_at = datetime(2026, 6, 15, 11, 0, 0)
    manager.save(newer_metadata)

    transcript = webui_dir / "websocket_old-metadata.jsonl"
    transcript.write_text(
        '{"event":"turn_end","chat_id":"old-metadata"}\n',
        encoding="utf-8",
    )
    activity_ns = int(datetime(2026, 6, 15, 12, 0, 0).timestamp() * 1_000_000_000)
    os.utime(transcript, ns=(activity_ns, activity_ns))

    rows = list_webui_sessions(manager)

    assert [row["key"] for row in rows] == [
        "websocket:old-metadata",
        "websocket:newer-metadata",
    ]
    assert rows[0]["updated_at"].startswith("2026-06-15T12:00:00")


def test_webui_session_list_rescans_when_transcript_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir()
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)

    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:transcript-change")
    session.created_at = datetime(2026, 6, 15, 10, 0, 0)
    session.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    session.add_message("user", "preview")
    session.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    manager.save(session)

    assert list_webui_sessions(manager)[0]["preview"] == "preview"

    transcript = webui_dir / "websocket_transcript-change.jsonl"
    transcript.write_text(
        '{"event":"turn_end","chat_id":"transcript-change"}\n',
        encoding="utf-8",
    )
    activity_ns = int(datetime(2026, 6, 15, 12, 30, 0).timestamp() * 1_000_000_000)
    os.utime(transcript, ns=(activity_ns, activity_ns))

    original_scan = session_list_index._scan_session_row
    scanned: list[str] = []

    def record_scan(session_manager: SessionManager, path: Path) -> dict | None:
        scanned.append(path.name)
        return original_scan(session_manager, path)

    monkeypatch.setattr(session_list_index, "_scan_session_row", record_scan)

    rows = list_webui_sessions(manager)

    assert scanned == [manager._get_session_path("websocket:transcript-change").name]
    assert rows[0]["updated_at"].startswith("2026-06-15T12:30:00")


def list_webui_sessions(manager: SessionManager) -> list[dict]:
    return session_list_index.list_webui_sessions(manager)
