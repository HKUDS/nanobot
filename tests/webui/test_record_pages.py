import base64
import json
import time

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.session.display_history import HistoryFact
from nanobot.session.history_graph import history_record_size
from nanobot.webui import transcript
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.history import fact_from_record


def _legacy_cursor(turn):
    raw = json.dumps({"before_turn": turn}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.parametrize("budget", ["records", "bytes"])
def test_oversized_turn_pages_are_contiguous_and_replay_raw_events(history, monkeypatch, budget):
    key = "websocket:record-pages"
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 4 if budget == "records" else 100)
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_BYTES", 500 if budget == "bytes" else 100_000)
    monkeypatch.setattr(transcript, "_MAX_INLINE_TRACE_DETAIL_BYTES", 10)
    rows = [
        {"event": "user", "text": "previous", "turn_id": "previous"},
        {"event": "turn_end", "turn_id": "previous"},
        {"event": "user", "text": "first", "turn_id": "execution", "turn_seq": 1},
        {"event": "delta", "text": "![plot](diagram", "turn_id": "execution", "turn_seq": 2},
        {"event": "delta", "text": ".png)", "turn_id": "execution", "turn_seq": 3},
        {"event": "stream_end", "text": "![plot](/api/media/signed)", "turn_id": "execution", "turn_seq": 4},
        {"event": "message", "kind": "progress", "text": "trace one with full detail", "turn_id": "execution", "turn_seq": 5},
        {"event": "user", "text": "second", "turn_id": "execution", "turn_seq": 6},
        {"event": "message", "kind": "progress", "text": "trace two with full detail", "turn_id": "execution", "turn_seq": 7},
        {"event": "message", "text": "answer", "turn_id": "execution", "turn_seq": 8},
        {"event": "turn_end", "turn_id": "execution", "turn_seq": 9, "transcript_incomplete": True},
        {"event": "user", "text": "next", "turn_id": "next"},
        {"event": "turn_end", "turn_id": "next"},
    ]
    for row in rows:
        history.append(key, row)

    decoded = []
    original_decode = HistoryFact.decode

    def track_decode(record):
        decoded.append(record)
        return original_decode(record)

    monkeypatch.setattr(HistoryFact, "decode", track_decode)

    def no_canonical_load():
        pytest.fail("a sliced turn must not trigger canonical recovery")

    def read(**kwargs):
        decoded.clear()
        stats = transcript.TranscriptReplayStats()
        page = history.build(key, limit=100, stats=stats,
                             session_messages_loader=no_canonical_load, **kwargs)
        assert page is not None
        assert stats.parsed_records == len(decoded) <= transcript._MAX_TRANSCRIPT_PAGE_RECORDS
        assert stats.source_bytes == sum(max(len(record.encode("utf-8")), history_record_size(record)) for record in decoded)
        assert stats.source_bytes <= transcript._MAX_TRANSCRIPT_PAGE_BYTES
        return page

    latest = read()
    backwards = [latest]
    while backwards[-1]["page"]["has_more_before"]:
        backwards.append(read(before=backwards[-1]["page"]["before_cursor"]))
        assert len(backwards) < 20
    chronological = list(reversed(backwards))
    fragments = [page for page in chronological if "record_range" in page["page"]]
    ranges = [page["page"]["record_range"] for page in fragments]
    assert len(ranges) > 1
    assert all(r["turn"] == 1 for r in ranges)
    assert ranges[0]["start"] == 0 and ranges[-1]["end"] == 9
    assert all(a["end"] == b["start"] for a, b in zip(ranges, ranges[1:]))
    assert all(page["page"]["truncated_oversized_turn"] for page in fragments)
    events = [event for page in chronological for event in page["events"]]
    target = [event for event in events if event.get("turn_id") == "execution"]
    assert [event["turn_seq"] for event in target] == list(range(1, 10))
    assert [event["event"] for event in target[1:4]] == ["delta", "delta", "stream_end"]
    assert [event["text"] for event in target[1:4]] == ["![plot](diagram", ".png)", "![plot](/api/media/signed)"]
    progress = [event for event in target if event.get("kind") == "progress"]
    assert [event["text"] for event in progress] == ["trace one with full detail", "trace two with full detail"]
    assert all("trace_detail" not in event for event in progress)
    assert len({event["projection_id"] for event in events}) == len(events)

    forwards = [read(after=_legacy_cursor(0))]
    while forwards[-1]["page"]["has_more_after"]:
        forwards.append(read(after=forwards[-1]["page"]["after_cursor"]))
        assert len(forwards) < 20
    forward_events = [event for page in forwards for event in page["events"]]
    assert forward_events == events

    prompts = history.prompts(key)
    assert [p["preview"] for p in prompts] == ["previous", "first", "second", "next"]
    for offset, prompt in enumerate(prompts):
        page = read(after=prompt["cursor"])
        assert page["events"][0]["projection_id"] == prompt["id"]
        assert page["page"]["user_message_offset"] == offset

    old = read(after=_legacy_cursor(1))
    assert old["events"][0]["text"] == "first"


