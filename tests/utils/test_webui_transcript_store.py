from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.session.manager import SessionManager
from nanobot.webui.transcript import (
    WebUITranscriptRecorder,
    append_transcript_object,
    webui_transcript_path,
)
from nanobot.webui.transcript_store import SQLiteTranscriptStore, TranscriptWriteQueue


def _append_turn(
    recorder: WebUITranscriptRecorder,
    chat_id: str,
    index: int,
    *,
    finish: bool = True,
) -> None:
    recorder.append(chat_id, {"event": "user", "chat_id": chat_id, "text": f"q{index}"})
    recorder.append(chat_id, {"event": "message", "chat_id": chat_id, "text": f"a{index}"})
    if finish:
        recorder.append(chat_id, {"event": "turn_end", "chat_id": chat_id})


def test_writer_batches_ordered_events_and_persists_wal_store(tmp_path: Path) -> None:
    store = SQLiteTranscriptStore(tmp_path / "transcripts.sqlite3")
    original_append_batch = store.append_batch
    store.append_batch = MagicMock(wraps=original_append_batch)
    writer = TranscriptWriteQueue(store, log=MagicMock(), batch_window_s=0.1)

    for index in range(12):
        writer.append(
            "websocket:ordered",
            {"event": "delta", "chat_id": "ordered", "text": str(index)},
        )
    writer.flush()

    assert [row["text"] for row in store.read_all("websocket:ordered")] == [
        str(index) for index in range(12)
    ]
    assert store.append_batch.call_count == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1

    writer.close()


def test_turn_cursor_stays_stable_when_new_turns_arrive(tmp_path: Path) -> None:
    recorder = WebUITranscriptRecorder(
        store_path=tmp_path / "transcripts.sqlite3",
        write_batch_window_s=0,
    )
    for index in range(1, 4):
        _append_turn(recorder, "paged", index)
    recorder.flush()
    recorder._store.read_all = MagicMock(side_effect=AssertionError("full scan is forbidden"))

    latest = recorder.build_response(
        "websocket:paged",
        limit=2,
        direction="latest",
    )
    assert latest is not None
    assert [message["content"] for message in latest["messages"]] == ["q3", "a3"]
    cursor = latest["page"]["before_cursor"]
    assert latest["page"]["user_message_offset"] == 2

    _append_turn(recorder, "paged", 4)
    older = recorder.build_response("websocket:paged", limit=2, before=cursor)

    assert older is not None
    assert [message["content"] for message in older["messages"]] == ["q2", "a2"]
    assert older["page"]["user_message_offset"] == 1
    recorder.close()


def test_legacy_jsonl_is_imported_once_and_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:legacy"
    sessions = SessionManager(tmp_path / "sessions")
    session = sessions.get_or_create(key)
    session.add_message("user", "legacy question")
    session.add_message("assistant", "legacy answer")
    sessions.save(session)
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "legacy", "text": "legacy answer"},
    )
    legacy_path = webui_transcript_path(key)

    first = WebUITranscriptRecorder(
        session_manager=sessions,
        store_path=tmp_path / "transcripts.sqlite3",
    )
    assert [row.get("text") for row in first.read_lines(key)] == [
        "legacy question",
        "legacy answer",
    ]
    first.close()
    assert legacy_path.is_file()

    append_transcript_object(
        key,
        {"event": "message", "chat_id": "legacy", "text": "late legacy row"},
    )
    restarted = WebUITranscriptRecorder(
        session_manager=sessions,
        store_path=tmp_path / "transcripts.sqlite3",
    )
    assert [row.get("text") for row in restarted.read_lines(key)] == [
        "legacy question",
        "legacy answer",
    ]
    restarted.close()


def test_restart_recovers_an_incomplete_active_turn(tmp_path: Path) -> None:
    store_path = tmp_path / "transcripts.sqlite3"
    first = WebUITranscriptRecorder(store_path=store_path, write_batch_window_s=0)
    first.append("restart", {"event": "user", "chat_id": "restart", "text": "question"})
    first.append(
        "restart",
        {"event": "delta", "chat_id": "restart", "stream_id": "s1", "text": "partial"},
    )
    first.close()

    restarted = WebUITranscriptRecorder(store_path=store_path, write_batch_window_s=0)
    incomplete = restarted.build_response("websocket:restart")
    assert incomplete is not None
    assert [message["content"] for message in incomplete["messages"]] == [
        "question",
        "partial",
    ]
    assert incomplete["has_pending_tool_calls"] is True
    restarted.append(
        "restart",
        {"event": "stream_end", "chat_id": "restart", "stream_id": "s1"},
    )
    restarted.append("restart", {"event": "turn_end", "chat_id": "restart"})
    restarted.close()

    final = WebUITranscriptRecorder(store_path=store_path)
    completed = final.build_response("websocket:restart")
    assert completed is not None
    assert completed["has_pending_tool_calls"] is False
    final.close()


def test_fork_and_delete_are_serialized_with_pending_writes(tmp_path: Path) -> None:
    recorder = WebUITranscriptRecorder(
        store_path=tmp_path / "transcripts.sqlite3",
        write_batch_window_s=0.1,
    )
    _append_turn(recorder, "source", 1)
    _append_turn(recorder, "source", 2)

    assert recorder.fork_before_user_index(
        "websocket:source",
        "websocket:target",
        1,
    )
    recorder.append_fork_marker("websocket:target")
    forked = recorder.build_response("websocket:target")
    assert forked is not None
    assert [message["content"] for message in forked["messages"]] == ["q1", "a1"]
    assert forked["fork_boundary_message_count"] == 2

    assert recorder.delete("websocket:target") is True
    assert recorder.build_response("websocket:target") is None
    recorder.close()


def test_writer_surfaces_batch_failure_to_flush_and_close() -> None:
    store = MagicMock(spec=SQLiteTranscriptStore)
    store.append_batch.side_effect = OSError("disk full")
    writer = TranscriptWriteQueue(store, log=MagicMock(), batch_window_s=0)
    writer.append("websocket:broken", {"event": "user", "text": "lost"})

    with pytest.raises(RuntimeError, match="writer has failed") as flush_error:
        writer.flush()
    assert isinstance(flush_error.value.__cause__, OSError)

    with pytest.raises(RuntimeError, match="writer has failed"):
        writer.close()


def test_newer_database_schema_fails_without_overwriting_it(tmp_path: Path) -> None:
    path = tmp_path / "transcripts.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")

    store = SQLiteTranscriptStore(path)
    with pytest.raises(RuntimeError, match="unsupported WebUI transcript schema 99"):
        store.read_all("websocket:newer")

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99
