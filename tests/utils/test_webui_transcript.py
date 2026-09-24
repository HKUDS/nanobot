"""Tests for append-only WebUI transcript replay."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock

import pytest

import nanobot.webui.transcript as transcript_module
from nanobot.session.history_visibility import HIDDEN_HISTORY_META
from nanobot.webui.transcript import (
    WEBUI_TRANSCRIPT_SCHEMA_VERSION,
    TranscriptReplayStats,
    append_fork_marker,
    append_transcript_object,
    build_webui_thread_response,
    build_webui_trace_detail_response,
    fork_transcript_before_user_index,
    read_transcript_lines,
    webui_transcript_revision,
    webui_transcript_segments_dir,
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


def _conversation_events(payload: dict) -> list[dict]:
    messages: list[dict] = []
    for event in payload["events"]:
        name = event.get("event")
        if name == "user_message":
            role = "user"
        elif name == "message" and event.get("kind") is None:
            role = "assistant"
        elif name == "stream_end" and isinstance(event.get("text"), str):
            role = "assistant"
        else:
            continue
        messages.append({
            "id": event["projection_id"],
            "role": role,
            "content": event.get("text", ""),
        })
    return messages


def _message_contents(payload: dict) -> list[str]:
    return [str(message.get("content") or "") for message in _conversation_events(payload)]


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
    assert [message["id"] for message in _conversation_events(latest_again)] == [
        message["id"] for message in _conversation_events(latest)
    ]
    full_ids_by_content = {
        message["content"]: message["id"] for message in _conversation_events(full)
    }
    assert [
        full_ids_by_content[message["content"]]
        for message in _conversation_events(latest)
    ] == [
        message["id"] for message in _conversation_events(latest)
    ]


def test_missing_page_query_uses_bounded_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.webui.transcript._DEFAULT_TRANSCRIPT_PAGE_LIMIT", 4)
    key = "websocket:bounded-default"
    for idx in range(1, 5):
        _append_numbered_turn(key, "bounded-default", idx)

    latest = build_webui_thread_response(key)

    assert latest is not None
    assert _message_contents(latest) == _numbered_turn_texts(3, 4)
    assert latest["page"]["has_more_before"] is True
    assert latest["page"]["loaded_event_count"] == 6


def test_large_trace_details_are_deferred_and_resolved(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:deferred-trace"
    trace = f'exec({json.dumps({"command": "x" * 40_000})})'
    for event in (
        {"event": "user", "chat_id": "deferred-trace", "text": "run it"},
        {
            "event": "message",
            "chat_id": "deferred-trace",
            "kind": "progress",
            "text": trace,
        },
        {"event": "message", "chat_id": "deferred-trace", "text": "done"},
        {"event": "turn_end", "chat_id": "deferred-trace"},
    ):
        append_transcript_object(key, event)

    payload = build_webui_thread_response(key, limit=40, direction="latest")

    assert payload is not None
    trace_event = next(event for event in payload["events"] if event.get("kind") == "progress")
    assert trace_event["text"] == "exec(…)"
    assert trace_event["trace_detail"]["bytes"] > 32 * 1024
    assert len(json.dumps(payload)) < len(trace)

    detail = build_webui_trace_detail_response(key, trace_event["trace_detail"]["ref"])

    assert detail is not None
    assert detail["message_id"] == trace_event["projection_id"]
    assert detail["events"][0]["text"] == trace
    assert "trace_detail" not in detail["events"][0]




def test_event_projection_augments_complete_stream_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:project-stream-media"
    for event in (
        {
            "event": "delta",
            "chat_id": "project-stream-media",
            "text": "![plot](output.png)",
        },
        {
            "event": "stream_end",
            "chat_id": "project-stream-media",
            "text": "![plot](output.png)",
        },
    ):
        append_transcript_object(key, event)

    payload = build_webui_thread_response(
        key,
        augment_assistant_text=lambda text: text.replace("output.png", "/api/media/signed"),
    )

    assert payload is not None
    assert [event["text"] for event in payload["events"]] == [
        "![plot](output.png)",
        "![plot](/api/media/signed)",
    ]


def test_event_projection_defers_trace_details_without_legacy_fallback(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:event-trace-fallback"
    for event in (
        {"event": "user", "chat_id": "event-trace-fallback", "text": "run"},
        {
            "event": "message",
            "chat_id": "event-trace-fallback",
            "kind": "progress",
            "text": f'exec({json.dumps({"command": "x" * 40_000})})',
        },
        {"event": "turn_end", "chat_id": "event-trace-fallback"},
    ):
        append_transcript_object(key, event)

    trace = f'exec({json.dumps({"command": "x" * 40_000})})'

    payload = build_webui_thread_response(key)

    assert payload is not None
    assert "messages" not in payload
    assert payload["projection"] == "events"
    trace_event = next(event for event in payload["events"] if event.get("kind") == "progress")
    assert trace_event["text"] == "exec(…)"
    assert trace_event["trace_detail"]["bytes"] > 32 * 1024
    assert trace_event["trace_detail"]["traceCount"] == 1
    assert len(json.dumps(payload)) < len(trace)

    detail = build_webui_trace_detail_response(key, trace_event["trace_detail"]["ref"])

    assert detail is not None
    assert detail["message_id"] == trace_event["projection_id"]
    assert detail["events"][0]["text"] == trace
    assert "trace_detail" not in detail["events"][0]


@pytest.mark.parametrize(
    ("delta_event", "end_event"),
    [("reasoning_delta", "reasoning_end"), ("delta", "stream_end")],
)
def test_active_trace_details_match_compacted_event_page(
    tmp_path, monkeypatch, delta_event: str, end_event: str,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:legacy-active-traces"
    traces = [f'exec({json.dumps({"command": label * 40_000})})' for label in ("A", "B")]
    rows = [
        {"event": "user", "text": "run it"},
        {"event": delta_event, "text": "first "},
        {"event": delta_event, "text": "second"},
        {"event": end_event},
        {"event": "message", "kind": "progress", "text": traces[0]},
        {"event": "message", "text": "between tools"},
        {"event": "message", "kind": "progress", "text": traces[1]},
        {"event": "message", "text": "done"},
        {"event": "turn_end"},
    ]
    path = transcript_module.webui_transcript_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    original_bytes = path.read_bytes()

    payload = build_webui_thread_response(key, limit=40, direction="latest")

    assert payload is not None
    trace_events = [
        event for event in payload["events"]
        if event.get("kind") == "progress"
    ]
    assert len(trace_events) == 2
    for event, trace in zip(trace_events, traces, strict=True):
        detail = build_webui_trace_detail_response(key, event["trace_detail"]["ref"])
        assert detail is not None
        assert detail["message_id"] == event["projection_id"]
        assert detail["events"][0]["text"] == trace
    assert path.read_bytes() == original_bytes


def test_large_structured_trace_error_is_bounded_and_resolved(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:deferred-trace-error"
    full_error = "failure: " + "界" * 40_000
    for event in (
        {"event": "user", "chat_id": "deferred-trace-error", "text": "run it"},
        {
            "event": "message",
            "chat_id": "deferred-trace-error",
            "kind": "progress",
            "text": 'exec({"command":"false"})',
            "tool_events": [
                {
                    "phase": "error",
                    "call_id": "call-exec",
                    "name": "exec",
                    "error": full_error,
                }
            ],
        },
        {"event": "message", "chat_id": "deferred-trace-error", "text": "done"},
        {"event": "turn_end", "chat_id": "deferred-trace-error"},
    ):
        append_transcript_object(key, event)

    payload = build_webui_thread_response(key, limit=40, direction="latest")

    assert payload is not None
    trace_event = next(
        event for event in payload["events"] if event.get("kind") == "progress"
    )
    assert len(json.dumps(trace_event).encode("utf-8")) < 4_096
    event_detail = build_webui_trace_detail_response(
        key,
        trace_event["trace_detail"]["ref"],
    )
    assert event_detail is not None
    assert event_detail["events"][0]["tool_events"][0]["error"] == full_error


def test_many_short_trace_rows_are_bounded_and_resolved(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:deferred-many-traces"
    trace_count = 2_000
    append_transcript_object(
        key,
        {"event": "user", "chat_id": "deferred-many-traces", "text": "run many tools"},
    )
    for index in range(trace_count):
        append_transcript_object(
            key,
            {
                "event": "message",
                "chat_id": "deferred-many-traces",
                "kind": "progress",
                "text": f"tool_{index}(value)",
            },
        )
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "deferred-many-traces", "text": "done"},
    )
    append_transcript_object(key, {"event": "turn_end", "chat_id": "deferred-many-traces"})

    payload = build_webui_thread_response(key, limit=40, direction="latest")

    assert payload is not None
    trace_event = next(event for event in payload["events"] if event.get("kind") == "progress")
    assert trace_event["trace_detail"]["traceCount"] == trace_count
    assert len(json.dumps(trace_event).encode("utf-8")) < 4_096

    detail = build_webui_trace_detail_response(key, trace_event["trace_detail"]["ref"])

    assert detail is not None
    assert len(detail["events"]) == trace_count
    assert detail["events"][0]["text"] == "tool_0(value)"
    assert detail["events"][-1]["text"] == f"tool_{trace_count - 1}(value)"


def test_transcript_revision_tracks_artifacts_and_variants(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:revision"
    append_transcript_object(key, {"event": "user", "chat_id": "revision", "text": "one"})

    first = webui_transcript_revision(key, variant={"limit": 40})
    same = webui_transcript_revision(key, variant={"limit": 40})
    other_variant = webui_transcript_revision(key, variant={"limit": 80})
    append_transcript_object(key, {"event": "message", "chat_id": "revision", "text": "two"})
    changed = webui_transcript_revision(key, variant={"limit": 40})

    assert first is not None
    assert same == first
    assert other_variant != first
    assert changed != first


def test_single_oversized_turn_is_bounded_and_marked(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_PAGE_RECORDS", 5)
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_PAGE_BYTES", 1_200)
    key = "websocket:oversized-turn"
    append_transcript_object(
        key,
        {"event": "user", "chat_id": "oversized-turn", "text": "question"},
    )
    for idx in range(20):
        append_transcript_object(
            key,
            {
                "event": "message",
                "chat_id": "oversized-turn",
                "kind": "progress",
                "text": f"progress {idx} " + ("x" * 160),
            },
        )
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "oversized-turn", "text": "final answer"},
    )
    append_transcript_object(key, {"event": "turn_end", "chat_id": "oversized-turn"})
    stats = TranscriptReplayStats()

    latest = build_webui_thread_response(key, stats=stats)

    assert latest is not None
    assert stats.selected_records <= 5
    assert stats.selected_bytes <= 1_200
    assert stats.capped_by_records is True
    assert stats.capped_by_bytes is True
    assert stats.truncated_oversized_turn is True
    assert latest["page"]["truncated_oversized_turn"] is True
    assert _message_contents(latest) == ["question", "final answer"]


def test_truncated_turn_does_not_advertise_ambiguous_trace_detail(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_PAGE_RECORDS", 6)
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_PAGE_BYTES", 1_000_000)
    key = "websocket:truncated-trace-detail"
    append_transcript_object(
        key,
        {"event": "user", "chat_id": "truncated-trace-detail", "text": "question"},
    )
    for prefix in ("first", "second"):
        for idx in range(4):
            append_transcript_object(
                key,
                {
                    "event": "message",
                    "chat_id": "truncated-trace-detail",
                    "kind": "progress",
                    "text": f"{prefix}_{idx}({('x' * 12_000)})",
                },
            )
        if prefix == "first":
            append_transcript_object(
                key,
                {
                    "event": "message",
                    "chat_id": "truncated-trace-detail",
                    "text": "intermediate",
                },
            )
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "truncated-trace-detail", "text": "done"},
    )
    append_transcript_object(
        key,
        {"event": "turn_end", "chat_id": "truncated-trace-detail"},
    )

    payload = build_webui_thread_response(key, limit=40, direction="latest")

    assert payload is not None
    assert payload["page"]["truncated_oversized_turn"] is True
    trace_event = next(event for event in payload["events"] if event.get("kind") == "progress")
    assert trace_event["text"] == "second_3(…)"
    assert "trace_detail" not in trace_event
    assert len(json.dumps(trace_event).encode("utf-8")) < 4_096


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


def test_manifest_repair_is_single_flight(tmp_path, monkeypatch) -> None:
    key = "websocket:manifest-single-flight"
    _write_segmented_turns(tmp_path, monkeypatch, key, "manifest-single-flight", 4)
    manifest = webui_transcript_segments_dir(key) / "manifest.json"
    manifest.write_text("{not json", encoding="utf-8")
    original = transcript_module._rebuild_segment_manifest
    rebuild_started = Event()
    release_rebuild = Event()
    calls = 0
    calls_lock = Lock()

    def slow_rebuild(*args, **kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        rebuild_started.set()
        assert release_rebuild.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(transcript_module, "_rebuild_segment_manifest", slow_rebuild)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(transcript_module._read_segment_manifest_entries, key)
        assert rebuild_started.wait(2)
        second = executor.submit(transcript_module._read_segment_manifest_entries, key)
        release_rebuild.set()
        assert first.result(timeout=2) == second.result(timeout=2)

    assert calls == 1


def test_page_read_compacts_legacy_immutable_segment(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:compact-segment"
    segment_id = "000001"
    rows = [
        {"event": "user", "chat_id": "compact-segment", "text": "q"},
        {
            "event": "delta",
            "chat_id": "compact-segment",
            "stream_id": "answer-1",
            "text": "answer ",
        },
        {
            "event": "delta",
            "chat_id": "compact-segment",
            "stream_id": "answer-1",
            "text": "done",
        },
        {
            "event": "stream_end",
            "chat_id": "compact-segment",
            "stream_id": "answer-1",
        },
        {"event": "turn_end", "chat_id": "compact-segment"},
    ]
    segment_path = transcript_module._segment_file_path(key, segment_id)
    transcript_module._write_records_to_path(segment_path, rows)
    transcript_module._write_segment_manifest(
        key,
        [transcript_module._segment_manifest_entry(key, segment_id)],
    )
    stats = TranscriptReplayStats()

    latest = build_webui_thread_response(key, stats=stats)
    persisted = transcript_module._read_transcript_file(segment_path)

    assert latest is not None
    assert _message_contents(latest) == ["q", "answer done"]
    assert [record["event"] for record in persisted] == [
        "user",
        "stream_end",
        "turn_end",
    ]
    assert stats.compacted_delta_records == 2
    assert transcript_module._load_segment_manifest_entries(key) is not None


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
    assert [m["content"] for m in _conversation_events(out)] == [
        "round1", "answer1", "new branch",
    ]
    assert out["fork_boundary_event_index"] == 2


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
    assert [m["content"] for m in _conversation_events(out)] == [
        "round1", "answer1", "round2", "answer2",
    ]
    assert out["fork_boundary_event_index"] == 4








def test_completed_turn_persists_canonical_stream_end_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:compact-deltas"
    for event in (
        {"event": "user", "chat_id": "compact-deltas", "text": "q"},
        {"event": "reasoning_delta", "chat_id": "compact-deltas", "text": "think "},
        {"event": "reasoning_delta", "chat_id": "compact-deltas", "text": "more"},
        {"event": "reasoning_end", "chat_id": "compact-deltas"},
        {"event": "delta", "chat_id": "compact-deltas", "text": "answer "},
        {"event": "delta", "chat_id": "compact-deltas", "text": "done"},
        {"event": "stream_end", "chat_id": "compact-deltas"},
        {"event": "turn_end", "chat_id": "compact-deltas"},
    ):
        append_transcript_object(key, event)

    lines = read_transcript_lines(key)

    assert [record["event"] for record in lines] == [
        "user",
        "reasoning_end",
        "stream_end",
        "turn_end",
    ]
    assert lines[1]["text"] == "think more"
    assert lines[2]["text"] == "answer done"














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
    assert out["events"][-2]["kind"] == "progress"
    assert _conversation_events(out)[-1]["content"] == "Cron test"


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
    assert out["events"] == []
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
    assert _conversation_events(out)[-1]["role"] == "user"
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
    assert [
        (message["role"], message["content"])
        for message in _conversation_events(out)
    ] == [
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
    assert [(m["role"], m["content"]) for m in _conversation_events(out)] == [
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
    assert [
        (message["role"], message["content"])
        for message in _conversation_events(out)
    ] == [
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
    assert [
        (message["role"], message["content"])
        for message in _conversation_events(out)
    ] == [
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
    assert [(m["role"], m["content"]) for m in _conversation_events(out)] == [
        ("user", "old prompt"),
        ("assistant", "old assistant"),
        ("user", "new prompt"),
        ("assistant", "new assistant"),
    ]






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
    assert [message["role"] for message in _conversation_events(out)] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["content"] for message in _conversation_events(out)] == [
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
    assert [message["role"] for message in _conversation_events(out)] == [
        "user", "assistant",
    ]
    assert _conversation_events(out)[0]["content"] == "already stored"


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
    assert [message["role"] for message in _conversation_events(out)] == [
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["content"] for message in _conversation_events(out)] == [
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
    assert [
        (message["role"], message["content"])
        for message in _conversation_events(out)
    ] == [
        ("assistant", "summary one"),
        ("assistant", "summary two"),
    ]




































def test_build_response_schema(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t3"
    append_transcript_object(key, {"event": "user", "chat_id": "t3", "text": "x"})
    out = build_webui_thread_response(key, augment_user_media=None)
    assert out is not None
    assert out["schemaVersion"] == WEBUI_TRANSCRIPT_SCHEMA_VERSION
    assert out["sessionKey"] == key
    assert len(_conversation_events(out)) == 1