def test_page_generation_is_stable_across_appends_and_changes_after_recreation(history):
    key = "websocket:page-generation"
    history.append(key, {"event": "user", "text": "first"})
    first = history.build(key)["page"]["history_generation"]
    history.append(key, {"event": "message", "text": "answer"})
    assert history.build(key)["page"]["history_generation"] == first
    history.sessions.delete_session(key)
    history.append(key, {"event": "user", "text": "replacement"})
    assert history.build(key)["page"]["history_generation"] != first


def test_single_record_larger_than_page_budget_still_makes_progress(history, monkeypatch):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_BYTES", 200)
    key = "websocket:large-record"
    for record in (
        {"event": "user", "text": "x" * 400},
        {"event": "message", "text": "answer"},
        {"event": "turn_end"},
    ):
        history.append(key, record)
    stats = transcript.TranscriptReplayStats()
    first = history.build(key, after=_legacy_cursor(0), stats=stats)
    assert first["page"]["record_range"] == {"turn": 0, "start": 0, "end": 1}
    assert first["events"][0]["text"] == "x" * 400
    assert 200 < stats.source_bytes < 1_000
    second = history.build(key, after=first["page"]["after_cursor"])
    assert second["page"]["record_range"]["start"] == 1
    assert history.build(key, before=second["page"]["before_cursor"])["events"] == first["events"]


def test_sliced_projection_retains_model_requests_and_stable_event_ids(history, monkeypatch):
    key = "websocket:model-request-pages"
    for record in (
        {"event": "user", "text": "question"},
        {"event": "model_request", "request_id": "r", "run_id": "run", "sequence": 1, "phase": "started"},
        {"event": "message", "text": "answer"},
        {"event": "turn_end"},
    ):
        history.append(key, record)
    complete = history.build(key, include_model_requests=True)
    assert "record_range" not in complete["page"]
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 2)
    first = history.build(key, after=_legacy_cursor(0), include_model_requests=True)
    second = history.build(key, after=first["page"]["after_cursor"], include_model_requests=True)
    assert [event["event"] for event in first["events"]] == ["user_message", "model_request"]
    assert first["events"] + second["events"] == complete["events"]
    without_requests = history.build(key, after=_legacy_cursor(0))
    assert [event["event"] for event in without_requests["events"]] == ["user_message"]
    assert without_requests["page"]["after_cursor"] == first["page"]["after_cursor"]


def test_stale_trace_reference_does_not_read_an_oversized_turn(history, monkeypatch):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 3)
    monkeypatch.setattr(transcript, "_MAX_INLINE_TRACE_DETAIL_BYTES", 10)
    key = "websocket:trace-grows"
    history.append(key, {"event": "user", "text": "question"})
    history.append(key, {"event": "message", "kind": "progress", "text": "full trace text"})
    page = history.build(key)
    reference = next(event["trace_detail"]["ref"] for event in page["events"] if event.get("trace_detail"))
    assert history.trace(key, reference) is not None
    history.append(key, {"event": "message", "kind": "progress", "text": "another trace"})
    history.append(key, {"event": "message", "kind": "progress", "text": "yet another trace"})
    assert history.trace(key, reference) is None


