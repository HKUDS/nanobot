"""Tests for append-only WebUI transcript replay."""

from __future__ import annotations

from nanobot.webui.transcript import (
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


def test_replay_keeps_interrupted_pre_tool_text_in_activity() -> None:
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
    assert msgs[0]["content"] == ""
    assert msgs[0]["reasoning"] == "I will inspect first."
    assert "isStreaming" not in msgs[0]
    assert msgs[1]["kind"] == "trace"
    assert msgs[1]["traces"] == ['exec({"cmd":"ls"})']
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["content"] == "Done. Open index.html to play."


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
    from nanobot.webui.transcript import build_webui_thread_response

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t3"
    append_transcript_object(key, {"event": "user", "chat_id": "t3", "text": "x"})
    out = build_webui_thread_response(key, augment_user_media=None)
    assert out is not None
    assert out["schemaVersion"] == WEBUI_TRANSCRIPT_SCHEMA_VERSION
    assert out["sessionKey"] == key
    assert len(out["messages"]) == 1
