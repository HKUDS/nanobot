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
from nanobot.session.manager import SessionManager
from nanobot.webui import transcript
from nanobot.webui.gateway_services import build_gateway_services
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


async def _http_thread(gateway, chat_id, query=""):
    gateway.tokens.api_tokens["test-token"] = time.monotonic() + 60
    headers = Headers([("Authorization", "Bearer test-token")])
    path = f"/api/sessions/websocket%3A{chat_id}/webui-thread"
    response = await gateway.http._dispatch_session_routes(Request(path + query, headers), path)
    assert response.status_code == 200
    return json.loads(response.body)


def _frames(ws):
    return [json.loads(call.args[0]) for call in ws.send.await_args_list]


def _stored_records(sessions):
    with closing(sqlite3.connect(sessions.sessions_dir / "sessions.sqlite3")) as db:
        return db.execute("SELECT session_key, turn_ordinal, position, record FROM history_entries ORDER BY session_key, turn_ordinal, position").fetchall()


@pytest.mark.asyncio
async def test_signed_snapshots_survive_http_pagination_and_restart_without_rewriting_history(history, tmp_path, monkeypatch):
    (tmp_path / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
    gateway, channel = _gateway(history, tmp_path, monkeypatch)
    ws = AsyncMock()
    channel._attach(ws, "snapshots")
    metadata = await history.metadata("snapshots", {WEBUI_TURN_METADATA_KEY: "turn-one"})

    async def delta(text, stream="primary", **kwargs):
        await channel.send_delta("snapshots", text, metadata, stream_id=stream, **kwargs)

    await gateway.transcripts.append_user_message("snapshots", "draw it", metadata=metadata)
    await delta("![plot](diagram")
    await channel.send(OutboundMessage(channel="websocket", chat_id="snapshots", content="tool()",
                                      event=ProgressEvent(content="tool()"), metadata=metadata))
    await channel.send_reasoning_delta("snapshots", "thinking", metadata, stream_id="primary")
    await delta(".png)")
    await delta("unrelated", stream="other")
    await delta("", stream_end=True, resuming=True, merge_next=True)
    await delta(" more")
    await delta("", stream_end=True)
    await channel.send_reasoning_end("snapshots", metadata, stream_id="primary")
    await delta("", stream="other", stream_end=True)
    await channel.send(OutboundMessage(channel="websocket", chat_id="snapshots", content="",
                                      event=TurnEndEvent(), metadata=metadata))

    live = _frames(ws)
    frames = [frame for frame in live if frame["event"] == "delta"]
    first, second, _ = [frame for frame in live if frame["event"] == "stream_end"]
    assert "diagram.png" in "".join(frame["text"] for frame in frames)
    assert "/api/media/" in first["text"] and second["text"] == first["text"] + " more"
    stored = history.read("websocket:snapshots")
    ends = [row for row in stored if row["event"] == "stream_end"]
    assert [row["text"] for row in ends] == [first["text"], second["text"], "unrelated"]
    reasoning = next(row for row in stored if row["event"] == "reasoning_end")
    assert reasoning["text"] == "thinking"
    assert [row["text_from_seq"] for row in ends] == [frames[0]["turn_seq"], frames[0]["turn_seq"], frames[2]["turn_seq"]]
    assert reasoning["text_from_seq"] == next(frame["turn_seq"] for frame in live if frame["event"] == "reasoning_delta")
    assert all(row["event"] not in {"delta", "reasoning_delta"} for row in stored)
    records = _stored_records(history.sessions)
    assert "diagram.png" not in json.dumps(records)
    complete = await _http_thread(gateway, "snapshots")
    projected = [event for event in complete["events"] if event["event"] == "stream_end"]
    assert [(event["stream_id"], event["turn_seq"], event["text"]) for event in projected] == [
        (row["stream_id"], row["turn_seq"], row["text"]) for row in ends
    ]
    signed_url = first["text"].split("(", 1)[1].split(")", 1)[0]
    _, _, _, signature, signed_payload = signed_url.split("/")
    assert gateway.media.serve_signed_media(signature, signed_payload).status_code == 200

    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 2)

    async def all_pages(owner):
        pages = [await _http_thread(owner, "snapshots")]
        while pages[-1]["page"]["has_more_before"]:
            pages.append(await _http_thread(owner, "snapshots", "?before=" + pages[-1]["page"]["before_cursor"]))
            assert len(pages) <= len(stored)
        pages.reverse()
        ranges = [page["page"]["record_range"] for page in pages]
        assert ranges[0]["start"] == 0 and ranges[-1]["end"] == len(stored)
        assert all(left["end"] == right["start"] for left, right in zip(ranges, ranges[1:]))
        assert [event for page in pages for event in page["events"]] == complete["events"]
        assert pages[-1]["completed_turn_ids"] == ["turn-one"]
        return pages

    pages = await all_pages(gateway)
    assert _stored_records(history.sessions) == records
    await history.sessions.state.aclose()
    restarted_sessions = SessionManager(tmp_path)
    try:
        restarted, _ = _gateway(SimpleNamespace(sessions=restarted_sessions), tmp_path, monkeypatch)
        restarted_pages = await all_pages(restarted)
        assert [page["page"] for page in restarted_pages] == [page["page"] for page in pages]
        assert _stored_records(restarted_sessions) == records
    finally:
        await restarted_sessions.state.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("reasoning", [False, True])
async def test_snapshot_coverage_follows_buffer_resets_after_a_failed_append(history, tmp_path, monkeypatch, reasoning):
    gateway, channel = _gateway(history, tmp_path, monkeypatch)
    ws = AsyncMock()
    channel._attach(ws, "reset")
    metadata = await history.metadata("reset", {WEBUI_TURN_METADATA_KEY: "turn-reset"})

    async def chunk(text):
        if reasoning:
            await channel.send_reasoning_delta("reset", text, metadata)
        else:
            await channel.send_delta("reset", text, metadata)

    async def end():
        if reasoning:
            await channel.send_reasoning_end("reset", metadata)
        else:
            await channel.send_delta("reset", "", metadata, stream_end=True)

    await chunk("not persisted")
    with monkeypatch.context() as patch:
        patch.setattr(gateway.transcripts, "append", AsyncMock(return_value=False))
        await end()
    await chunk("next buffer")
    await end()
    frames = _frames(ws)
    snapshot = history.read("websocket:reset")[0]
    assert snapshot["text"] == "next buffer"
    assert snapshot["text_from_seq"] == frames[2]["turn_seq"] > frames[1]["turn_seq"]
    assert frames[3]["text_from_seq"] == snapshot["text_from_seq"]