@pytest.mark.asyncio
async def test_http_defaults_to_record_pages_and_accepts_legacy_turn_cursor(history, tmp_path, monkeypatch):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 2)
    key = "websocket:http-pages"
    for record in (
        {"event": "user", "text": "first"},
        {"event": "message", "text": "one"},
        {"event": "user", "text": "second"},
        {"event": "message", "text": "two"},
        {"event": "turn_end"},
    ):
        history.append(key, record)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MessageBus(), session_manager=history.sessions,
        static_dist_path=None, workspace_path=tmp_path, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    gateway.tokens.api_tokens["test-token"] = time.monotonic() + 60
    headers = Headers([("Authorization", "Bearer test-token")])
    path = "/api/sessions/websocket%3Ahttp-pages/webui-thread"

    async def get(query):
        response = await gateway.http._dispatch_session_routes(Request(path + query, headers), path)
        assert response.status_code == 200
        return json.loads(response.body)

    latest = await get("")
    assert latest["page"]["record_range"] == {"turn": 0, "start": 3, "end": 5}
    earlier = await get("?before=" + latest["page"]["before_cursor"])
    assert earlier["page"]["record_range"] == {"turn": 0, "start": 1, "end": 3}
    from_legacy = await get("?after=" + _legacy_cursor(0))
    assert from_legacy["page"]["record_range"] == {"turn": 0, "start": 0, "end": 2}
    response = await gateway.http._dispatch_session_routes(Request(path + "/prompts", headers), path + "/prompts")
    assert response.status_code == 200
    prompts = json.loads(response.body)
    second = await get("?after=" + prompts["prompts"][1]["cursor"])
    assert second["events"][0]["projection_id"] == prompts["prompts"][1]["id"]
    assert second["page"]["user_message_offset"] == 1


def test_compaction_does_not_reuse_the_source_record_budget(history, monkeypatch):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 10)
    key = "websocket:compacted-source-budget"
    for i in range(3):
        for row in [
            {"event": "user", "text": f"question {i}"},
            *({"event": "delta", "text": "x"} for _ in range(4)),
            {"event": "stream_end", "text": "xxxx"},
            {"event": "turn_end"},
        ]:
            history.append(key, row)
    stats = transcript.TranscriptReplayStats()
    latest = history.build(key, limit=100, stats=stats)
    assert stats.parsed_records == 7
    assert stats.compacted_delta_records == 4
    assert len(latest["events"]) == 3
    assert "record_range" not in latest["page"]
    assert latest["page"]["has_more_before"]


def test_source_budget_accounts_for_graphs_larger_in_storage(history, monkeypatch):
    key = "websocket:graph-byte-budget"
    graph = {"nodes": [{"path": "/a", "name": "a", "tokens": 1, "state": "loaded"}], "edges": []}
    rows = [
        {"event": "user", "text": "question", "created_at_ms": 1},
        *({"event": "model_request", "request_id": str(i), "run_id": "run", "sequence": 1,
           "phase": "started", "context_graph": graph, "created_at_ms": 1} for i in range(2)),
        {"event": "turn_end", "created_at_ms": 1},
    ]
    encoded = [fact_from_record(row).encode() for row in rows]
    logical = sum(history_record_size(record) for record in encoded)
    actual = sum(max(history_record_size(record), len(record.encode("utf-8"))) for record in encoded)
    assert logical < actual
    for row in rows:
        history.append(key, row)
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_BYTES", logical)
    stats = transcript.TranscriptReplayStats()
    first = history.build(key, after=_legacy_cursor(0), include_model_requests=True, stats=stats)
    assert first["page"]["record_range"]["start"] == 0
    assert stats.source_bytes <= logical
    assert stats.capped_by_bytes
    second = history.build(key, after=first["page"]["after_cursor"], include_model_requests=True)
    assert second["page"]["record_range"]["start"] == first["page"]["record_range"]["end"]
    events = first["events"] + second["events"]
    assert [event["event"] for event in events] == ["user_message", "model_request", "model_request", "turn_end"]
    assert all(event["context_graph"] == graph for event in events if event["event"] == "model_request")

    # Stored turn aggregates can understate bytes when a small compressed graph
    # expands. If an earlier turn already occupies the page, do not mix a
    # partially read next turn into it or lose the next turn's boundary.
    other = "websocket:graph-after-normal-turn"
    previous = [{"event": "user", "text": "previous", "created_at_ms": 1},
                {"event": "turn_end", "created_at_ms": 1}]
    for row in [*previous, *rows]:
        history.append(other, row)
    previous_bytes = sum(history_record_size(fact_from_record(row).encode()) for row in previous)
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_BYTES", logical + previous_bytes)
    stats = transcript.TranscriptReplayStats()
    initial = history.build(other, after=_legacy_cursor(0), include_model_requests=True, stats=stats)
    assert [event["event"] for event in initial["events"]] == ["user_message", "turn_end"]
    assert "record_range" not in initial["page"]
    assert stats.capped_by_bytes and stats.source_bytes <= logical + previous_bytes
    following = history.build(other, after=initial["page"]["after_cursor"], include_model_requests=True)
    assert [event["event"] for event in following["events"]] == ["user_message", "model_request", "model_request", "turn_end"]


