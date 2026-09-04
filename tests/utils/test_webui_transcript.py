"""Tests for append-only WebUI transcript replay."""

from __future__ import annotations

from pathlib import Path

import nanobot.webui.transcript as transcript_module
from nanobot.session.history_visibility import HIDDEN_HISTORY_META
from nanobot.webui.transcript import (
    WEBUI_TRANSCRIPT_SCHEMA_VERSION,
    append_fork_marker,
    append_transcript_object,
    build_webui_thread_response,
    fork_transcript_before_user_index,
    read_transcript_lines,
    replay_transcript_to_ui_messages,
    webui_transcript_segments_dir,
    write_session_messages_as_transcript,
)


def test_append_and_read_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t1"
    append_transcript_object(key, {"event": "user", "chat_id": "t1", "text": "hello"})
    lines = read_transcript_lines(key)
    assert len(lines) == 1
    assert lines[0]["text"] == "hello"


def test_append_stamps_created_at_ms(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.webui.transcript.time.time", lambda: 1_700_000_000.0)
    key = "websocket:t-created-at"

    append_transcript_object(key, {"event": "user", "chat_id": "t-created-at", "text": "hello"})

    lines = read_transcript_lines(key)
    assert lines[0]["created_at_ms"] == 1_700_000_000_000


def _force_small_transcript_budget(monkeypatch, *, limit: int = 520, target: int = 260) -> None:
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_FILE_BYTES", limit)
    monkeypatch.setattr("nanobot.webui.transcript._ACTIVE_TRANSCRIPT_ROTATE_BYTES", limit)
    monkeypatch.setattr("nanobot.webui.transcript._TARGET_ACTIVE_TRANSCRIPT_BYTES", target)


def _append_numbered_turn(key: str, chat_id: str, idx: int) -> None:
    append_transcript_object(
        key,
        {"event": "user", "chat_id": chat_id, "text": f"question {idx} " + ("x" * 24)},
    )
    append_transcript_object(
        key,
        {"event": "message", "chat_id": chat_id, "text": f"answer {idx} " + ("y" * 24)},
    )
    append_transcript_object(key, {"event": "turn_end", "chat_id": chat_id})


def _write_segmented_turns(tmp_path, monkeypatch, key: str, chat_id: str, count: int) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    _force_small_transcript_budget(monkeypatch)
    for idx in range(1, count + 1):
        _append_numbered_turn(key, chat_id, idx)


def _message_contents(payload: dict) -> list[str]:
    return [str(message.get("content") or "") for message in payload["messages"]]


def _numbered_turn_texts(start: int, end: int) -> list[str]:
    return [
        text
        for idx in range(start, end + 1)
        for text in (f"question {idx} " + ("x" * 24), f"answer {idx} " + ("y" * 24))
    ]


def test_segmented_transcript_rotation_preserves_full_history(tmp_path, monkeypatch) -> None:
    key = "websocket:segmented"
    _write_segmented_turns(tmp_path, monkeypatch, key, "segmented", 6)

    segment_dir = webui_transcript_segments_dir(key)
    assert segment_dir.is_dir()
    assert (segment_dir / "manifest.json").is_file()

    lines = read_transcript_lines(key)
    contents = [str(line.get("text") or "") for line in lines if line.get("event") in {"user", "message"}]
    assert contents == _numbered_turn_texts(1, 6)


def test_segmented_transcript_paginates_latest_and_older_without_overlap(
    tmp_path,
    monkeypatch,
) -> None:
    key = "websocket:paged"
    _write_segmented_turns(tmp_path, monkeypatch, key, "paged", 6)

    latest = build_webui_thread_response(key, limit=4, direction="latest")
    assert latest is not None
    assert latest["page"]["has_more_before"] is True
    assert latest["page"]["user_message_offset"] == 4
    assert _message_contents(latest) == _numbered_turn_texts(5, 6)

    older = build_webui_thread_response(
        key,
        limit=4,
        before=latest["page"]["before_cursor"],
    )
    assert older is not None
    assert older["page"]["user_message_offset"] == 2
    assert _message_contents(older) == _numbered_turn_texts(3, 4)

    latest_again = build_webui_thread_response(key, limit=4, direction="latest")
    full = build_webui_thread_response(key)
    assert latest_again is not None
    assert full is not None
    assert [message["id"] for message in latest_again["messages"]] == [
        message["id"] for message in latest["messages"]
    ]
    full_ids_by_content = {
        message["content"]: message["id"] for message in full["messages"]
    }
    assert [full_ids_by_content[message["content"]] for message in latest["messages"]] == [
        message["id"] for message in latest["messages"]
    ]


def test_latest_page_reads_active_chunk_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:single-active-read"
    for idx in range(1, 7):
        _append_numbered_turn(key, "single-active-read", idx)

    original = transcript_module._read_chunk_turns
    read_chunk_ids: list[str] = []

    def track_read(session_key: str, chunk_id: str) -> list[list[dict]]:
        read_chunk_ids.append(chunk_id)
        return original(session_key, chunk_id)

    monkeypatch.setattr(transcript_module, "_read_chunk_turns", track_read)

    latest = build_webui_thread_response(key, limit=4, direction="latest")

    assert latest is not None
    assert _message_contents(latest) == _numbered_turn_texts(5, 6)
    assert read_chunk_ids == ["active"]


def test_page_cursor_survives_active_rotation_after_latest_page(
    tmp_path,
    monkeypatch,
) -> None:
    key = "websocket:stable-cursor"
    _write_segmented_turns(tmp_path, monkeypatch, key, "stable-cursor", 7)

    latest = build_webui_thread_response(key, limit=4, direction="latest")
    assert latest is not None
    cursor = latest["page"]["before_cursor"]
    assert cursor
    assert _message_contents(latest) == _numbered_turn_texts(6, 7)

    for idx in range(8, 13):
        _append_numbered_turn(key, "stable-cursor", idx)

    older = build_webui_thread_response(key, limit=4, before=cursor)

    assert older is not None
    assert _message_contents(older) == _numbered_turn_texts(4, 5)


def test_segment_manifest_can_be_rebuilt_when_missing_or_corrupt(tmp_path, monkeypatch) -> None:
    key = "websocket:manifest"
    _write_segmented_turns(tmp_path, monkeypatch, key, "manifest", 4)

    segment_dir = webui_transcript_segments_dir(key)
    segment_names = sorted(path.name for path in segment_dir.glob("*.jsonl"))
    assert segment_names
    original = transcript_module._read_transcript_file
    segment_reads: list[str] = []

    def track_read(path):
        if path.parent == segment_dir and path.suffix == ".jsonl":
            segment_reads.append(path.name)
        return original(path)

    monkeypatch.setattr(transcript_module, "_read_transcript_file", track_read)
    manifest = segment_dir / "manifest.json"
    manifest.write_text("{not json", encoding="utf-8")

    entries = transcript_module._read_segment_manifest_entries(key)

    assert [entry["id"] for entry in entries] == [path.removesuffix(".jsonl") for path in segment_names]
    assert segment_reads == segment_names

    lines = read_transcript_lines(key)

    assert len([line for line in lines if line.get("event") == "user"]) == 4
    assert manifest.read_text(encoding="utf-8").lstrip().startswith("{")


def test_rotation_does_not_reread_existing_segments(tmp_path, monkeypatch) -> None:
    key = "websocket:manifest-append"
    _write_segmented_turns(tmp_path, monkeypatch, key, "manifest-append", 4)
    segment_dir = webui_transcript_segments_dir(key)
    assert list(segment_dir.glob("*.jsonl"))

    original = transcript_module._read_transcript_file
    segment_reads: list[str] = []

    def track_read(path):
        if path.parent == segment_dir and path.suffix == ".jsonl":
            segment_reads.append(path.name)
        return original(path)

    monkeypatch.setattr(transcript_module, "_read_transcript_file", track_read)
    for idx in range(5, 9):
        _append_numbered_turn(key, "manifest-append", idx)

    assert segment_reads == []


def test_delete_webui_transcript_removes_segments(tmp_path, monkeypatch) -> None:
    from nanobot.webui.thread_disk import webui_thread_file_path
    from nanobot.webui.transcript import delete_webui_transcript, webui_transcript_path

    key = "websocket:delete-segments"
    _write_segmented_turns(tmp_path, monkeypatch, key, "delete-segments", 4)
    legacy_path = webui_thread_file_path(key)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text('{"messages":[]}', encoding="utf-8")

    assert webui_transcript_segments_dir(key).is_dir()
    assert delete_webui_transcript(key) is True
    assert not legacy_path.exists()
    assert not webui_transcript_path(key).exists()
    assert not webui_transcript_segments_dir(key).exists()


def test_fork_transcript_reads_across_segments(tmp_path, monkeypatch) -> None:
    source = "websocket:seg-source"
    _write_segmented_turns(tmp_path, monkeypatch, source, "seg-source", 5)

    ok = fork_transcript_before_user_index(source, "websocket:seg-fork", 3)

    assert ok is True
    forked = build_webui_thread_response("websocket:seg-fork")
    assert forked is not None
    assert _message_contents(forked) == _numbered_turn_texts(1, 3)


def test_fork_transcript_before_user_index_copies_only_prefix(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    source = "websocket:source"
    for ev in (
        {"event": "user", "chat_id": "source", "text": "round1"},
        {"event": "message", "chat_id": "source", "text": "answer1"},
        {"event": "turn_end", "chat_id": "source"},
        {"event": "user", "chat_id": "source", "text": "round2 fork me"},
        {"event": "message", "chat_id": "source", "text": "answer2"},
        {"event": "user", "chat_id": "source", "text": "round3 must not appear"},
    ):
        append_transcript_object(source, ev)

    ok = fork_transcript_before_user_index(source, "websocket:fork", 1)

    assert ok is True
    lines = read_transcript_lines("websocket:fork")
    assert [line.get("text") for line in lines] == ["round1", "answer1", None]
    assert all(line.get("chat_id") == "fork" for line in lines)
    assert "round2 fork me" not in "\n".join(str(line.get("text")) for line in lines)
    assert "round3 must not appear" not in "\n".join(str(line.get("text")) for line in lines)


def test_fork_transcript_rejects_out_of_range_user_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    source = "websocket:source"
    append_transcript_object(source, {"event": "user", "chat_id": "source", "text": "round1"})

    assert fork_transcript_before_user_index(source, "websocket:fork", 2) is False
    assert read_transcript_lines("websocket:fork") == []


def test_build_response_reports_fork_boundary_from_marker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:fork"
    for ev in (
        {"event": "user", "chat_id": "fork", "text": "round1"},
        {"event": "message", "chat_id": "fork", "text": "answer1"},
    ):
        append_transcript_object(key, ev)
    append_fork_marker(key)
    append_transcript_object(key, {"event": "user", "chat_id": "fork", "text": "new branch"})

    out = build_webui_thread_response(key)

    assert out is not None
    assert [m["content"] for m in out["messages"]] == ["round1", "answer1", "new branch"]
    assert out["fork_boundary_message_count"] == 2


def test_nested_fork_drops_inherited_fork_marker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    source = "websocket:source"
    for ev in (
        {"event": "user", "chat_id": "source", "text": "round1"},
        {"event": "message", "chat_id": "source", "text": "answer1"},
    ):
        append_transcript_object(source, ev)
    append_fork_marker(source)
    for ev in (
        {"event": "user", "chat_id": "source", "text": "round2"},
        {"event": "message", "chat_id": "source", "text": "answer2"},
    ):
        append_transcript_object(source, ev)

    ok = fork_transcript_before_user_index(source, "websocket:nested", 2)
    append_fork_marker("websocket:nested")

    lines = read_transcript_lines("websocket:nested")
    out = build_webui_thread_response("websocket:nested")

    assert ok is True
    assert [line.get("event") for line in lines] == [
        "user",
        "message",
        "user",
        "message",
        "fork_marker",
    ]
    assert out is not None
    assert [m["content"] for m in out["messages"]] == ["round1", "answer1", "round2", "answer2"]
    assert out["fork_boundary_message_count"] == 4


def test_write_session_messages_as_transcript_builds_canonical_prefix(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    write_session_messages_as_transcript(
        "websocket:fork",
        [
            {"role": "user", "content": "round1"},
            {"role": "assistant", "content": "answer1"},
        ],
    )

    lines = read_transcript_lines("websocket:fork")
    assert lines == [
        {"event": "user", "chat_id": "fork", "text": "round1"},
        {"event": "message", "chat_id": "fork", "text": "answer1"},
    ]
    msgs = replay_transcript_to_ui_messages(lines)
    assert [m["content"] for m in msgs] == ["round1", "answer1"]


def test_direct_transcript_replay_generates_stable_message_ids() -> None:
    lines = [
        {"event": "user", "chat_id": "stable", "text": "question"},
        {"event": "message", "chat_id": "stable", "text": "answer"},
        {"event": "turn_end", "chat_id": "stable"},
    ]

    first = replay_transcript_to_ui_messages(lines)
    second = replay_transcript_to_ui_messages(lines)

    assert [message["id"] for message in second] == [
        message["id"] for message in first
    ]


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


def test_replay_canonical_completed_stream_records() -> None:
    msgs = replay_transcript_to_ui_messages([
        {"event": "user", "chat_id": "canonical", "text": "q"},
        {"event": "reasoning_end", "chat_id": "canonical", "text": "think"},
        {"event": "stream_end", "chat_id": "canonical", "text": "answer"},
        {"event": "turn_end", "chat_id": "canonical", "latency_ms": 42},
    ])

    assert len(msgs) == 2
    assert msgs[1]["content"] == "answer"
    assert msgs[1]["reasoning"] == "think"
    assert msgs[1]["latencyMs"] == 42


def test_replay_preserves_closed_reasoning_slices_before_later_tool_trace() -> None:
    msgs = replay_transcript_to_ui_messages([
        {
            "event": "reasoning_delta",
            "chat_id": "reasoning-boundary",
            "text": "First reasoning.",
            "turn_id": "turn-reasoning-boundary",
            "turn_phase": "reasoning",
            "turn_seq": 1,
        },
        {
            "event": "reasoning_end",
            "chat_id": "reasoning-boundary",
            "turn_id": "turn-reasoning-boundary",
            "turn_phase": "reasoning",
            "turn_seq": 2,
        },
        {
            "event": "reasoning_delta",
            "chat_id": "reasoning-boundary",
            "text": "Second reasoning.",
            "turn_id": "turn-reasoning-boundary",
            "turn_phase": "reasoning",
            "turn_seq": 3,
        },
        {
            "event": "reasoning_end",
            "chat_id": "reasoning-boundary",
            "turn_id": "turn-reasoning-boundary",
            "turn_phase": "reasoning",
            "turn_seq": 4,
        },
        {
            "event": "message",
            "chat_id": "reasoning-boundary",
            "text": "exec()",
            "kind": "tool_hint",
            "turn_id": "turn-reasoning-boundary",
            "turn_phase": "activity",
            "turn_seq": 5,
        },
        {
            "event": "message",
            "chat_id": "reasoning-boundary",
            "text": "Final answer.",
            "turn_id": "turn-reasoning-boundary",
            "turn_phase": "answer",
            "turn_seq": 6,
        },
        {
            "event": "turn_end",
            "chat_id": "reasoning-boundary",
            "turn_id": "turn-reasoning-boundary",
            "turn_phase": "complete",
            "turn_seq": 7,
        },
    ])

    assert [
        message.get("reasoning")
        or (message.get("traces") or [None])[0]
        or message.get("content")
        for message in msgs
    ] == [
        "First reasoning.",
        "Second reasoning.",
        "exec()",
        "Final answer.",
    ]


def test_replay_preserves_closed_reasoning_slices_without_tool_trace() -> None:
    msgs = replay_transcript_to_ui_messages([
        {"event": "reasoning_delta", "text": "First reasoning.", "turn_seq": 1},
        {"event": "reasoning_end", "turn_seq": 2},
        {"event": "reasoning_delta", "text": "Second reasoning.", "turn_seq": 3},
        {"event": "reasoning_end", "turn_seq": 4},
        {"event": "message", "text": "Final answer.", "turn_seq": 5},
        {"event": "turn_end", "turn_seq": 6},
    ])

    assert [
        (message.get("reasoning"), message.get("content"))
        for message in msgs
    ] == [
        ("First reasoning.", ""),
        ("Second reasoning.", "Final answer."),
    ]


def test_replay_keeps_answer_separate_from_reasoning_before_delayed_tool_trace() -> None:
    msgs = replay_transcript_to_ui_messages([
        {"event": "delta", "text": "Visible progress.", "turn_phase": "answer"},
        {"event": "stream_end", "turn_phase": "answer"},
        {"event": "reasoning_delta", "text": "Think again.", "turn_phase": "reasoning"},
        {"event": "reasoning_end", "turn_phase": "reasoning"},
        {
            "event": "message",
            "text": "exec()",
            "kind": "tool_hint",
            "turn_phase": "activity",
        },
        {"event": "message", "text": "Final answer.", "turn_phase": "answer"},
        {"event": "turn_end", "turn_phase": "complete"},
    ])

    assert [
        (
            message.get("content"),
            message.get("reasoning"),
            message.get("kind"),
            message.get("turnPhase"),
        )
        for message in msgs
    ] == [
        ("Visible progress.", None, None, "answer"),
        ("", "Think again.", None, "reasoning"),
        ("exec()", None, "trace", "activity"),
        ("Final answer.", None, None, "answer"),
    ]


def test_replay_turn_end_preserves_usage_semantics(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-usage"
    for event in (
        {"event": "user", "chat_id": "t-usage", "text": "q"},
        {"event": "message", "chat_id": "t-usage", "text": "a"},
        {
            "event": "turn_end",
            "chat_id": "t-usage",
            "latency_ms": 18_200,
            "usage": {
                "prompt_tokens": 12_400,
                "completion_tokens": 823,
                "cached_tokens": 9_672,
                "context_tokens": 8_200,
                "request_count": 3,
            },
            "round_usages": [
                {
                    "prompt_tokens": 4_000,
                    "completion_tokens": 200,
                    "cached_tokens": 2_000,
                    "request_count": 1,
                },
                {
                    "prompt_tokens": 4_200,
                    "completion_tokens": 300,
                    "cached_tokens": 3_672,
                    "request_count": 1,
                },
                {
                    "prompt_tokens": 4_200,
                    "completion_tokens": 323,
                    "cached_tokens": 4_000,
                    "request_count": 1,
                },
            ],
            "context_window_tokens": 128_000,
        },
    ):
        append_transcript_object(key, event)

    messages = replay_transcript_to_ui_messages(read_transcript_lines(key))

    assert messages[-1]["usage"] == {
        "prompt_tokens": 12_400,
        "completion_tokens": 823,
        "cached_tokens": 9_672,
        "context_tokens": 8_200,
        "request_count": 3,
    }
    assert [item["prompt_tokens"] for item in messages[-1]["roundUsages"]] == [
        4_000,
        4_200,
        4_200,
    ]
    assert messages[-1]["contextWindowTokens"] == 128_000
    assert messages[-1]["latencyMs"] == 18_200


def test_replay_uses_persisted_created_at_ms() -> None:
    msgs = replay_transcript_to_ui_messages(
        [
            {
                "event": "user",
                "chat_id": "t-created-at",
                "text": "q",
                "created_at_ms": 1_700_000_000_000,
            },
            {
                "event": "message",
                "chat_id": "t-created-at",
                "kind": "tool_hint",
                "text": "exec()",
                "created_at_ms": 1_700_000_230_000,
            },
        ],
    )

    assert [message["createdAt"] for message in msgs] == [
        1_700_000_000_000,
        1_700_000_230_000,
    ]


def test_thread_response_does_not_mark_completed_message_tool_tail_pending(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:cron-tail"
    turn_id = "cron:job:run"
    for ev in (
        {
            "event": "message",
            "chat_id": "cron-tail",
            "text": 'message({"content":"Cron test"})',
            "kind": "tool_hint",
            "tool_events": [{
                "phase": "start",
                "call_id": "call-message",
                "name": "message",
                "arguments": {"content": "Cron test"},
            }],
            "turn_id": turn_id,
            "turn_phase": "activity",
            "turn_seq": 5,
        },
        {
            "event": "message",
            "chat_id": "cron-tail",
            "text": "Cron test",
            "source": {"kind": "cron", "label": "one-min-test"},
            "turn_id": turn_id,
            "turn_phase": "answer",
            "turn_seq": 6,
        },
        {
            "event": "message",
            "chat_id": "cron-tail",
            "text": "",
            "kind": "progress",
            "tool_events": [{
                "phase": "end",
                "call_id": "call-message",
                "name": "message",
                "arguments": {"content": "Cron test"},
                "result": "ok",
            }],
            "turn_id": turn_id,
            "turn_phase": "activity",
            "turn_seq": 7,
        },
        {
            "event": "turn_end",
            "chat_id": "cron-tail",
            "turn_id": turn_id,
            "turn_phase": "complete",
            "turn_seq": 8,
        },
    ):
        append_transcript_object(key, ev)

    out = build_webui_thread_response(key)

    assert out is not None
    assert out["has_pending_tool_calls"] is False
    assert out["completed_turn_ids"] == [turn_id]
    assert out["messages"][-1]["kind"] == "trace"
    assert out["messages"][-2]["content"] == "Cron test"


def test_thread_response_marks_unfinished_tool_tail_pending(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:active-tail"
    append_transcript_object(
        key,
        {
            "event": "message",
            "chat_id": "active-tail",
            "text": 'exec({"command":"date"})',
            "kind": "tool_hint",
        },
    )

    out = build_webui_thread_response(key)

    assert out is not None
    assert out["has_pending_tool_calls"] is True
    assert out["completed_turn_ids"] == []


def test_recovery_tail_check_reads_only_the_active_transcript(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:recovery-tail"
    active_path = transcript_module.webui_transcript_path(key)
    reads: list[Path] = []

    def read(path: Path) -> list[dict[str, object]]:
        reads.append(path)
        return [{"event": "message", "kind": "progress", "text": "running"}]

    monkeypatch.setattr(transcript_module, "_read_transcript_file", read)

    assert transcript_module.has_unfinished_transcript_tail(key) is True
    assert reads == [active_path]


def test_thread_response_reports_active_registry_without_transcript(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    out = build_webui_thread_response(
        "websocket:active-without-transcript",
        active_turn_started_at=1_700_000_000.0,
        active_turn_id="turn-active",
    )

    assert out is not None
    assert out["messages"] == []
    assert out["completed_turn_ids"] == []
    assert out["has_pending_tool_calls"] is True
    assert out["active_turn_id"] == "turn-active"


def test_thread_response_reports_explicit_completion_without_assistant_row(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:empty-answer"
    turn_id = "turn-empty-answer"
    append_transcript_object(
        key,
        {"event": "user", "chat_id": "empty-answer", "text": "stop", "turn_id": turn_id},
    )
    append_transcript_object(
        key,
        {"event": "turn_end", "chat_id": "empty-answer", "turn_id": turn_id},
    )

    out = build_webui_thread_response(key)

    assert out is not None
    assert out["messages"][-1]["role"] == "user"
    assert out["has_pending_tool_calls"] is False
    assert out["completed_turn_ids"] == [turn_id]


def test_incomplete_turn_with_ambiguous_session_match_stays_pending(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:ambiguous-incomplete"
    turn_id = "turn-ambiguous"
    append_transcript_object(
        key,
        {
            "event": "user",
            "chat_id": "ambiguous-incomplete",
            "text": "repeat",
            "turn_id": turn_id,
        },
    )
    append_transcript_object(
        key,
        {
            "event": "turn_end",
            "chat_id": "ambiguous-incomplete",
            "turn_id": turn_id,
            "transcript_incomplete": True,
        },
    )

    out = build_webui_thread_response(
        key,
        session_messages=[
            {"role": "user", "content": "repeat"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "repeat"},
            {"role": "assistant", "content": "second answer"},
        ],
    )

    assert out is not None
    assert [(message["role"], message["content"]) for message in out["messages"]] == [
        ("user", "repeat"),
    ]
    assert out["completed_turn_ids"] == []
    assert out["has_pending_tool_calls"] is True


def test_later_completion_does_not_hide_older_incomplete_turn(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:older-incomplete"
    for event in (
        {"event": "user", "text": "first", "turn_id": "turn-first"},
        {
            "event": "turn_end",
            "turn_id": "turn-first",
            "transcript_incomplete": True,
        },
        {"event": "user", "text": "second", "turn_id": "turn-second"},
        {"event": "message", "text": "second answer", "turn_id": "turn-second"},
        {"event": "turn_end", "turn_id": "turn-second"},
    ):
        append_transcript_object(
            key,
            {"chat_id": "older-incomplete", **event},
        )

    out = build_webui_thread_response(key)

    assert out is not None
    assert out["completed_turn_ids"] == ["turn-second"]
    assert out["has_pending_tool_calls"] is True


def test_active_registry_does_not_hide_a_newer_queued_turn(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:queued-tail"
    for event in (
        {"event": "user", "text": "first", "turn_id": "turn-old"},
        {"event": "message", "text": "done", "turn_id": "turn-old"},
        {"event": "turn_end", "turn_id": "turn-old"},
        {"event": "user", "text": "queued next", "turn_id": "turn-new"},
    ):
        append_transcript_object(key, {"chat_id": "queued-tail", **event})

    out = build_webui_thread_response(
        key,
        active_turn_started_at=1_700_000_000.0,
        active_turn_id="turn-old",
    )

    assert out is not None
    assert out["has_pending_tool_calls"] is True


def test_replay_preserves_turn_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-turn"
    for ev in (
        {
            "event": "user",
            "chat_id": "t-turn",
            "text": "q",
            "turn_id": "turn-1",
            "turn_phase": "user",
            "turn_seq": 1,
        },
        {
            "event": "reasoning_delta",
            "chat_id": "t-turn",
            "text": "think",
            "turn_id": "turn-1",
            "turn_phase": "reasoning",
            "turn_seq": 2,
        },
        {
            "event": "delta",
            "chat_id": "t-turn",
            "text": "a",
            "turn_id": "turn-1",
            "turn_phase": "answer",
            "turn_seq": 3,
        },
        {
            "event": "turn_end",
            "chat_id": "t-turn",
            "latency_ms": 12,
            "turn_id": "turn-1",
            "turn_phase": "complete",
            "turn_seq": 4,
        },
    ):
        append_transcript_object(key, ev)

    msgs = replay_transcript_to_ui_messages(read_transcript_lines(key))

    assert msgs[0]["turnId"] == "turn-1"
    assert msgs[0]["turnPhase"] == "user"
    assert msgs[0]["turnSeq"] == 1
    assert msgs[1]["turnId"] == "turn-1"
    assert msgs[1]["turnPhase"] == "answer"
    assert msgs[1]["turnSeq"] == 3


def test_replay_reused_turn_id_after_turn_end_starts_new_turn(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-reused-turn"

    def event(
        event: str,
        phase: str,
        seq: int,
        text: str | None = None,
        source: dict[str, str] | None = None,
    ) -> dict[str, object]:
        out = {
            "event": event,
            "chat_id": "t-reused-turn",
            "turn_id": "turn-1",
            "turn_phase": phase,
            "turn_seq": seq,
        }
        if text is not None:
            out["text"] = text
        if source is not None:
            out["source"] = source
        return out

    for record in (
        event("user", "user", 1, "remind me later"),
        event("message", "answer", 2, "Reminder set."),
        event("turn_end", "complete", 3),
        event(
            "message", "answer", 1, "Time to drink water.",
            {"kind": "cron", "label": "drink water"},
        ),
        event("turn_end", "complete", 2),
    ):
        append_transcript_object(key, record)

    msgs = replay_transcript_to_ui_messages(read_transcript_lines(key))

    assert [m["content"] for m in msgs] == [
        "remind me later",
        "Reminder set.",
        "Time to drink water.",
    ]
    assert msgs[1]["turnId"] == "turn-1"
    assert msgs[2]["turnId"].startswith("turn-1:replay:")
    assert msgs[2]["turnId"] != msgs[1]["turnId"]
    assert msgs[2]["source"] == {"kind": "cron", "label": "drink water"}


def test_replay_preserves_local_trigger_source_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-local-trigger-source"
    append_transcript_object(
        key,
        {
            "event": "message",
            "chat_id": "t-local-trigger-source",
            "text": "PR #4502 review started.",
            "source": {"kind": "local_trigger", "label": "PR review"},
        },
    )

    msgs = replay_transcript_to_ui_messages(read_transcript_lines(key))

    assert msgs[0]["source"] == {"kind": "local_trigger", "label": "PR review"}


def test_replay_preserves_automation_source_metadata_on_streamed_reply(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-streamed-cron-source"
    source = {"kind": "cron", "label": "Repo check"}

    for record in (
        {
            "event": "delta",
            "chat_id": "t-streamed-cron-source",
            "text": "Repo ",
            "source": source,
        },
        {
            "event": "delta",
            "chat_id": "t-streamed-cron-source",
            "text": "clean.",
            "source": source,
        },
        {
            "event": "stream_end",
            "chat_id": "t-streamed-cron-source",
            "source": source,
        },
        {"event": "turn_end", "chat_id": "t-streamed-cron-source"},
    ):
        append_transcript_object(key, record)

    msgs = replay_transcript_to_ui_messages(read_transcript_lines(key))

    assert msgs[0]["content"] == "Repo clean."
    assert msgs[0]["source"] == source


def test_replay_preserves_legacy_trigger_source_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-trigger-source"
    append_transcript_object(
        key,
        {
            "event": "message",
            "chat_id": "t-trigger-source",
            "text": "PR #4502 review started.",
            "source": {"kind": "trigger", "label": "PR review"},
        },
    )

    msgs = replay_transcript_to_ui_messages(read_transcript_lines(key))

    assert msgs[0]["source"] == {"kind": "trigger", "label": "PR review"}


def test_build_response_restores_session_users_for_legacy_transcript(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:legacy-users"
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "legacy-users", "text": "assistant one"},
    )
    append_transcript_object(key, {"event": "turn_end", "chat_id": "legacy-users"})
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "legacy-users", "text": "assistant two"},
    )
    append_transcript_object(key, {"event": "turn_end", "chat_id": "legacy-users"})

    out = build_webui_thread_response(
        key,
        session_messages=[
            {"role": "user", "content": "prompt one", "timestamp": "2026-06-02T10:00:00"},
            {"role": "assistant", "content": "assistant one"},
            {"role": "user", "content": "prompt two", "timestamp": "2026-06-02T10:01:00"},
            {"role": "assistant", "content": "assistant two"},
        ],
    )

    assert out is not None
    assert [(m["role"], m["content"]) for m in out["messages"]] == [
        ("user", "prompt one"),
        ("assistant", "assistant one"),
        ("user", "prompt two"),
        ("assistant", "assistant two"),
    ]


def test_complete_transcript_does_not_load_session_messages(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:complete-fast-path"
    for event in (
        {"event": "user", "chat_id": "complete-fast-path", "text": "question"},
        {"event": "message", "chat_id": "complete-fast-path", "text": "answer"},
        {"event": "turn_end", "chat_id": "complete-fast-path"},
    ):
        append_transcript_object(key, event)

    def fail_if_loaded() -> list[dict]:
        raise AssertionError("complete transcripts must not read canonical session history")

    out = build_webui_thread_response(
        key,
        limit=4,
        direction="latest",
        session_messages_loader=fail_if_loaded,
    )

    assert out is not None
    assert [(message["role"], message["content"]) for message in out["messages"]] == [
        ("user", "question"),
        ("assistant", "answer"),
    ]


def test_legacy_recovery_loads_session_and_builds_backfill_turns_once(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:lazy-legacy-recovery"
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "lazy-legacy-recovery", "text": "answer"},
    )
    append_transcript_object(
        key,
        {
            "event": "turn_end",
            "chat_id": "lazy-legacy-recovery",
            "transcript_incomplete": True,
        },
    )

    loader_calls = 0
    backfill_calls = 0
    original = transcript_module._session_backfill_turns

    def load_session_messages() -> list[dict]:
        nonlocal loader_calls
        loader_calls += 1
        return [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]

    def track_backfill(session_key: str, session_messages: list[dict]):
        nonlocal backfill_calls
        backfill_calls += 1
        return original(session_key, session_messages)

    monkeypatch.setattr(transcript_module, "_session_backfill_turns", track_backfill)

    out = build_webui_thread_response(key, session_messages_loader=load_session_messages)

    assert out is not None
    assert loader_calls == 1
    assert backfill_calls == 1
    assert [(message["role"], message["content"]) for message in out["messages"]] == [
        ("user", "question"),
        ("assistant", "answer"),
    ]
    assert out["has_pending_tool_calls"] is False


def test_build_response_restores_session_users_without_duplicating_new_transcript_users(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:mixed-users"
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "mixed-users", "text": "old assistant"},
    )
    append_transcript_object(key, {"event": "turn_end", "chat_id": "mixed-users"})
    append_transcript_object(key, {"event": "user", "chat_id": "mixed-users", "text": "new prompt"})
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "mixed-users", "text": "new assistant"},
    )
    append_transcript_object(key, {"event": "turn_end", "chat_id": "mixed-users"})

    out = build_webui_thread_response(
        key,
        session_messages=[
            {"role": "user", "content": "old prompt"},
            {"role": "assistant", "content": "old assistant"},
            {"role": "user", "content": "new prompt"},
            {"role": "assistant", "content": "new assistant"},
        ],
    )

    assert out is not None
    assert [(m["role"], m["content"]) for m in out["messages"]] == [
        ("user", "old prompt"),
        ("assistant", "old assistant"),
        ("user", "new prompt"),
        ("assistant", "new assistant"),
    ]


def test_replay_augments_assistant_text() -> None:
    msgs = replay_transcript_to_ui_messages(
        [
            {"event": "user", "chat_id": "t-img", "text": "draw"},
            {"event": "delta", "chat_id": "t-img", "text": "![Diagram](diagram.png)"},
            {"event": "stream_end", "chat_id": "t-img"},
        ],
        augment_assistant_text=lambda text: text.replace("diagram.png", "/api/media/sig/payload"),
    )

    assert msgs[1]["content"] == "![Diagram](/api/media/sig/payload)"


def test_replay_uses_stream_end_final_text() -> None:
    msgs = replay_transcript_to_ui_messages(
        [
            {"event": "user", "chat_id": "t-img", "text": "draw"},
            {"event": "stream_end", "chat_id": "t-img", "text": "![Diagram](/api/media/sig/payload)"},
        ],
    )

    assert msgs[1]["content"] == "![Diagram](/api/media/sig/payload)"


def test_build_response_backfills_legacy_sse_only_transcripts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-legacy"
    for ev in (
        {"event": "delta", "chat_id": "t-legacy", "text": "first answer"},
        {"event": "stream_end", "chat_id": "t-legacy"},
        {"event": "turn_end", "chat_id": "t-legacy"},
        {"event": "message", "chat_id": "t-legacy", "text": "second answer"},
        {"event": "turn_end", "chat_id": "t-legacy"},
    ):
        append_transcript_object(key, ev)

    out = build_webui_thread_response(
        key,
        session_messages=[
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
            {"role": "assistant", "content": "second answer"},
        ],
    )

    assert out is not None
    assert [message["role"] for message in out["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["content"] for message in out["messages"]] == [
        "first question",
        "first answer",
        "second question",
        "second answer",
    ]


def test_backfill_does_not_duplicate_existing_user_transcript(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-current"
    for ev in (
        {"event": "user", "chat_id": "t-current", "text": "already stored"},
        {"event": "message", "chat_id": "t-current", "text": "answer"},
        {"event": "turn_end", "chat_id": "t-current"},
    ):
        append_transcript_object(key, ev)

    out = build_webui_thread_response(
        key,
        session_messages=[{"role": "user", "content": "already stored"}],
    )

    assert out is not None
    assert [message["role"] for message in out["messages"]] == ["user", "assistant"]
    assert out["messages"][0]["content"] == "already stored"


def test_backfill_does_not_misalign_when_session_only_has_transcript_tail(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-tail"
    for ev in (
        {"event": "message", "chat_id": "t-tail", "text": "old answer"},
        {"event": "turn_end", "chat_id": "t-tail"},
        {"event": "message", "chat_id": "t-tail", "text": "tail answer"},
        {"event": "turn_end", "chat_id": "t-tail"},
    ):
        append_transcript_object(key, ev)

    out = build_webui_thread_response(
        key,
        session_messages=[
            {"role": "user", "content": "tail question"},
            {"role": "assistant", "content": "tail answer"},
        ],
    )

    assert out is not None
    assert [message["role"] for message in out["messages"]] == [
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["content"] for message in out["messages"]] == [
        "old answer",
        "tail question",
        "tail answer",
    ]


def test_backfill_skips_internal_subagent_results(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-subagent"
    for ev in (
        {"event": "message", "chat_id": "t-subagent", "text": "summary one"},
        {"event": "turn_end", "chat_id": "t-subagent"},
        {"event": "message", "chat_id": "t-subagent", "text": "summary two"},
        {"event": "turn_end", "chat_id": "t-subagent"},
    ):
        append_transcript_object(key, ev)

    legacy_raw = (
        "[Subagent 'legacy' completed successfully]\n\n"
        "Task: t\n\n"
        "Result:\nr\n\n"
        "Summarize this naturally for the user."
    )
    out = build_webui_thread_response(
        key,
        session_messages=[
            {"role": "user", "content": legacy_raw},
            {"role": "assistant", "content": "summary one"},
            {
                "role": "user",
                "content": "marked result",
                HIDDEN_HISTORY_META: {
                    "kind": "subagent_result",
                    "subagent_task_id": "sub-1",
                },
            },
            {"role": "assistant", "content": "summary two"},
        ],
    )

    assert out is not None
    assert [(message["role"], message["content"]) for message in out["messages"]] == [
        ("assistant", "summary one"),
        ("assistant", "summary two"),
    ]


def test_replay_infers_video_media_from_attachment_name() -> None:
    msgs = replay_transcript_to_ui_messages(
        [
            {"event": "user", "chat_id": "t-video", "text": "render"},
            {
                "event": "message",
                "chat_id": "t-video",
                "text": "video ready",
                "media_urls": [{"url": "/api/media/sig/payload", "name": "intro.mp4"}],
            },
        ],
    )

    assert msgs[1]["media"] == [
        {"kind": "video", "url": "/api/media/sig/payload", "name": "intro.mp4"},
    ]


def test_replay_resigns_assistant_media_paths_before_stale_urls() -> None:
    msgs = replay_transcript_to_ui_messages(
        [
            {"event": "user", "chat_id": "t-video-resign", "text": "render"},
            {
                "event": "message",
                "chat_id": "t-video-resign",
                "text": "video ready",
                "media": ["/tmp/intro.mp4"],
                "media_urls": [{"url": "/api/media/old-sig/old-payload", "name": "intro.mp4"}],
            },
        ],
        augment_assistant_media=lambda paths: [
            {"kind": "video", "url": f"/api/media/new-sig/{paths[0].split('/')[-1]}", "name": "intro.mp4"},
        ],
    )

    assert msgs[1]["media"] == [
        {"kind": "video", "url": "/api/media/new-sig/intro.mp4", "name": "intro.mp4"},
    ]


def test_replay_infers_svg_media_from_attachment_name() -> None:
    msgs = replay_transcript_to_ui_messages(
        [
            {"event": "user", "chat_id": "t-svg", "text": "send svg"},
            {
                "event": "message",
                "chat_id": "t-svg",
                "text": "chart ready",
                "media_urls": [{"url": "/api/media/sig/payload", "name": "chart.svg"}],
            },
        ],
    )

    assert msgs[1]["media"] == [
        {"kind": "image", "url": "/api/media/sig/payload", "name": "chart.svg"},
    ]


def test_replay_infers_file_media_from_attachment_name() -> None:
    msgs = replay_transcript_to_ui_messages(
        [
            {"event": "user", "chat_id": "t-file-media", "text": "send html"},
            {
                "event": "message",
                "chat_id": "t-file-media",
                "text": "file ready",
                "media_urls": [{"url": "/api/media/sig/payload", "name": "index.html"}],
            },
        ],
    )

    assert msgs[1]["media"] == [
        {"kind": "file", "url": "/api/media/sig/payload", "name": "index.html"},
    ]


def test_replay_file_edit_event_creates_file_activity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-file"
    for ev in (
        {"event": "user", "chat_id": "t-file", "text": "edit"},
        {
            "event": "message",
            "chat_id": "t-file",
            "text": 'write_file({"path":"foo.txt"})',
            "kind": "tool_hint",
        },
        {
            "event": "file_edit",
            "chat_id": "t-file",
            "edits": [
                {
                    "version": 1,
                    "call_id": "call-write",
                    "tool": "write_file",
                    "path": "foo.txt",
                    "phase": "end",
                    "added": 2,
                    "deleted": 1,
                    "approximate": False,
                    "status": "done",
                },
            ],
        },
    ):
        append_transcript_object(key, ev)

    msgs = replay_transcript_to_ui_messages(read_transcript_lines(key))

    assert len(msgs) == 3
    assert msgs[1]["kind"] == "trace"
    assert msgs[1]["traces"] == ['write_file({"path":"foo.txt"})']
    assert "fileEdits" not in msgs[1]
    assert msgs[2]["kind"] == "trace"
    assert msgs[2]["traces"] == []
    assert msgs[2]["fileEdits"] == [
        {
            "version": 1,
            "call_id": "call-write",
            "tool": "write_file",
            "path": "foo.txt",
            "phase": "end",
            "added": 2,
            "deleted": 1,
            "approximate": False,
            "status": "done",
        },
    ]
    assert msgs[2]["activitySegmentId"]
    assert msgs[2]["activitySegmentId"] != msgs[1]["activitySegmentId"]


def test_replay_file_edit_absorbs_matching_write_tool_event() -> None:
    msgs = replay_transcript_to_ui_messages([
        {
            "event": "message",
            "chat_id": "t-file",
            "text": 'write_file({"path":"foo.txt"})',
            "kind": "tool_hint",
            "tool_events": [
                {
                    "phase": "start",
                    "call_id": "call-write",
                    "name": "write_file",
                    "arguments": {"path": "foo.txt", "content": "hello\n"},
                },
            ],
        },
        {
            "event": "file_edit",
            "chat_id": "t-file",
            "edits": [
                {
                    "version": 1,
                    "call_id": "call-write",
                    "tool": "write_file",
                    "path": "foo.txt",
                    "phase": "start",
                    "added": 1,
                    "deleted": 0,
                    "approximate": True,
                    "status": "editing",
                },
            ],
        },
        {
            "event": "message",
            "chat_id": "t-file",
            "text": "",
            "kind": "progress",
            "tool_events": [
                {
                    "phase": "end",
                    "call_id": "call-write",
                    "name": "write_file",
                    "arguments": {"path": "foo.txt", "content": "hello\n"},
                    "result": "ok",
                },
            ],
        },
    ])

    assert len(msgs) == 1
    assert msgs[0]["kind"] == "trace"
    assert msgs[0]["traces"] == []
    assert "toolEvents" not in msgs[0]
    assert msgs[0]["fileEdits"] == [
        {
            "version": 1,
            "call_id": "call-write",
            "tool": "write_file",
            "path": "foo.txt",
            "phase": "start",
            "added": 1,
            "deleted": 0,
            "approximate": True,
            "status": "editing",
        },
    ]


def test_replay_file_edit_stays_separate_from_mixed_tool_trace() -> None:
    msgs = replay_transcript_to_ui_messages([
        {
            "event": "message",
            "chat_id": "t-file",
            "text": "",
            "kind": "tool_hint",
            "tool_events": [
                {
                    "phase": "start",
                    "call_id": "call-read",
                    "name": "read_file",
                    "arguments": {"path": "quicksort.py"},
                },
                {
                    "phase": "start",
                    "call_id": "call-write",
                    "name": "write_file",
                    "arguments": {"path": "sorting/quicksort.py", "content": "def quicksort():\n"},
                },
            ],
        },
        {
            "event": "file_edit",
            "chat_id": "t-file",
            "edits": [
                {
                    "version": 1,
                    "call_id": "call-write",
                    "tool": "write_file",
                    "path": "sorting/quicksort.py",
                    "phase": "end",
                    "added": 3,
                    "deleted": 0,
                    "approximate": False,
                    "status": "done",
                },
            ],
        },
    ])

    assert len(msgs) == 2
    assert msgs[0]["kind"] == "trace"
    assert msgs[0]["traces"] == ['read_file({"path": "quicksort.py"})']
    assert [event["name"] for event in msgs[0]["toolEvents"]] == ["read_file"]
    assert "fileEdits" not in msgs[0]
    assert msgs[1]["kind"] == "trace"
    assert msgs[1]["traces"] == []
    assert "toolEvents" not in msgs[1]
    assert msgs[1]["fileEdits"] == [
        {
            "version": 1,
            "call_id": "call-write",
            "tool": "write_file",
            "path": "sorting/quicksort.py",
            "phase": "end",
            "added": 3,
            "deleted": 0,
            "approximate": False,
            "status": "done",
        },
    ]


def test_replay_keeps_every_file_from_one_apply_patch_call() -> None:
    msgs = replay_transcript_to_ui_messages([
        {
            "event": "message",
            "chat_id": "t-file",
            "text": "apply_patch()",
            "kind": "tool_hint",
            "tool_events": [
                {
                    "phase": "start",
                    "call_id": "call-patch",
                    "name": "apply_patch",
                    "arguments": {"edits": []},
                },
            ],
        },
        {
            "event": "file_edit",
            "chat_id": "t-file",
            "edits": [
                {
                    "version": 1,
                    "call_id": "call-patch",
                    "tool": "apply_patch",
                    "path": "USER.md",
                    "phase": "end",
                    "added": 0,
                    "deleted": 3,
                    "approximate": False,
                    "status": "done",
                },
                {
                    "version": 1,
                    "call_id": "call-patch",
                    "tool": "apply_patch",
                    "path": "MEMORY.md",
                    "phase": "end",
                    "added": 0,
                    "deleted": 4,
                    "approximate": False,
                    "status": "done",
                },
            ],
        },
    ])

    assert len(msgs) == 1
    assert msgs[0]["traces"] == []
    assert "toolEvents" not in msgs[0]
    assert [edit["path"] for edit in msgs[0]["fileEdits"]] == ["USER.md", "MEMORY.md"]


def test_replay_keeps_interrupted_pre_tool_text_as_answer() -> None:
    msgs = replay_transcript_to_ui_messages([
        {"event": "delta", "chat_id": "t-stream", "text": "I will inspect first."},
        {"event": "stream_end", "chat_id": "t-stream"},
        {
            "event": "message",
            "chat_id": "t-stream",
            "text": 'exec({"cmd":"ls"})',
            "kind": "tool_hint",
        },
        {
            "event": "stream_end",
            "chat_id": "t-stream",
            "text": "Done. Open index.html to play.",
        },
    ])

    assert len(msgs) == 3
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "I will inspect first."
    assert msgs[0]["turnPhase"] == "answer"
    assert "reasoning" not in msgs[0]
    assert "activitySegmentId" not in msgs[0]
    assert "isStreaming" not in msgs[0]
    assert msgs[1]["kind"] == "trace"
    assert msgs[1]["traces"] == ['exec({"cmd":"ls"})']
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["content"] == "Done. Open index.html to play."


def test_replay_merges_length_recovery_segments_into_one_assistant_message() -> None:
    msgs = replay_transcript_to_ui_messages([
        {"event": "delta", "chat_id": "t-stream", "text": "first "},
        {
            "event": "stream_end",
            "chat_id": "t-stream",
            "text": "first ",
            "resuming": True,
            "merge_next": True,
        },
        {"event": "delta", "chat_id": "t-stream", "text": "second"},
        {"event": "stream_end", "chat_id": "t-stream"},
        {"event": "turn_end", "chat_id": "t-stream"},
    ])

    assert len(msgs) == 1
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "first second"


def test_replay_tool_events_dedupes_finish_after_start() -> None:
    msgs = replay_transcript_to_ui_messages([
        {
            "event": "message",
            "chat_id": "t-tool",
            "text": 'exec({"cmd":"ls"})',
            "kind": "tool_hint",
            "tool_events": [
                {
                    "phase": "start",
                    "call_id": "call-exec",
                    "name": "exec",
                    "arguments": {"cmd": "ls"},
                },
            ],
        },
        {
            "event": "message",
            "chat_id": "t-tool",
            "text": "",
            "kind": "progress",
            "tool_events": [
                {
                    "phase": "end",
                    "call_id": "call-exec",
                    "name": "exec",
                    "arguments": {"cmd": "ls"},
                    "result": "ok",
                },
                {
                    "phase": "end",
                    "call_id": "call-read",
                    "name": "read_file",
                    "arguments": {"path": "notes.md"},
                    "result": "done",
                },
            ],
        },
    ])

    assert len(msgs) == 1
    assert msgs[0]["traces"] == [
        'exec({"cmd": "ls"})',
        'read_file({"path": "notes.md"})',
    ]
    assert msgs[0]["toolEvents"][0]["phase"] == "end"
    assert msgs[0]["toolEvents"][0]["call_id"] == "call-exec"


def test_replay_tool_events_keeps_phase_update_when_trace_is_deduped() -> None:
    args = {"name": "github", "args": ["repo", "view"], "json": "true"}
    msgs = replay_transcript_to_ui_messages([
        {
            "event": "message",
            "chat_id": "t-tool",
            "text": "",
            "kind": "tool_hint",
            "tool_events": [
                {
                    "phase": "start",
                    "call_id": "call-cli",
                    "name": "run_cli_app",
                    "arguments": args,
                },
            ],
        },
        {
            "event": "message",
            "chat_id": "t-tool",
            "text": "",
            "kind": "progress",
            "tool_events": [
                {
                    "phase": "error",
                    "call_id": "call-cli",
                    "name": "run_cli_app",
                    "arguments": args,
                    "error": "Error: CLI app 'github' not found",
                },
            ],
        },
    ])

    assert len(msgs) == 1
    assert msgs[0]["traces"] == [
        'run_cli_app({"name": "github", "args": ["repo", "view"], "json": "true"})',
    ]
    assert msgs[0]["toolEvents"][0]["phase"] == "error"
    assert msgs[0]["toolEvents"][0]["error"] == "Error: CLI app 'github' not found"


def test_replay_file_edit_progress_merges_after_interleaved_activity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-file-progress"
    for ev in (
        {"event": "user", "chat_id": "t-file-progress", "text": "edit"},
        {
            "event": "message",
            "chat_id": "t-file-progress",
            "text": 'write_file({"path":"foo.txt"})',
            "kind": "tool_hint",
        },
        {
            "event": "file_edit",
            "chat_id": "t-file-progress",
            "edits": [
                {
                    "version": 1,
                    "call_id": "call-write",
                    "tool": "write_file",
                    "path": "foo.txt",
                    "phase": "start",
                    "added": 12,
                    "deleted": 0,
                    "approximate": True,
                    "status": "editing",
                },
            ],
        },
        {
            "event": "message",
            "chat_id": "t-file-progress",
            "text": "still working",
            "kind": "progress",
        },
        {
            "event": "file_edit",
            "chat_id": "t-file-progress",
            "edits": [
                {
                    "version": 1,
                    "call_id": "call-write",
                    "tool": "write_file",
                    "path": "foo.txt",
                    "phase": "end",
                    "added": 30,
                    "deleted": 0,
                    "approximate": False,
                    "status": "done",
                },
            ],
        },
    ):
        append_transcript_object(key, ev)

    msgs = replay_transcript_to_ui_messages(read_transcript_lines(key))
    file_edit_messages = [msg for msg in msgs if msg.get("fileEdits")]

    assert len(file_edit_messages) == 1
    assert file_edit_messages[0]["fileEdits"] == [
        {
            "version": 1,
            "call_id": "call-write",
            "tool": "write_file",
            "path": "foo.txt",
            "phase": "end",
            "added": 30,
            "deleted": 0,
            "approximate": False,
            "status": "done",
        },
    ]


def test_replay_file_edit_pending_placeholder_upgrades_to_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-file-pending"
    for ev in (
        {"event": "user", "chat_id": "t-file-pending", "text": "write"},
        {
            "event": "file_edit",
            "chat_id": "t-file-pending",
            "edits": [
                {
                    "version": 1,
                    "call_id": "call-write",
                    "tool": "write_file",
                    "path": "",
                    "phase": "start",
                    "added": 1,
                    "deleted": 0,
                    "approximate": True,
                    "status": "editing",
                    "pending": True,
                },
            ],
        },
        {
            "event": "file_edit",
            "chat_id": "t-file-pending",
            "edits": [
                {
                    "version": 1,
                    "call_id": "call-write",
                    "tool": "write_file",
                    "path": "foo.txt",
                    "phase": "start",
                    "added": 12,
                    "deleted": 0,
                    "approximate": True,
                    "status": "editing",
                },
            ],
        },
    ):
        append_transcript_object(key, ev)

    msgs = replay_transcript_to_ui_messages(read_transcript_lines(key))
    file_edit_messages = [msg for msg in msgs if msg.get("fileEdits")]

    assert len(file_edit_messages) == 1
    assert file_edit_messages[0]["fileEdits"] == [
        {
            "version": 1,
            "call_id": "call-write",
            "tool": "write_file",
            "path": "foo.txt",
            "phase": "start",
            "added": 12,
            "deleted": 0,
            "approximate": True,
            "status": "editing",
        },
    ]


def test_replay_keeps_new_file_edit_after_reasoning_in_order(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-file-order"
    for ev in (
        {"event": "user", "chat_id": "t-file-order", "text": "edit"},
        {
            "event": "file_edit",
            "chat_id": "t-file-order",
            "edits": [
                {
                    "version": 1,
                    "call_id": "call-one",
                    "tool": "write_file",
                    "path": "one.txt",
                    "phase": "start",
                    "added": 10,
                    "deleted": 0,
                    "approximate": True,
                    "status": "editing",
                },
            ],
        },
        {"event": "reasoning_delta", "chat_id": "t-file-order", "text": "Check next."},
        {"event": "reasoning_end", "chat_id": "t-file-order"},
        {
            "event": "file_edit",
            "chat_id": "t-file-order",
            "edits": [
                {
                    "version": 1,
                    "call_id": "call-two",
                    "tool": "write_file",
                    "path": "two.txt",
                    "phase": "start",
                    "added": 20,
                    "deleted": 0,
                    "approximate": True,
                    "status": "editing",
                },
            ],
        },
    ):
        append_transcript_object(key, ev)

    msgs = replay_transcript_to_ui_messages(read_transcript_lines(key))

    assert [msg.get("fileEdits", [{}])[0].get("path") if msg.get("fileEdits") else msg.get("reasoning") for msg in msgs[1:]] == [
        "one.txt",
        "Check next.",
        "two.txt",
    ]
    file_edit_segments = [
        msg.get("activitySegmentId")
        for msg in msgs
        if msg.get("fileEdits")
    ]
    assert len(file_edit_segments) == 2
    assert file_edit_segments[0] != file_edit_segments[1]


def test_build_response_schema(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t3"
    append_transcript_object(key, {"event": "user", "chat_id": "t3", "text": "x"})
    out = build_webui_thread_response(key, augment_user_media=None)
    assert out is not None
    assert out["schemaVersion"] == WEBUI_TRANSCRIPT_SCHEMA_VERSION
    assert out["sessionKey"] == key
    assert len(out["messages"]) == 1
