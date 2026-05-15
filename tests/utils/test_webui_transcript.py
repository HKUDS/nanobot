"""Tests for append-only WebUI transcript replay."""

from __future__ import annotations

from nanobot.utils.webui_transcript import (
    WEBUI_TRANSCRIPT_SCHEMA_VERSION,
    append_transcript_object,
    read_transcript_lines,
    replay_transcript_to_ui_messages,
)


def test_append_and_read_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t1"
    append_transcript_object(key, {"event": "user", "chat_id": "t1", "text": "hello"})
    lines = read_transcript_lines(key)
    assert len(lines) == 1
    assert lines[0]["text"] == "hello"


def test_replay_delta_and_turn_end(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t2"
    for ev in (
        {"event": "user", "chat_id": "t2", "text": "q"},
        {"event": "reasoning_delta", "chat_id": "t2", "text": "think"},
        {"event": "reasoning_end", "chat_id": "t2"},
        {"event": "delta", "chat_id": "t2", "text": "a"},
        {"event": "stream_end", "chat_id": "t2"},
        {"event": "turn_end", "chat_id": "t2", "latency_ms": 42},
    ):
        append_transcript_object(key, ev)
    lines = read_transcript_lines(key)
    msgs = replay_transcript_to_ui_messages(lines)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "q"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "a"
    assert msgs[1]["reasoning"] == "think"
    assert msgs[1]["latencyMs"] == 42


def test_build_response_schema(monkeypatch, tmp_path) -> None:
    from nanobot.utils.webui_transcript import build_webui_thread_response

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t3"
    append_transcript_object(key, {"event": "user", "chat_id": "t3", "text": "x"})
    out = build_webui_thread_response(key, augment_user_media=None)
    assert out is not None
    assert out["schemaVersion"] == WEBUI_TRANSCRIPT_SCHEMA_VERSION
    assert out["sessionKey"] == key
    assert len(out["messages"]) == 1