@pytest.mark.parametrize("user_position", [0, 13])
def test_oversized_incomplete_turn_recovers_once_across_all_fragments(history, monkeypatch, user_position):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 4)
    key = "websocket:incomplete-record-pages"
    turn_id = "incomplete-turn"
    rows = [
        {"event": "user", "text": "unique question", "turn_id": turn_id},
        {"event": "delta", "text": "partial", "turn_id": turn_id},
        *({"event": "message", "kind": "progress", "text": f"step {i}", "turn_id": turn_id}
          for i in range(20)),
        {"event": "turn_end", "turn_id": turn_id, "transcript_incomplete": True},
    ]
    user = rows.pop(0)
    rows.insert(user_position, user)
    for row in rows:
        history.append(key, row)
    original_history = history.read(key)
    messages = [
        {"role": "user", "content": "unique question"},
        {"role": "assistant", "content": "complete canonical answer"},
    ]
    def read(**kwargs):
        stats = transcript.TranscriptReplayStats()
        page = history.build(key, session_messages=messages, stats=stats, **kwargs)
        assert stats.parsed_records <= 4
        assert stats.source_bytes <= transcript._MAX_TRANSCRIPT_PAGE_BYTES
        return page

    pages = [read(after=_legacy_cursor(0))]
    while pages[-1]["page"]["has_more_after"]:
        pages.append(read(after=pages[-1]["page"]["after_cursor"]))
        assert len(pages) < len(rows)
    events = [event for page in pages for event in page["events"]]
    assert [event["text"] for event in events if event["event"] == "message" and not event.get("kind")] == [
        "complete canonical answer",
    ]
    assert not any(event["event"] == "delta" for event in events)
    assert pages[-1]["completed_turn_ids"] == [turn_id]
    assert pages[-1]["has_pending_tool_calls"] is False
    assert len({event["projection_id"] for event in events}) == len(events)
    ranges = [page["page"]["record_range"] for page in pages]
    assert ranges[0]["start"] == 0 and ranges[-1]["end"] == len(rows)
    assert all(left["end"] == right["start"] for left, right in zip(ranges, ranges[1:]))
    recovered = next(event for event in events if event.get("text") == "complete canonical answer")
    latest = read()
    assert latest["page"]["recovered_answers"] is True
    assert next(event for event in latest["events"] if event.get("text") == recovered["text"]) == recovered
    for left, right in zip(pages, pages[1:]):
        assert read(before=right["page"]["before_cursor"])["events"] == left["events"]
    assert history.read(key) == original_history


