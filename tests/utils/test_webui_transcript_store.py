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
    activity = store.activity_signatures()["websocket:ordered"]
    assert activity["revision"] == 1
    assert activity["updated_at_ns"] > 0
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2

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
    assert first.activity_signatures() == {}
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


def test_schema_one_database_is_migrated_without_losing_events(tmp_path: Path) -> None:
    path = tmp_path / "transcripts.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE transcript_sessions (
                session_key TEXT PRIMARY KEY,
                legacy_imported INTEGER NOT NULL DEFAULT 0,
                next_sequence INTEGER NOT NULL DEFAULT 0,
                active_turn INTEGER NOT NULL DEFAULT 0,
                next_user_index INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE transcript_turns (
                session_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                finalized INTEGER NOT NULL DEFAULT 0,
                user_offset INTEGER NOT NULL DEFAULT 0,
                user_count INTEGER NOT NULL DEFAULT 0,
                event_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (session_key, ordinal),
                FOREIGN KEY (session_key)
                    REFERENCES transcript_sessions(session_key)
                    ON DELETE CASCADE
            );
            CREATE TABLE transcript_events (
                session_key TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                turn_ordinal INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (session_key, sequence),
                FOREIGN KEY (session_key, turn_ordinal)
                    REFERENCES transcript_turns(session_key, ordinal)
                    ON DELETE CASCADE
            );
            INSERT INTO transcript_sessions (
                session_key, legacy_imported, next_sequence, active_turn, next_user_index
            ) VALUES ('websocket:v1', 1, 1, 0, 1);
            INSERT INTO transcript_turns (
                session_key, ordinal, user_offset, user_count, event_count
            ) VALUES ('websocket:v1', 0, 0, 1, 1);
            INSERT INTO transcript_events (
                session_key, sequence, turn_ordinal, payload
            ) VALUES ('websocket:v1', 0, 0, '{"event":"user","text":"kept"}');
            PRAGMA user_version = 1;
            """
        )

    store = SQLiteTranscriptStore(path)

    assert store.read_all("websocket:v1") == [{"event": "user", "text": "kept"}]
    assert store.activity_signatures() == {}
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(transcript_sessions)")
        }
    assert {"activity_revision", "activity_updated_at_ns"} <= columns


def test_recorder_closes_all_sqlite_handles_after_reads(tmp_path: Path) -> None:
    path = tmp_path / "transcripts.sqlite3"
    recorder = WebUITranscriptRecorder(store_path=path, write_batch_window_s=0)
    _append_turn(recorder, "handles", 1)
    assert recorder.build_response(
        "websocket:handles",
        limit=2,
        direction="latest",
    ) is not None
    assert recorder.activity_signatures()["websocket:handles"]["revision"] > 0

    recorder.close()
    moved = path.with_name("moved.sqlite3")
    path.rename(moved)
    moved.unlink()

    assert not moved.exists()
