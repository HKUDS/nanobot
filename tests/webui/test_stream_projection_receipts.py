import asyncio
import json
import sqlite3
import time
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent, TurnEndEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.session.display_history import MAX_HISTORY_FACT_BYTES
from nanobot.session.manager import SessionManager
from nanobot.webui import transcript
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.history import fact_from_record
from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY


def _gateway(history, tmp_path, monkeypatch):
    def media_dir(channel=None):
        path = tmp_path / "media" / (channel or "")
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("nanobot.webui.media_gateway.get_media_dir", media_dir)
    monkeypatch.setattr("nanobot.webui.gateway_services.get_media_dir", media_dir)
    bus = MessageBus()
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=bus, session_manager=history.sessions,
        static_dist_path=None, workspace_path=tmp_path, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"], "streaming": True}, bus, gateway=gateway)
    return gateway, channel


async def _http_thread(gateway, chat_id):
    gateway.tokens.api_tokens["test-token"] = time.monotonic() + 60
    headers = Headers([("Authorization", "Bearer test-token")])
    path = f"/api/sessions/websocket%3A{chat_id}/webui-thread"
    response = await gateway.http._dispatch_session_routes(Request(path, headers), path)
    assert response.status_code == 200
    return json.loads(response.body)


def _frames(ws):
    return [json.loads(call.args[0]) for call in ws.send.await_args_list]