def test_oversized_legacy_prompt_cursor_finds_backfilled_user_on_cold_page(history, monkeypatch):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 4)
    key = "websocket:legacy-record-pages"
    rows = [
        *({"event": "message", "kind": "progress", "text": f"step {i}"} for i in range(20)),
        {"event": "message", "text": "distinct answer"},
        {"event": "turn_end"},
    ]
    for row in rows:
        history.append(key, row)
    messages = [
        {"role": "user", "content": "restored question"},
        {"role": "assistant", "content": "distinct answer"},
    ]
    prompts = history.prompts(key, session_messages_loader=lambda: messages)
    assert [prompt["preview"] for prompt in prompts] == ["restored question"]
    transcript._PROMPT_SNAPSHOTS.clear()
    def read(**kwargs):
        stats = transcript.TranscriptReplayStats()
        page = history.build(key, session_messages=messages, stats=stats, **kwargs)
        assert stats.parsed_records <= 4
        assert stats.source_bytes <= transcript._MAX_TRANSCRIPT_PAGE_BYTES
        return page

    page = read(after=prompts[0]["cursor"])
    assert page["events"][0]["event"] == "user_message"
    assert page["events"][0]["projection_id"] == prompts[0]["id"]
    pages = [page]
    while pages[-1]["page"]["has_more_after"]:
        pages.append(read(after=pages[-1]["page"]["after_cursor"]))
        assert len(pages) < len(rows)
    events = [event for current in pages for event in current["events"]]
    assert [event["text"] for event in events if event["event"] == "user_message"] == ["restored question"]
    assert [event["text"] for event in events if event["event"] == "message" and not event.get("kind")] == [
        "distinct answer",
    ]


def test_recovered_prompt_cursor_keeps_answers_owned_by_both_inputs(history):
    key = "websocket:backfilled-input-recovery"
    rows = [
        {"event": "user", "text": "A", "input_id": "user:a", "turn_id": "t", "turn_seq": 1},
        {"event": "message", "text": "Answer A", "response_input_ids": ["user:a"], "turn_id": "t", "turn_seq": 2},
        {"event": "message", "kind": "progress", "text": "Working", "turn_id": "t", "turn_seq": 3},
        {"event": "message", "text": "Answer B", "response_input_ids": ["user:b"], "turn_id": "t", "turn_seq": 4},
        {"event": "message", "kind": "progress", "text": "Finished", "turn_id": "t", "turn_seq": 5},
        {"event": "turn_end", "turn_id": "t", "turn_seq": 6, "transcript_incomplete": True},
    ]
    for row in rows:
        history.append(key, row)
    original = history.read(key)
    messages = [
        {"role": "user", "content": "A", "input_id": "user:a"},
        {"role": "assistant", "content": "Answer A", "response_input_ids": ["user:a"]},
        {"role": "user", "content": "B", "input_id": "user:b"},
        {"role": "assistant", "content": "Answer B", "response_input_ids": ["user:b"]},
    ]
    whole = history.build(key, session_messages=messages)
    prompts = history.prompts(key, session_messages_loader=lambda: messages)
    prompt = next(item for item in prompts if item["inputId"] == "user:b")
    navigated = history.build(key, after=prompt["cursor"], session_messages=messages)

    def contents(body):
        return [event["text"] for event in body["events"]
                if event["event"] in {"user_message", "message"} and not event.get("kind")]

    assert contents(whole) == ["A", "Answer A", "B", "Answer B"]
    assert contents(navigated) == ["B", "Answer B"]
    assert navigated["events"][0]["projection_id"] == prompt["id"]
    assert whole["completed_turn_ids"] == navigated["completed_turn_ids"] == []
    assert navigated["has_pending_tool_calls"] is True
    assert history.read(key) == original


@pytest.mark.parametrize("ambiguous", ["duplicate-canonical-user", "two-physical-users"])
def test_sliced_incomplete_turn_preserves_partial_answers_when_match_is_ambiguous(history, monkeypatch, ambiguous):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 3)
    key = f"websocket:ambiguous-fragments-{ambiguous}"
    rows = [
        {"event": "user", "text": "same question", "turn_id": "t"},
        {"event": "delta", "text": "partial", "turn_id": "t"},
        *({"event": "message", "kind": "progress", "text": f"step {i}", "turn_id": "t"} for i in range(8)),
        {"event": "turn_end", "turn_id": "t", "transcript_incomplete": True},
    ]
    if ambiguous == "two-physical-users":
        rows.insert(7, {"event": "user", "text": "another question", "turn_id": "t"})
    for row in rows:
        history.append(key, row)
    messages = [{"role": "user", "content": "same question"}, {"role": "assistant", "content": "answer"}]
    if ambiguous == "duplicate-canonical-user":
        messages += [{"role": "user", "content": "same question"}, {"role": "assistant", "content": "another answer"}]
    pages = [history.build(key, after=_legacy_cursor(0), session_messages=messages)]
    while pages[-1]["page"]["has_more_after"]:
        pages.append(history.build(key, after=pages[-1]["page"]["after_cursor"], session_messages=messages))
    events = [event for page in pages for event in page["events"]]
    assert [event["text"] for event in events if event["event"] == "delta"] == ["partial"]
    assert not any(event.get("text") in {"answer", "another answer"} for event in events)
    assert pages[-1]["completed_turn_ids"] == []
    assert pages[-1]["has_pending_tool_calls"] is True


