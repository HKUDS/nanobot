"""Tests for WebUI transcript automatic rolling compaction."""

from __future__ import annotations

import json

from nanobot.webui.transcript import (
    append_transcript_object,
    read_transcript_lines,
    webui_transcript_path,
)


def test_read_transcript_compaction_on_large_file(tmp_path, monkeypatch) -> None:
    # Set data dir to tmp path
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    # Set small transcript limit for easy testing
    limit = 300
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_FILE_BYTES", limit)

    session_key = "websocket:test_session_1"

    # Construct multiple turns
    # Turn 1: 3 messages, end with turn_end
    turn_1 = [
        {"event": "user", "chat_id": "test_session_1", "text": "hello 1"},
        {"event": "delta", "content": "reply 1"},
        {"event": "turn_end"},
    ]
    # Turn 2: 3 messages, end with turn_end
    turn_2 = [
        {
            "event": "user",
            "chat_id": "test_session_1",
            "text": "hello 2 hello 2 hello 2 hello 2 hello 2",
        },
        {
            "event": "delta",
            "content": "reply 2 reply 2 reply 2 reply 2 reply 2 reply 2 reply 2",
        },
        {"event": "turn_end"},
    ]
    # Turn 3: 3 messages, end with turn_end
    turn_3 = [
        {"event": "user", "chat_id": "test_session_1", "text": "hello 3"},
        {"event": "delta", "content": "reply 3"},
        {"event": "turn_end"},
    ]

    path = webui_transcript_path(session_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    all_events = turn_1 + turn_2 + turn_3

    with open(path, "w", encoding="utf-8") as f:
        for ev in all_events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    # Verify file is larger than the limit
    assert path.stat().st_size > limit

    # Read transcript. This should trigger automatic compaction
    lines = read_transcript_lines(session_key)

    # Check that it read successfully and file size is now compacted (<= limit // 2)
    assert len(lines) > 0
    assert len(lines) < len(all_events)
    assert path.stat().st_size <= limit // 2

    # Check that the remaining events are the most recent complete turns.
    assert lines[-1]["event"] == "turn_end"

    # Ensure all remaining events belong to complete turns
    assert lines[0]["event"] == "user"


def test_append_transcript_compaction_on_turn_end(tmp_path, monkeypatch) -> None:
    # Set data dir to tmp path
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    # Set small transcript limit
    limit = 400
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_FILE_BYTES", limit)

    session_key = "websocket:test_session_2"
    path = webui_transcript_path(session_key)

    # 1. Append event by event
    # We will write 4 turns. Each turn is about 150 bytes.
    # Total size for 3 turns is about 450 bytes (< limit 500).
    # Total size for 4 turns is about 600 bytes (> limit 500).

    # Turn 1
    append_transcript_object(session_key, {"event": "user", "chat_id": "test_session_2", "text": "hello 1"})
    append_transcript_object(session_key, {"event": "delta", "content": "reply 1"})
    append_transcript_object(session_key, {"event": "turn_end"})

    # Turn 2
    append_transcript_object(session_key, {"event": "user", "chat_id": "test_session_2", "text": "hello 2"})
    append_transcript_object(session_key, {"event": "delta", "content": "reply 2"})
    append_transcript_object(session_key, {"event": "turn_end"})

    # Turn 3
    append_transcript_object(session_key, {"event": "user", "chat_id": "test_session_2", "text": "hello 3"})
    append_transcript_object(session_key, {"event": "delta", "content": "reply 3"})
    append_transcript_object(session_key, {"event": "turn_end"})

    # File size should be small, no compaction yet
    assert path.stat().st_size < limit

    # Turn 4
    append_transcript_object(session_key, {"event": "user", "chat_id": "test_session_2", "text": "hello 4"})
    append_transcript_object(session_key, {"event": "delta", "content": "reply 4"})

    # Currently, file size may exceed the limit, but because event is "delta" (not "turn_end"),
    # no compaction should trigger yet.
    assert path.stat().st_size > limit

    # Now append "turn_end" for the 4th turn.
    # This should trigger compaction.
    append_transcript_object(session_key, {"event": "turn_end"})

    # After turn_end, the file should be compacted to <= limit // 2 (250 bytes)
    assert path.stat().st_size <= limit // 2

    # Read back and verify
    lines = read_transcript_lines(session_key)
    assert len(lines) > 0
    # The remaining events should end with "turn_end"
    assert lines[-1]["event"] == "turn_end"
    assert lines[0]["event"] == "user"