@pytest.mark.asyncio
async def test_signed_stream_receipts_follow_exact_snapshots_through_http_and_restart(history, tmp_path, monkeypatch):
    (tmp_path / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
    gateway, channel = _gateway(history, tmp_path, monkeypatch)
    ws = AsyncMock()
    channel._attach(ws, "receipts")
    metadata = await history.metadata("receipts", {WEBUI_TURN_METADATA_KEY: "turn-one"})

    async def delta(text, stream="primary", **kwargs):
        await channel.send_delta("receipts", text, metadata, stream_id=stream, **kwargs)

    await delta("![plot](diagram")
    await channel.send(OutboundMessage(channel="websocket", chat_id="receipts", content="tool()",
                                      event=ProgressEvent(content="tool()"), metadata=metadata))
    await channel.send_reasoning_delta("receipts", "thinking", metadata, stream_id="primary")
    await delta(".png)")
    await delta("unrelated", stream="other")
    await delta("", stream_end=True, resuming=True, merge_next=True)
    await delta(" more")
    await delta("", stream_end=True)
    await channel.send_reasoning_end("receipts", metadata, stream_id="primary")
    await delta("", stream="other", stream_end=True)
    await channel.send(OutboundMessage(channel="websocket", chat_id="receipts", content="",
                                      event=TurnEndEvent(), metadata=metadata))

    live = _frames(ws)
    frames = [frame for frame in live if frame["event"] == "delta"]
    first, second, other = [frame for frame in live if frame["event"] == "stream_end"]
    reasoning = next(frame for frame in live if frame["event"] == "reasoning_delta")
    assert "diagram.png" in "".join(frame["text"] for frame in frames)
    assert "/api/media/" in first["text"] and "/api/media/" in second["text"]
    expected = [
        [{"turn_id": "turn-one", "ranges": [[frames[0]["turn_seq"], frames[0]["turn_seq"]],
                                              [frames[1]["turn_seq"], frames[1]["turn_seq"]]]}],
        [{"turn_id": "turn-one", "ranges": [[frames[0]["turn_seq"], frames[0]["turn_seq"]],
                                              [frames[1]["turn_seq"], frames[1]["turn_seq"]],
                                              [frames[3]["turn_seq"], frames[3]["turn_seq"]]]}],
        [{"turn_id": "turn-one", "ranges": [[frames[2]["turn_seq"], frames[2]["turn_seq"]]]}],
    ]
    stored = history.read("websocket:receipts")
    ends = [row for row in stored if row["event"] == "stream_end"]
    assert [row["_webui_projection_receipts"] for row in ends] == expected
    reason_end = next(row for row in stored if row["event"] == "reasoning_end")
    assert reason_end["_webui_projection_receipts"] == [
        {"turn_id": "turn-one", "ranges": [[reasoning["turn_seq"], reasoning["turn_seq"]]]}
    ]
    assert "diagram.png" not in json.dumps(stored)
    assert all(row["event"] not in {"delta", "reasoning_delta"} for row in stored)
    with closing(sqlite3.connect(history.sessions.sessions_dir / "sessions.sqlite3")) as db:
        records = [row[0] for row in db.execute("SELECT record FROM history_entries")]
    assert "diagram.png" not in "".join(records)
    assert "_webui_projection_receipts" in "".join(records)
    payload = await _http_thread(gateway, "receipts")
    projected = [event for event in payload["events"] if event["event"] == "stream_end"]
    assert [event["projection_receipts"] for event in projected] == expected
    signed_url = first["text"].split("(", 1)[1].split(")", 1)[0]
    _, _, _, signature, signed_payload = signed_url.split("/")
    assert gateway.media.serve_signed_media(signature, signed_payload).status_code == 200

    # A fresh session owner, gateway, recorder and media signing key simulate restart.
    await history.sessions.state.aclose()
    restarted_sessions = SessionManager(tmp_path)
    try:
        restarted, _ = _gateway(SimpleNamespace(sessions=restarted_sessions), tmp_path, monkeypatch)
        payload = await _http_thread(restarted, "receipts")
        projected = [event for event in payload["events"] if event["event"] == "stream_end"]
        assert [event["projection_receipts"] for event in projected] == expected
        assert projected[0]["text"] == first["text"]
        # Restored signed media should remain usable after the gateway restarts.
        assert restarted.media.serve_signed_media(signature, signed_payload).status_code == 200
    finally:
        await restarted_sessions.state.aclose()


@pytest.mark.asyncio
async def test_failed_append_keeps_merged_snapshot_evidence_but_not_closed_segment(history, tmp_path, monkeypatch):
    gateway, channel = _gateway(history, tmp_path, monkeypatch)
    ws = AsyncMock()
    channel._attach(ws, "failed")
    metadata = await history.metadata("failed", {WEBUI_TURN_METADATA_KEY: "turn-failed"})
    append = history.sessions.state.append_history
    count = 0

    async def fail_first(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            raise OSError("injected write failure")
        return await append(*args, **kwargs)

    monkeypatch.setattr(history.sessions.state, "append_history", fail_first)
    await channel.send_delta("failed", "first", metadata, stream_id="s")
    await channel.send_delta("failed", "", metadata, stream_id="s", stream_end=True, merge_next=True)
    assert history.read("websocket:failed") == []
    await channel.send_delta("failed", " second", metadata, stream_id="s")
    await channel.send_delta("failed", "", metadata, stream_id="s", stream_end=True)
    await channel.send_delta("failed", " fresh", metadata, stream_id="s")
    await channel.send_delta("failed", "", metadata, stream_id="s", stream_end=True)
    deltas = [frame for frame in _frames(ws) if frame["event"] == "delta"]
    rows = [event for event in (await _http_thread(gateway, "failed"))["events"] if event["event"] == "stream_end"]
    assert [row["text"] for row in rows] == ["first second", " fresh"]
    assert [row["projection_receipts"] for row in rows] == [
        [{"turn_id": "turn-failed", "ranges": [[deltas[0]["turn_seq"], deltas[0]["turn_seq"]],
                                                 [deltas[1]["turn_seq"], deltas[1]["turn_seq"]]]}],
        [{"turn_id": "turn-failed", "ranges": [[deltas[2]["turn_seq"], deltas[2]["turn_seq"]]]}],
    ]
    assert not gateway.transcripts._stream_receipts


@pytest.mark.asyncio
async def test_interleaved_turns_and_cancelled_fanout_do_not_reuse_stale_buffer(history, tmp_path, monkeypatch):
    gateway, channel = _gateway(history, tmp_path, monkeypatch)
    ws = AsyncMock()
    channel._attach(ws, "cross")
    first = await history.metadata("cross", {WEBUI_TURN_METADATA_KEY: "first"})
    second = {**first, WEBUI_TURN_METADATA_KEY: "second"}
    await channel.send_delta("cross", "A", first, stream_id="same")
    await channel.send_delta("cross", "B", second, stream_id="same")
    await channel.send_delta("cross", "", second, stream_id="same", stream_end=True)
    await channel.send_delta("cross", "", first, stream_id="same", stream_end=True)
    rows = history.read("websocket:cross")
    assert [(row["turn_id"], row["text"], row["_webui_projection_receipts"]) for row in rows] == [
        ("second", "B", [{"turn_id": "second", "ranges": [[1, 1]]}]),
        ("first", "A", [{"turn_id": "first", "ranges": [[1, 1]]}]),
    ]

    await channel.send_delta("cross", "old", first, stream_id="same")
    original = channel._outbound._fanout

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(channel._outbound, "_fanout", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await channel.send_delta("cross", "not delivered", first, stream_id="same")
    monkeypatch.setattr(channel._outbound, "_fanout", original)
    await channel.send_delta("cross", "new", first, stream_id="same")
    await channel.send_delta("cross", "", first, stream_id="same", stream_end=True)
    last = history.read("websocket:cross")[-1]
    new = [frame for frame in _frames(ws) if frame.get("text") == "new"][0]
    assert last["text"] == "new"
    assert last["_webui_projection_receipts"] == [
        {"turn_id": "first", "ranges": [[new["turn_seq"], new["turn_seq"]]]}
    ]
    await channel.send(OutboundMessage(channel="websocket", chat_id="cross", content="",
                                      event=TurnEndEvent(), metadata=first))
    assert not gateway.transcripts._stream_receipts
    assert not channel._outbound._stream_text_buffers


@pytest.mark.asyncio
async def test_range_budget_fails_closed_and_cleans_up_at_termination(history, tmp_path, monkeypatch):
    gateway, channel = _gateway(history, tmp_path, monkeypatch)
    ws = AsyncMock()
    channel._attach(ws, "budget")
    metadata = await history.metadata("budget", {WEBUI_TURN_METADATA_KEY: "budget-turn"})
    monkeypatch.setattr(transcript, "_MAX_STREAM_RECEIPT_RANGES", 2)
    for index in range(3):
        await channel.send_delta("budget", str(index), metadata, stream_id="s")
        if index < 2:
            await channel.send(OutboundMessage(channel="websocket", chat_id="budget", content="tool",
                                              event=ProgressEvent(content="tool"), metadata=metadata))
    await channel.send_delta("budget", "", metadata, stream_id="s", stream_end=True)
    row = history.read("websocket:budget")[-1]
    assert row["text"] == "012"
    seqs = [frame["turn_seq"] for frame in _frames(ws) if frame["event"] == "delta"]
    assert row["_webui_projection_receipts"] == [
        {"turn_id": "budget-turn", "ranges": [[seq, seq] for seq in seqs]},
    ]
    await channel.send(OutboundMessage(channel="websocket", chat_id="budget", content="",
                                      event=TurnEndEvent(), metadata=metadata))
    assert not gateway.transcripts._stream_receipts


@pytest.mark.asyncio
async def test_receipts_never_push_valid_eight_mib_fact_over_limit(history, tmp_path, monkeypatch):
    gateway, channel = _gateway(history, tmp_path, monkeypatch)
    ws = AsyncMock()
    channel._attach(ws, "limit")
    metadata = await history.metadata("limit", {WEBUI_TURN_METADATA_KEY: "limit-turn"})
    baseline = fact_from_record({"event": "stream_end", "stream_id": "s", "text": "",
                                 "turn_id": "limit-turn", "turn_phase": "answer", "turn_seq": 2,
                                 "created_at_ms": 1_700_000_000_000}).encode()
    text = "x" * (MAX_HISTORY_FACT_BYTES - len(baseline.encode("utf-8")))
    await channel.send_delta("limit", text, metadata, stream_id="s")
    await channel.send_delta("limit", "", metadata, stream_id="s", stream_end=True)
    facts = await history.sessions.state.project_history("websocket:limit", lambda reader: reader.all_facts())
    assert len(facts) == 1
    assert len(facts[0].encode().encode("utf-8")) == MAX_HISTORY_FACT_BYTES
    assert facts[0].content["text"] == text
    assert facts[0].content["_webui_projection_receipts"] == [
        {"turn_id": "limit-turn", "ranges": [[1, 1]]},
    ]
    assert not gateway.transcripts._stream_receipts


@pytest.mark.asyncio
async def test_temporary_chat_never_tracks_or_persists_receipts(history, tmp_path, monkeypatch):
    gateway, channel = _gateway(history, tmp_path, monkeypatch)
    owner = object()
    chat_id = await gateway.temporary_chats.create(owner, trusted_webui=True)
    ws = AsyncMock()
    channel._attach(ws, chat_id)
    metadata = await history.metadata(chat_id, {WEBUI_TURN_METADATA_KEY: "temporary"})
    append = AsyncMock(wraps=history.sessions.state.append_history)
    monkeypatch.setattr(history.sessions.state, "append_history", append)
    await channel.send_delta(chat_id, "private", metadata, stream_id="s")
    await channel.send_delta(chat_id, "", metadata, stream_id="s", stream_end=True)
    await channel.send(OutboundMessage(channel="websocket", chat_id=chat_id, content="",
                                      event=TurnEndEvent(), metadata=metadata))
    append.assert_not_awaited()
    assert not gateway.transcripts._stream_receipts
    assert not channel._outbound._stream_text_buffers
    gateway.temporary_chats.close()


@pytest.mark.asyncio
async def test_inflight_delta_receipt_matches_snapshot_even_if_one_recipient_misses_it(history, tmp_path, monkeypatch):
    gateway, channel = _gateway(history, tmp_path, monkeypatch)
    first, second = AsyncMock(), AsyncMock()
    channel._attach(first, "racing")
    channel._attach(second, "racing")
    metadata = await history.metadata("racing", {WEBUI_TURN_METADATA_KEY: "race-turn"})
    entered, release = asyncio.Event(), asyncio.Event()
    original = channel._outbound._fanout

    async def delayed(recipients, payload, *, label):
        if payload.get("event") == "delta" and payload.get("stream_id") == "primary":
            entered.set()
            await release.wait()
            await original((first,), payload, label=label)
        else:
            await original(recipients, payload, label=label)

    monkeypatch.setattr(channel._outbound, "_fanout", delayed)
    task = asyncio.create_task(channel.send_delta("racing", "part", metadata, stream_id="primary"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await channel.send_delta("racing", "other", metadata, stream_id="other")
        await channel.send_delta("racing", "", metadata, stream_id="primary", stream_end=True)
        end = history.read("websocket:racing")[-1]
        assert end["text"] == "part"
        assert end["_webui_projection_receipts"] == [{"turn_id": "race-turn", "ranges": [[1, 1]]}]
        payload = await _http_thread(gateway, "racing")
        snapshot = next(event for event in payload["events"] if event["event"] == "stream_end")
        assert snapshot["projection_receipts"] == end["_webui_projection_receipts"]
    finally:
        release.set()
        await task
    assert any(frame.get("text") == "part" and frame["turn_seq"] == 1 for frame in _frames(first))
    assert not any(frame.get("text") == "part" for frame in _frames(second))
    assert any(frame.get("text") == "other" and frame["turn_seq"] == 2 for frame in _frames(second))