def test_legacy_fragment_does_not_backfill_when_user_is_in_another_slice(history, monkeypatch):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 3)
    key = "websocket:physical-user-in-later-slice"
    rows = [
        *({"event": "message", "kind": "progress", "text": f"step {i}"} for i in range(5)),
        {"event": "user", "text": "real user"},
        {"event": "message", "text": "answer"},
        {"event": "turn_end"},
    ]
    for row in rows:
        history.append(key, row)
    messages = [{"role": "user", "content": "wrong user"}, {"role": "assistant", "content": "answer"}]
    page = history.build(key, after=_legacy_cursor(0), session_messages=messages)
    assert all(event["event"] != "user_message" for event in page["events"])
    prompts = history.prompts(key, session_messages_loader=lambda: messages)
    assert [prompt["preview"] for prompt in prompts] == ["real user"]


def test_byte_limited_terminal_fragment_recovers_the_answer(history, monkeypatch):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 100)
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_BYTES", 500)
    key = "websocket:recovery-byte-budget"
    rows = [
        {"event": "user", "text": "question"},
        *({"event": "message", "kind": "progress", "text": "x" * 150} for _ in range(6)),
        {"event": "turn_end", "turn_id": "t", "transcript_incomplete": True},
    ]
    for row in rows:
        history.append(key, row)
    messages = [{"role": "user", "content": "question"}, {"role": "assistant", "content": "answer"}]
    stats = transcript.TranscriptReplayStats()
    page = history.build(key, session_messages=messages, stats=stats)
    assert page["completed_turn_ids"] == ["t"]
    assert stats.source_bytes <= 500
    pages = [page]
    while pages[-1]["page"]["has_more_before"]:
        pages.append(history.build(key, session_messages=messages, before=pages[-1]["page"]["before_cursor"]))
    answers = [event["text"] for page in pages for event in page["events"]
               if event["event"] == "message" and not event.get("kind")]
    assert answers == ["answer"]


def test_complete_single_user_fragment_keeps_normal_budget_without_loading_canonical(history, monkeypatch):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 3)
    key = "websocket:complete-single-user-fragment"
    for row in [
        {"event": "user", "text": "question"},
        *({"event": "message", "kind": "progress", "text": "step"} for _ in range(8)),
        {"event": "message", "text": "answer"},
        {"event": "turn_end"},
    ]:
        history.append(key, row)

    def fail_if_loaded():
        pytest.fail("a complete fragment must not load canonical history")

    stats = transcript.TranscriptReplayStats()
    page = history.build(key, after=_legacy_cursor(0), session_messages_loader=fail_if_loaded, stats=stats)
    assert page["page"]["record_range"] == {"turn": 0, "start": 0, "end": 3}
    assert stats.parsed_records == 3
    assert stats.source_bytes <= transcript._MAX_TRANSCRIPT_PAGE_BYTES


def test_legacy_prompt_id_agrees_with_warm_and_cold_snapshots(history, monkeypatch):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 3)
    key = "websocket:legacy-prompt-snapshot"
    for row in [
        *({"event": "message", "kind": "progress", "text": "step"} for _ in range(8)),
        {"event": "message", "text": "answer"},
        {"event": "turn_end"},
    ]:
        history.append(key, row)
    messages = [{"role": "user", "content": "question"}, {"role": "assistant", "content": "answer"}]

    def version():
        return ("canonical-generation", 1)

    response = history.prompt_response(key, None, session_messages_loader=lambda: messages, session_version_loader=version)
    prompt = response["prompts"][0]
    warm = history.build(key, after=prompt["cursor"], session_messages=messages, session_version_loader=version)
    assert warm["events"][0]["projection_id"] == prompt["id"]
    transcript._PROMPT_SNAPSHOTS.clear()
    cold = history.build(key, after=prompt["cursor"], session_messages=messages, session_version_loader=version)
    assert cold["events"] == warm["events"]


