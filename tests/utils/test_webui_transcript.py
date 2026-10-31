from __future__ import annotations

import json

import pytest

import nanobot.webui.transcript as transcript_module
from nanobot.session.history_visibility import HIDDEN_HISTORY_META
from nanobot.webui.history import fact_from_record
from nanobot.webui.transcript import WEBUI_TRANSCRIPT_SCHEMA_VERSION, TranscriptReplayStats


def test_append_and_read_roundtrip(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t1"
    history.append(key, {"event": "user", "chat_id": "t1", "text": "hello"})
    lines = history.read(key)
    assert len(lines) == 1
    assert lines[0]["text"] == "hello"


@pytest.mark.parametrize("event", ["stream_end", "reasoning_end"])
def test_history_preserves_phase_qualified_stream_identity(history, event) -> None:
    key = "websocket:stream-identity"
    history.append(key, {"event": "user", "chat_id": "stream-identity", "text": "question"})
    history.append(key, {
        "event": event, "chat_id": "stream-identity", "text": "completed segment",
        "stream_id": "stream-one", "turn_id": "turn-one", "turn_seq": 2,
    })
    response = history.build(key)
    assert response is not None
    segment = next(record for record in response["events"] if record["event"] == event)
    assert segment["stream_id"] == "stream-one"
    assert segment["turn_seq"] == 2


@pytest.mark.parametrize("reason", [None, "idle", "context_pressure", "manual", "provider_native"])
def test_compaction_reason_survives_sqlite_reload_and_older_page(history, tmp_path, reason) -> None:
    from nanobot.session.manager import SessionManager

    key = "websocket:compaction-reason"
    history.append(key, {"event": "user", "chat_id": "compaction-reason", "text": "first"})
    compaction = {
        "event": "context_compaction", "chat_id": "compaction-reason",
        "compaction_id": "compact-one", "phase": "succeeded",
        "turn_id": "turn-one", "turn_seq": 1,
        **({"reason": reason} if reason is not None else {}),
    }
    history.append(key, compaction)
    history.append(key, {"event": "turn_end", "chat_id": "compaction-reason"})
    _append_numbered_turn(history, key, "compaction-reason", 2)
    reopened = SessionManager(tmp_path)

    def build(**kwargs):
        return reopened.project_history(key, lambda snapshot: transcript_module.build_webui_thread_response(
            key, history=snapshot, **kwargs,
        ))

    latest = build(limit=2, direction="latest")
    assert latest is not None
    older = build(limit=2, before=latest["page"]["before_cursor"])
    assert older is not None
    [replayed] = [event for event in older["events"] if event["event"] == "context_compaction"]
    assert {field: replayed[field] for field in compaction} == compaction
    if reason is None:
        assert "reason" not in replayed


def test_append_stamps_created_at_ms(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.webui.transcript.time.time", lambda: 1_700_000_000.0)
    key = "websocket:t-created-at"

    history.append(key, {"event": "user", "chat_id": "t-created-at", "text": "hello"})

    lines = history.read(key)
    assert lines[0]["created_at_ms"] == 1_700_000_000_000


def _append_numbered_turn(history, key: str, chat_id: str, idx: int) -> None:
    history.append(
        key,
        {"event": "user", "chat_id": chat_id, "text": f"question {idx} " + ("x" * 24)},
    )
    history.append(
        key,
        {"event": "message", "chat_id": chat_id, "text": f"answer {idx} " + ("y" * 24)},
    )
    history.append(key, {"event": "turn_end", "chat_id": chat_id})


def _write_history_turns(history, tmp_path, monkeypatch, key: str, chat_id: str, count: int) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    for idx in range(1, count + 1):
        _append_numbered_turn(history, key, chat_id, idx)


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


def test_sqlite_history_paginates_latest_and_older_without_overlap(history,
    tmp_path,
    monkeypatch,
) -> None:
    key = "websocket:paged"
    _write_history_turns(history, tmp_path, monkeypatch, key, "paged", 6)

    latest = history.build(key, limit=4, direction="latest")
    assert latest is not None
    assert latest["page"]["has_more_before"] is True
    assert latest["page"]["user_message_offset"] == 4
    assert _message_contents(latest) == _numbered_turn_texts(5, 6)

    older = history.build(
        key,
        limit=4,
        before=latest["page"]["before_cursor"],
    )
    assert older is not None
    assert older["page"]["user_message_offset"] == 2
    assert _message_contents(older) == _numbered_turn_texts(3, 4)

    latest_again = history.build(key, limit=4, direction="latest")
    full = history.build(key)
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


def test_missing_page_query_uses_bounded_default(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.webui.transcript._DEFAULT_TRANSCRIPT_PAGE_LIMIT", 4)
    key = "websocket:bounded-default"
    for idx in range(1, 5):
        _append_numbered_turn(history, key, "bounded-default", idx)

    latest = history.build(key)

    assert latest is not None
    assert _message_contents(latest) == _numbered_turn_texts(3, 4)
    assert latest["page"]["has_more_before"] is True
    assert latest["page"]["loaded_event_count"] == 6


def test_large_trace_details_are_deferred_and_resolved(history, tmp_path, monkeypatch) -> None:
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
        history.append(key, event)

    payload = history.build(key, limit=40, direction="latest")

    assert payload is not None
    trace_event = next(event for event in payload["events"] if event.get("kind") == "progress")
    assert trace_event["text"] == "exec(…)"
    assert trace_event["trace_detail"]["bytes"] > 32 * 1024
    assert len(json.dumps(payload)) < len(trace)

    detail = history.trace(key, trace_event["trace_detail"]["ref"])

    assert detail is not None
    assert detail["message_id"] == trace_event["projection_id"]
    assert detail["events"][0]["text"] == trace
    assert "trace_detail" not in detail["events"][0]


def test_event_projection_augments_complete_stream_text(history, tmp_path, monkeypatch) -> None:
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
        history.append(key, event)

    payload = history.build(
        key,
        augment_assistant_text=lambda text: text.replace("output.png", "/api/media/signed"),
    )

    assert payload is not None
    assert [event["text"] for event in payload["events"]] == [
        "![plot](output.png)",
        "![plot](/api/media/signed)",
    ]


@pytest.mark.parametrize(
    ("delta_event", "end_event", "phase"),
    [("delta", "stream_end", "answer"), ("reasoning_delta", "reasoning_end", "reasoning")],
)
def test_thread_response_preserves_optional_stream_ids(history, delta_event, end_event, phase) -> None:
    key = "websocket:stream-identity"
    history.append(key, {"event": "user", "text": "question", "turn_id": "turn-stream"})
    for stream_id in ("wire-first", "wire-second", None):
        for event in (delta_event, end_event):
            history.append(key, {
                "event": event,
                "turn_id": "turn-stream",
                "turn_phase": phase,
                "text": "part",
                **({"stream_id": stream_id} if stream_id is not None else {}),
            })
    original_rows = history.read(key)

    payload = history.build(key)

    assert payload is not None
    stream_events = payload["events"][1:]
    assert [event["event"] for event in stream_events] == [delta_event, end_event] * 3
    assert [event.get("stream_id") for event in stream_events] == [
        "wire-first", "wire-first", "wire-second", "wire-second", None, None,
    ]
    assert all("stream_id" not in event for event in stream_events[-2:])
    assert all("projection_receipts" not in event for event in stream_events)
    assert history.read(key) == original_rows


@pytest.mark.parametrize(
    ("delta_event", "end_event", "phase"),
    [("delta", "stream_end", "answer"), ("reasoning_delta", "reasoning_end", "reasoning")],
)
@pytest.mark.parametrize("completed_text", [None, "canonical text"])
def test_thread_response_receipts_for_folded_legacy_deltas(
    history, delta_event, end_event, phase, completed_text,
) -> None:
    key = "websocket:folded-receipts"
    primary_text = completed_text or "first second last"
    rows = [
        {"event": "user", "text": "question", "turn_phase": "user", "turn_seq": 1},
        {"event": delta_event, "text": "first ", "stream_id": "primary", "turn_seq": 3},
        {"event": delta_event, "text": "second", "stream_id": "primary", "turn_seq": 4},
        {"event": "message", "kind": "progress", "text": "tool()", "turn_phase": "activity", "turn_seq": 5},
        {"event": delta_event, "text": "other", "stream_id": "secondary", "turn_seq": 6},
        {"event": delta_event, "text": " last", "stream_id": "primary", "turn_seq": 8},
        {"event": end_event, "stream_id": "primary", "turn_seq": 9,
         **({"text": completed_text} if completed_text is not None else {})},
        {"event": end_event, "stream_id": "secondary", "turn_seq": 10},
        {"event": "turn_end", "turn_phase": "complete", "turn_seq": 11},
    ]
    for row in rows:
        history.append(key, {"turn_id": "turn-folded", "turn_phase": phase, **row})
    original_rows = history.read(key)
    stats = TranscriptReplayStats()

    payload = history.build(key, stats=stats)

    assert payload is not None
    assert stats.compacted_delta_records == 4
    ends = [event for event in payload["events"] if event["event"] == end_event]
    assert [(event["stream_id"], event["turn_seq"], event["text"]) for event in ends] == [
        ("primary", 9, primary_text), ("secondary", 10, "other"),
    ]
    assert [event["projection_receipts"] for event in ends] == [
        [{"turn_id": "turn-folded", "ranges": [[3, 4], [8, 9]]}],
        [{"turn_id": "turn-folded", "ranges": [[6, 6], [10, 10]]}],
    ]
    assert history.read(key) == original_rows


def test_event_projection_defers_trace_details_without_legacy_fallback(history,
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
        history.append(key, event)

    trace = f'exec({json.dumps({"command": "x" * 40_000})})'

    payload = history.build(key)

    assert payload is not None
    assert "messages" not in payload
    assert payload["projection"] == "events"
    trace_event = next(event for event in payload["events"] if event.get("kind") == "progress")
    assert trace_event["text"] == "exec(…)"
    assert trace_event["trace_detail"]["bytes"] > 32 * 1024
    assert trace_event["trace_detail"]["traceCount"] == 1
    assert len(json.dumps(payload)) < len(trace)

    detail = history.trace(key, trace_event["trace_detail"]["ref"])

    assert detail is not None
    assert detail["message_id"] == trace_event["projection_id"]
    assert detail["events"][0]["text"] == trace
    assert "trace_detail" not in detail["events"][0]


@pytest.mark.parametrize(
    ("delta_event", "end_event"),
    [("reasoning_delta", "reasoning_end"), ("delta", "stream_end")],
)
def test_active_trace_details_match_compacted_event_page(history,
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
    for record in rows:
        history.append(key, record)
    original_rows = history.read(key)

    payload = history.build(key, limit=40, direction="latest")

    assert payload is not None
    trace_events = [
        event for event in payload["events"]
        if event.get("kind") == "progress"
    ]
    assert len(trace_events) == 2
    for event, trace in zip(trace_events, traces, strict=True):
        detail = history.trace(key, event["trace_detail"]["ref"])
        assert detail is not None
        assert detail["message_id"] == event["projection_id"]
        assert detail["events"][0]["text"] == trace
    assert history.read(key) == original_rows


def test_large_structured_trace_error_is_bounded_and_resolved(history, tmp_path, monkeypatch) -> None:
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
        history.append(key, event)

    payload = history.build(key, limit=40, direction="latest")

    assert payload is not None
    trace_event = next(
        event for event in payload["events"] if event.get("kind") == "progress"
    )
    assert len(json.dumps(trace_event).encode("utf-8")) < 4_096
    event_detail = history.trace(
        key,
        trace_event["trace_detail"]["ref"],
    )
    assert event_detail is not None
    assert event_detail["events"][0]["tool_events"][0]["error"] == full_error


def test_many_short_trace_rows_are_bounded_and_resolved(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:deferred-many-traces"
    trace_count = 2_000
    rows = [
        {"event": "user", "chat_id": "deferred-many-traces", "text": "run many tools"},
        *(
            {
                "event": "message",
                "chat_id": "deferred-many-traces",
                "kind": "progress",
                "text": f"tool_{index}(value)",
            }
            for index in range(trace_count)
        ),
        {"event": "message", "chat_id": "deferred-many-traces", "text": "done"},
        {"event": "turn_end", "chat_id": "deferred-many-traces"},
    ]
    history.sessions.append_history(
        key,
        [fact_from_record({**row, "created_at_ms": 1_700_000_000_000}) for row in rows],
    )

    payload = history.build(key, limit=40, direction="latest")

    assert payload is not None
    trace_event = next(event for event in payload["events"] if event.get("kind") == "progress")
    assert trace_event["trace_detail"]["traceCount"] == trace_count
    assert len(json.dumps(trace_event).encode("utf-8")) < 4_096

    detail = history.trace(key, trace_event["trace_detail"]["ref"])

    assert detail is not None
    assert len(detail["events"]) == trace_count
    assert detail["events"][0]["text"] == "tool_0(value)"
    assert detail["events"][-1]["text"] == f"tool_{trace_count - 1}(value)"


def test_thread_response_summary_receipts_preserve_holes_and_turn_membership(history) -> None:
    key = "websocket:summary-receipts"
    history.append(key, {"event": "user", "text": "run tools", "turn_id": "turn-T", "turn_seq": 1})
    members = [("turn-T", 3), ("turn-T", 4), ("turn-U", 2), ("turn-T", 8)]
    for turn_id, sequence in members:
        history.append(key, {
            "event": "message", "kind": "progress", "text": f'exec({"x" * 10_000})',
            "turn_id": turn_id, "turn_seq": sequence, "turn_phase": "activity",
        })
    history.append(key, {"event": "turn_end", "turn_id": "turn-T", "turn_seq": 9})
    original_rows = history.read(key)

    payload = history.build(key)

    assert payload is not None
    assert len(payload["events"]) == 3
    summary = payload["events"][1]
    assert summary["trace_detail"]["traceCount"] == len(members)
    assert summary["projection_receipts"] == [
        {"turn_id": "turn-T", "ranges": [[3, 4], [8, 8]]},
        {"turn_id": "turn-U", "ranges": [[2, 2]]},
    ]
    assert (summary["turn_id"], summary["turn_seq"]) == members[0]
    detail = history.trace(key, summary["trace_detail"]["ref"])
    assert detail is not None
    assert [(event["turn_id"], event["turn_seq"]) for event in detail["events"]] == members
    assert history.read(key) == original_rows


def test_transcript_revision_tracks_artifacts_and_variants(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:revision"
    history.append(key, {"event": "user", "chat_id": "revision", "text": "one"})

    first = history.revision(key, variant={"limit": 40})
    same = history.revision(key, variant={"limit": 40})
    other_variant = history.revision(key, variant={"limit": 80})
    history.append(key, {"event": "message", "chat_id": "revision", "text": "two"})
    changed = history.revision(key, variant={"limit": 40})

    assert first is not None
    assert same == first
    assert other_variant != first
    assert changed != first


def test_single_oversized_turn_is_bounded_and_marked(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_PAGE_RECORDS", 5)
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_PAGE_BYTES", 1_200)
    key = "websocket:oversized-turn"
    history.append(
        key,
        {"event": "user", "chat_id": "oversized-turn", "text": "question"},
    )
    for idx in range(20):
        history.append(
            key,
            {
                "event": "message",
                "chat_id": "oversized-turn",
                "kind": "progress",
                "text": f"progress {idx} " + ("x" * 160),
            },
        )
    history.append(
        key,
        {"event": "message", "chat_id": "oversized-turn", "text": "final answer"},
    )
    history.append(key, {"event": "turn_end", "chat_id": "oversized-turn"})
    stats = TranscriptReplayStats()

    latest = history.build(key, stats=stats)

    assert latest is not None
    assert stats.selected_records <= 5
    assert stats.selected_bytes <= 1_200
    assert stats.capped_by_records is True
    assert stats.capped_by_bytes is True
    assert stats.truncated_oversized_turn is True
    assert latest["page"]["truncated_oversized_turn"] is True
    assert _message_contents(latest) == ["question", "final answer"]


def test_truncated_turn_does_not_advertise_ambiguous_trace_detail(history,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_PAGE_RECORDS", 6)
    monkeypatch.setattr("nanobot.webui.transcript._MAX_TRANSCRIPT_PAGE_BYTES", 1_000_000)
    key = "websocket:truncated-trace-detail"
    history.append(
        key,
        {"event": "user", "chat_id": "truncated-trace-detail", "text": "question"},
    )
    for prefix in ("first", "second"):
        for idx in range(4):
            history.append(
                key,
                {
                    "event": "message",
                    "chat_id": "truncated-trace-detail",
                    "kind": "progress",
                    "text": f"{prefix}_{idx}({('x' * 12_000)})",
                },
            )
        if prefix == "first":
            history.append(
                key,
                {
                    "event": "message",
                    "chat_id": "truncated-trace-detail",
                    "text": "intermediate",
                },
            )
    history.append(
        key,
        {"event": "message", "chat_id": "truncated-trace-detail", "text": "done"},
    )
    history.append(
        key,
        {"event": "turn_end", "chat_id": "truncated-trace-detail"},
    )

    payload = history.build(key, limit=40, direction="latest")

    assert payload is not None
    assert payload["page"]["truncated_oversized_turn"] is True
    trace_event = next(event for event in payload["events"] if event.get("kind") == "progress")
    assert trace_event["text"] == "second_3(…)"
    assert "trace_detail" not in trace_event
    assert len(json.dumps(trace_event).encode("utf-8")) < 4_096


def test_page_cursor_survives_appends_after_latest_page(history,
    tmp_path,
    monkeypatch,
) -> None:
    key = "websocket:stable-cursor"
    _write_history_turns(history, tmp_path, monkeypatch, key, "stable-cursor", 7)

    latest = history.build(key, limit=4, direction="latest")
    assert latest is not None
    cursor = latest["page"]["before_cursor"]
    assert cursor
    assert _message_contents(latest) == _numbered_turn_texts(6, 7)

    for idx in range(8, 13):
        _append_numbered_turn(history, key, "stable-cursor", idx)

    older = history.build(key, limit=4, before=cursor)

    assert older is not None
    assert _message_contents(older) == _numbered_turn_texts(4, 5)


def test_build_response_reports_fork_boundary_from_marker(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:fork"
    for ev in (
        {"event": "user", "chat_id": "fork", "text": "round1"},
        {"event": "message", "chat_id": "fork", "text": "answer1"},
    ):
        history.append(key, ev)
    history.append(key, {"event": "fork_marker"})
    history.append(key, {"event": "user", "chat_id": "fork", "text": "new branch"})

    out = history.build(key)

    assert out is not None
    assert [m["content"] for m in _conversation_events(out)] == [
        "round1", "answer1", "new branch",
    ]
    assert out["fork_boundary_event_index"] == 2


def test_thread_response_does_not_mark_completed_message_tool_tail_pending(history,
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
        history.append(key, ev)

    out = history.build(key)

    assert out is not None
    assert out["has_pending_tool_calls"] is False
    assert out["completed_turn_ids"] == [turn_id]
    assert out["events"][-2]["kind"] == "progress"
    assert _conversation_events(out)[-1]["content"] == "Cron test"


def test_thread_response_marks_unfinished_tool_tail_pending(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:active-tail"
    history.append(
        key,
        {
            "event": "message",
            "chat_id": "active-tail",
            "text": 'exec({"command":"date"})',
            "kind": "tool_hint",
        },
    )

    out = history.build(key)

    assert out is not None
    assert out["has_pending_tool_calls"] is True
    assert out["completed_turn_ids"] == []


def test_thread_response_reports_active_registry_without_transcript(history,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    out = history.build(
        "websocket:active-without-transcript",
        active_turn_started_at=1_700_000_000.0,
        active_turn_id="turn-active",
    )

    assert out is not None
    assert out["events"] == []
    assert out["completed_turn_ids"] == []
    assert out["has_pending_tool_calls"] is True
    assert out["active_turn_id"] == "turn-active"


def test_thread_response_reports_explicit_completion_without_assistant_row(history,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:empty-answer"
    turn_id = "turn-empty-answer"
    history.append(
        key,
        {"event": "user", "chat_id": "empty-answer", "text": "stop", "turn_id": turn_id},
    )
    history.append(
        key,
        {"event": "turn_end", "chat_id": "empty-answer", "turn_id": turn_id},
    )

    out = history.build(key)

    assert out is not None
    assert _conversation_events(out)[-1]["role"] == "user"
    assert out["has_pending_tool_calls"] is False
    assert out["completed_turn_ids"] == [turn_id]


def test_incomplete_turn_with_ambiguous_session_match_stays_pending(history,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:ambiguous-incomplete"
    turn_id = "turn-ambiguous"
    history.append(
        key,
        {
            "event": "user",
            "chat_id": "ambiguous-incomplete",
            "text": "repeat",
            "turn_id": turn_id,
        },
    )
    history.append(
        key,
        {
            "event": "turn_end",
            "chat_id": "ambiguous-incomplete",
            "turn_id": turn_id,
            "transcript_incomplete": True,
        },
    )

    out = history.build(
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


def test_later_completion_does_not_hide_older_incomplete_turn(history,
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
        history.append(
            key,
            {"chat_id": "older-incomplete", **event},
        )

    out = history.build(key)

    assert out is not None
    assert out["completed_turn_ids"] == ["turn-second"]
    assert out["has_pending_tool_calls"] is True


def test_active_registry_does_not_hide_a_newer_queued_turn(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:queued-tail"
    for event in (
        {"event": "user", "text": "first", "turn_id": "turn-old"},
        {"event": "message", "text": "done", "turn_id": "turn-old"},
        {"event": "turn_end", "turn_id": "turn-old"},
        {"event": "user", "text": "queued next", "turn_id": "turn-new"},
    ):
        history.append(key, {"chat_id": "queued-tail", **event})

    out = history.build(
        key,
        active_turn_started_at=1_700_000_000.0,
        active_turn_id="turn-old",
    )

    assert out is not None
    assert out["has_pending_tool_calls"] is True


def test_build_response_restores_session_users_for_legacy_transcript(history,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:legacy-users"
    history.append(
        key,
        {"event": "message", "chat_id": "legacy-users", "text": "assistant one"},
    )
    history.append(key, {"event": "turn_end", "chat_id": "legacy-users"})
    history.append(
        key,
        {"event": "message", "chat_id": "legacy-users", "text": "assistant two"},
    )
    history.append(key, {"event": "turn_end", "chat_id": "legacy-users"})

    out = history.build(
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


def test_complete_transcript_does_not_load_session_messages(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:complete-fast-path"
    for event in (
        {"event": "user", "chat_id": "complete-fast-path", "text": "question"},
        {"event": "message", "chat_id": "complete-fast-path", "text": "answer"},
        {"event": "turn_end", "chat_id": "complete-fast-path"},
    ):
        history.append(key, event)

    def fail_if_loaded() -> list[dict]:
        raise AssertionError("complete transcripts must not read canonical session history")

    out = history.build(
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


def test_legacy_recovery_loads_session_and_builds_backfill_turns_once(history,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:lazy-legacy-recovery"
    history.append(
        key,
        {"event": "message", "chat_id": "lazy-legacy-recovery", "text": "answer"},
    )
    history.append(
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

    out = history.build(key, session_messages_loader=load_session_messages)

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


def test_build_response_restores_session_users_without_duplicating_new_transcript_users(history,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:mixed-users"
    history.append(
        key,
        {"event": "message", "chat_id": "mixed-users", "text": "old assistant"},
    )
    history.append(key, {"event": "turn_end", "chat_id": "mixed-users"})
    history.append(key, {"event": "user", "chat_id": "mixed-users", "text": "new prompt"})
    history.append(
        key,
        {"event": "message", "chat_id": "mixed-users", "text": "new assistant"},
    )
    history.append(key, {"event": "turn_end", "chat_id": "mixed-users"})

    out = history.build(
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


def test_build_response_backfills_legacy_sse_only_transcripts(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-legacy"
    for ev in (
        {"event": "delta", "chat_id": "t-legacy", "text": "first answer"},
        {"event": "stream_end", "chat_id": "t-legacy"},
        {"event": "turn_end", "chat_id": "t-legacy"},
        {"event": "message", "chat_id": "t-legacy", "text": "second answer"},
        {"event": "turn_end", "chat_id": "t-legacy"},
    ):
        history.append(key, ev)

    out = history.build(
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


def test_backfill_does_not_duplicate_existing_user_transcript(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-current"
    for ev in (
        {"event": "user", "chat_id": "t-current", "text": "already stored"},
        {"event": "message", "chat_id": "t-current", "text": "answer"},
        {"event": "turn_end", "chat_id": "t-current"},
    ):
        history.append(key, ev)

    out = history.build(
        key,
        session_messages=[{"role": "user", "content": "already stored"}],
    )

    assert out is not None
    assert [message["role"] for message in _conversation_events(out)] == [
        "user", "assistant",
    ]
    assert _conversation_events(out)[0]["content"] == "already stored"


def test_backfill_does_not_misalign_when_session_only_has_transcript_tail(history,
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
        history.append(key, ev)

    out = history.build(
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


def test_backfill_skips_internal_subagent_results(history, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t-subagent"
    for ev in (
        {"event": "message", "chat_id": "t-subagent", "text": "summary one"},
        {"event": "turn_end", "chat_id": "t-subagent"},
        {"event": "message", "chat_id": "t-subagent", "text": "summary two"},
        {"event": "turn_end", "chat_id": "t-subagent"},
    ):
        history.append(key, ev)

    legacy_raw = (
        "[Subagent 'legacy' completed successfully]\n\n"
        "Task: t\n\n"
        "Result:\nr\n\n"
        "Summarize this naturally for the user."
    )
    out = history.build(
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


def test_build_response_schema(history, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:t3"
    history.append(key, {"event": "user", "chat_id": "t3", "text": "x"})
    out = history.build(key, augment_user_media=None)
    assert out is not None
    assert out["schemaVersion"] == WEBUI_TRANSCRIPT_SCHEMA_VERSION
    assert out["sessionKey"] == key
    assert len(_conversation_events(out)) == 1


def test_shell_output_format_survives_reload_and_paging_without_loading_model_history(history, tmp_path) -> None:
    from nanobot.session.manager import SessionManager

    key = "websocket:shell-output"
    output = "Path\n----\n  __pycache__\n```mermaid\nflowchart LR\n```\n![preview](local.png)\n"
    history.append(key, {"event": "user", "text": "!pwd", "turn_id": "shell-turn"})
    history.append(key, {
        "event": "message", "text": output, "render_as": "text", "turn_id": "shell-turn",
    })
    history.append(key, {"event": "turn_end", "turn_id": "shell-turn"})
    _append_numbered_turn(history, key, "shell-output", 2)
    reopened = SessionManager(tmp_path)

    def fail_if_loaded():
        pytest.fail("Recorded output formatting must not load model history")

    def build(**kwargs):
        return reopened.project_history(key, lambda snapshot: transcript_module.build_webui_thread_response(
            key, history=snapshot, session_messages_loader=fail_if_loaded,
            augment_assistant_text=lambda text: text.replace("local.png", "/api/media/signed"), **kwargs,
        ))

    latest = build(limit=2, direction="latest")
    older = build(limit=2, before=latest["page"]["before_cursor"])
    [answer] = [event for event in older["events"] if event["event"] == "message"]
    assert answer["text"] == output
    assert answer["render_as"] == "text"
    assert history.read(key)[1]["text"] == output
    assert history.read(key)[1]["render_as"] == "text"


@pytest.mark.parametrize("command", [True, False])
def test_existing_shell_output_uses_canonical_command_identity_not_bang_text(history, command) -> None:
    key = "websocket:existing-shell-output"
    output = "Path\n----\n__pycache__"
    history.append(key, {"event": "user", "text": "!pwd", "turn_id": "shell-turn"})
    history.append(key, {"event": "message", "text": output, "turn_id": "shell-turn"})
    history.append(key, {"event": "turn_end", "turn_id": "shell-turn"})
    messages = [
        {"role": "user", "content": "/__shell pwd" if command else "!pwd",
         "webui_turn_id": "shell-turn", "_command": command},
        {"role": "assistant", "content": output, "_command": command},
    ]
    response = history.build(key, session_messages=messages)
    [answer] = [event for event in response["events"] if event["event"] == "message"]
    assert answer["text"] == output
    assert answer.get("render_as") == ("text" if command else None)
    assert history.read(key)[1]["text"] == output
    assert messages[1]["content"] == output