def test_legacy_backfill_does_not_make_an_incomplete_turn_physically_recoverable(history, monkeypatch):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 3)
    key = "websocket:legacy-incomplete-without-physical-user"
    for row in [
        *({"event": "message", "kind": "progress", "text": f"step {i}"} for i in range(7)),
        {"event": "message", "text": "partial answer"},
        {"event": "turn_end", "turn_id": "t", "transcript_incomplete": True},
    ]:
        history.append(key, row)
    messages = [{"role": "user", "content": "restored question"},
                {"role": "assistant", "content": "partial answer"}]
    pages = [history.build(key, after=_legacy_cursor(0), session_messages=messages)]
    while pages[-1]["page"]["has_more_after"]:
        pages.append(history.build(key, after=pages[-1]["page"]["after_cursor"], session_messages=messages))
    events = [event for page in pages for event in page["events"]]
    assert [event["text"] for event in events if event["event"] == "user_message"] == ["restored question"]
    assert [event["text"] for event in events if event["event"] == "message" and not event.get("kind")] == ["partial answer"]
    assert pages[-1]["completed_turn_ids"] == []
    assert pages[-1]["has_pending_tool_calls"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_http_fragment_recovery_reads_persisted_canonical_history(history, tmp_path, monkeypatch, legacy):
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 3)
    key = f"websocket:http-recovery-{legacy}"
    session = history.sessions.get_or_create(key)
    session.add_message("user", "question")
    session.add_message("assistant", "canonical answer")
    history.sessions.save(session)
    rows = [
        *({"event": "message", "kind": "progress", "text": f"step {i}"} for i in range(8)),
        {"event": "message" if legacy else "delta", "text": "canonical answer" if legacy else "partial"},
        {"event": "turn_end", "turn_id": "t", **({} if legacy else {"transcript_incomplete": True})},
    ]
    if not legacy:
        rows.insert(5, {"event": "user", "text": "question"})
    for row in rows:
        history.append(key, row)
    original = history.read(key)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MessageBus(), session_manager=history.sessions,
        static_dist_path=None, workspace_path=tmp_path, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    gateway.tokens.api_tokens["test-token"] = time.monotonic() + 60
    headers = Headers([("Authorization", "Bearer test-token")])
    path = "/api/sessions/" + key.replace(":", "%3A") + "/webui-thread"

    async def get(query):
        response = await gateway.http._dispatch_session_routes(Request(path + query, headers), path)
        assert response.status_code == 200
        return json.loads(response.body)

    if legacy:
        response = await gateway.http._dispatch_session_routes(Request(path + "/prompts", headers), path + "/prompts")
        assert response.status_code == 200
        prompt = json.loads(response.body)["prompts"][0]
        transcript._PROMPT_SNAPSHOTS.clear()
        first = await get("?after=" + prompt["cursor"])
        assert first["events"][0]["projection_id"] == prompt["id"]
    else:
        first = await get("?after=" + _legacy_cursor(0))
    pages = [first]
    while pages[-1]["page"]["has_more_after"]:
        pages.append(await get("?after=" + pages[-1]["page"]["after_cursor"]))
        assert len(pages) <= len(rows)
    events = [event for page in pages for event in page["events"]]
    assert [event["text"] for event in events if event["event"] == "user_message"] == ["question"]
    assert [event["text"] for event in events if event["event"] == "message" and not event.get("kind")] == ["canonical answer"]
    assert not any(event["event"] == "delta" for event in events)
    assert pages[-1]["completed_turn_ids"] == ["t"]
    assert pages[-1]["has_pending_tool_calls"] is False
    assert history.read(key) == original
