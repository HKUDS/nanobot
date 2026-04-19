"""Integration tests for the WebSocket channel using WsTestClient.

Complements the unit/lightweight tests in test_websocket_channel.py by covering
multi-client scenarios, edge cases, and realistic usage patterns.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import websockets

from nanobot.channels.websocket import WebSocketChannel
from nanobot.bus.events import OutboundMessage
from ws_test_client import WsTestClient, issue_token, issue_token_ok


def _ch(bus: Any, port: int, **kw: Any) -> WebSocketChannel:
    cfg: dict[str, Any] = {
        "enabled": True,
        "allowFrom": ["*"],
        "host": "127.0.0.1",
        "port": port,
        "path": "/",
        "websocketRequiresToken": False,
    }
    cfg.update(kw)
    return WebSocketChannel(cfg, bus)


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


# -- Connection basics ----------------------------------------------------


@pytest.mark.asyncio
async def test_ready_event_fields(bus: MagicMock) -> None:
    ch = _ch(bus, 29901)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29901/", client_id="c1") as c:
            r = await c.recv_ready()
            assert r.event == "ready"
            assert len(r.chat_id) == 36
            assert r.client_id == "c1"
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_anonymous_client_gets_generated_id(bus: MagicMock) -> None:
    ch = _ch(bus, 29902)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29902/", client_id="") as c:
            r = await c.recv_ready()
            assert r.client_id.startswith("anon-")
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_each_connection_unique_chat_id(bus: MagicMock) -> None:
    ch = _ch(bus, 29903)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29903/", client_id="a") as c1:
            async with WsTestClient("ws://127.0.0.1:29903/", client_id="b") as c2:
                assert (await c1.recv_ready()).chat_id != (await c2.recv_ready()).chat_id
    finally:
        await ch.stop(); await t


# -- Inbound messages (client -> server) ----------------------------------


@pytest.mark.asyncio
async def test_plain_text(bus: MagicMock) -> None:
    ch = _ch(bus, 29904)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29904/", client_id="p") as c:
            await c.recv_ready()
            await c.send_text("hello world")
            await asyncio.sleep(0.1)
            inbound = bus.publish_inbound.call_args[0][0]
            assert inbound.content == "hello world"
            assert inbound.sender_id == "p"
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_json_content_field(bus: MagicMock) -> None:
    ch = _ch(bus, 29905)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29905/", client_id="j") as c:
            await c.recv_ready()
            await c.send_json({"content": "structured"})
            await asyncio.sleep(0.1)
            assert bus.publish_inbound.call_args[0][0].content == "structured"
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_json_text_and_message_fields(bus: MagicMock) -> None:
    ch = _ch(bus, 29906)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29906/", client_id="x") as c:
            await c.recv_ready()
            await c.send_json({"text": "via text"})
            await asyncio.sleep(0.1)
            assert bus.publish_inbound.call_args[0][0].content == "via text"
            await c.send_json({"message": "via message"})
            await asyncio.sleep(0.1)
            assert bus.publish_inbound.call_args[0][0].content == "via message"
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_empty_payload_ignored(bus: MagicMock) -> None:
    ch = _ch(bus, 29907)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29907/", client_id="e") as c:
            await c.recv_ready()
            await c.send_text("   ")
            await c.send_json({})
            await asyncio.sleep(0.1)
            bus.publish_inbound.assert_not_awaited()
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_messages_preserve_order(bus: MagicMock) -> None:
    ch = _ch(bus, 29908)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29908/", client_id="o") as c:
            await c.recv_ready()
            for i in range(5):
                await c.send_text(f"msg-{i}")
            await asyncio.sleep(0.2)
            contents = [call[0][0].content for call in bus.publish_inbound.call_args_list]
            assert contents == [f"msg-{i}" for i in range(5)]
    finally:
        await ch.stop(); await t


# -- Outbound messages (server -> client) ---------------------------------


@pytest.mark.asyncio
async def test_server_send_message(bus: MagicMock) -> None:
    ch = _ch(bus, 29909)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29909/", client_id="r") as c:
            ready = await c.recv_ready()
            await ch.send(OutboundMessage(
                channel="websocket", chat_id=ready.chat_id, content="reply",
            ))
            msg = await c.recv_message()
            assert msg.text == "reply"
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_server_send_with_media_and_reply(bus: MagicMock) -> None:
    ch = _ch(bus, 29910)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29910/", client_id="m") as c:
            ready = await c.recv_ready()
            await ch.send(OutboundMessage(
                channel="websocket", chat_id=ready.chat_id, content="img",
                media=["/tmp/a.png"], reply_to="m1",
            ))
            msg = await c.recv_message()
            assert msg.text == "img"
            assert msg.media == ["/tmp/a.png"]
            assert msg.reply_to == "m1"
    finally:
        await ch.stop(); await t


# -- Streaming ------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_deltas_and_end(bus: MagicMock) -> None:
    ch = _ch(bus, 29911, streaming=True)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29911/", client_id="s") as c:
            cid = (await c.recv_ready()).chat_id
            for part in ("Hello", " ", "world", "!"):
                await ch.send_delta(cid, part, {"_stream_delta": True, "_stream_id": "s1"})
            await ch.send_delta(cid, "", {"_stream_end": True, "_stream_id": "s1"})

            msgs = await c.collect_stream()
            deltas = [m for m in msgs if m.event == "delta"]
            assert "".join(d.text for d in deltas) == "Hello world!"
            ends = [m for m in msgs if m.event == "stream_end"]
            assert len(ends) == 1
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_interleaved_streams(bus: MagicMock) -> None:
    ch = _ch(bus, 29912, streaming=True)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29912/", client_id="i") as c:
            cid = (await c.recv_ready()).chat_id
            await ch.send_delta(cid, "A1", {"_stream_delta": True, "_stream_id": "sa"})
            await ch.send_delta(cid, "B1", {"_stream_delta": True, "_stream_id": "sb"})
            await ch.send_delta(cid, "A2", {"_stream_delta": True, "_stream_id": "sa"})
            await ch.send_delta(cid, "", {"_stream_end": True, "_stream_id": "sa"})
            await ch.send_delta(cid, "B2", {"_stream_delta": True, "_stream_id": "sb"})
            await ch.send_delta(cid, "", {"_stream_end": True, "_stream_id": "sb"})

            msgs = await c.recv_n(6)
            sa = "".join(m.text for m in msgs if m.event == "delta" and m.stream_id == "sa")
            sb = "".join(m.text for m in msgs if m.event == "delta" and m.stream_id == "sb")
            assert sa == "A1A2"
            assert sb == "B1B2"
    finally:
        await ch.stop(); await t


# -- Multi-client ---------------------------------------------------------


@pytest.mark.asyncio
async def test_independent_sessions(bus: MagicMock) -> None:
    ch = _ch(bus, 29913)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29913/", client_id="u1") as c1:
            async with WsTestClient("ws://127.0.0.1:29913/", client_id="u2") as c2:
                r1, r2 = await c1.recv_ready(), await c2.recv_ready()
                await ch.send(OutboundMessage(
                    channel="websocket", chat_id=r1.chat_id, content="for-u1",
                ))
                assert (await c1.recv_message()).text == "for-u1"
                await ch.send(OutboundMessage(
                    channel="websocket", chat_id=r2.chat_id, content="for-u2",
                ))
                assert (await c2.recv_message()).text == "for-u2"
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_disconnected_client_cleanup(bus: MagicMock) -> None:
    ch = _ch(bus, 29914)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29914/", client_id="tmp") as c:
            chat_id = (await c.recv_ready()).chat_id
        # disconnected
        await asyncio.sleep(0.1)
        await ch.send(OutboundMessage(
            channel="websocket", chat_id=chat_id, content="orphan",
        ))
        assert chat_id not in ch._subs
    finally:
        await ch.stop(); await t


# -- Authentication -------------------------------------------------------


@pytest.mark.asyncio
async def test_static_token_accepted(bus: MagicMock) -> None:
    ch = _ch(bus, 29915, token="secret")
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29915/", client_id="a", token="secret") as c:
            assert (await c.recv_ready()).client_id == "a"
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_static_token_rejected(bus: MagicMock) -> None:
    ch = _ch(bus, 29916, token="correct")
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc:
            async with WsTestClient("ws://127.0.0.1:29916/", client_id="b", token="wrong"):
                pass
        assert exc.value.response.status_code == 401
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_token_issue_full_flow(bus: MagicMock) -> None:
    ch = _ch(bus, 29917, path="/ws",
             tokenIssuePath="/auth/token", tokenIssueSecret="s",
             websocketRequiresToken=True)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        # no secret -> 401
        _, status = await issue_token(port=29917, issue_path="/auth/token")
        assert status == 401

        # with secret -> token
        token = await issue_token_ok(port=29917, issue_path="/auth/token", secret="s")

        # no token -> 401
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc:
            async with WsTestClient("ws://127.0.0.1:29917/ws", client_id="x"):
                pass
        assert exc.value.response.status_code == 401

        # valid token -> ok
        async with WsTestClient("ws://127.0.0.1:29917/ws", client_id="ok", token=token) as c:
            assert (await c.recv_ready()).client_id == "ok"

        # reuse -> 401
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc:
            async with WsTestClient("ws://127.0.0.1:29917/ws", client_id="r", token=token):
                pass
        assert exc.value.response.status_code == 401
    finally:
        await ch.stop(); await t


# -- Path routing ---------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_path(bus: MagicMock) -> None:
    ch = _ch(bus, 29918, path="/my-chat")
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29918/my-chat", client_id="p") as c:
            assert (await c.recv_ready()).event == "ready"
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_wrong_path_404(bus: MagicMock) -> None:
    ch = _ch(bus, 29919, path="/ws")
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc:
            async with WsTestClient("ws://127.0.0.1:29919/wrong", client_id="x"):
                pass
        assert exc.value.response.status_code == 404
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_trailing_slash_normalized(bus: MagicMock) -> None:
    ch = _ch(bus, 29920, path="/ws")
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29920/ws/", client_id="s") as c:
            assert (await c.recv_ready()).event == "ready"
    finally:
        await ch.stop(); await t


# -- Edge cases -----------------------------------------------------------


@pytest.mark.asyncio
async def test_large_message(bus: MagicMock) -> None:
    ch = _ch(bus, 29921)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29921/", client_id="big") as c:
            await c.recv_ready()
            big = "x" * 100_000
            await c.send_text(big)
            await asyncio.sleep(0.2)
            assert bus.publish_inbound.call_args[0][0].content == big
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_unicode_roundtrip(bus: MagicMock) -> None:
    ch = _ch(bus, 29922)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29922/", client_id="u") as c:
            ready = await c.recv_ready()
            text = "你好世界 🌍 日本語テスト"
            await c.send_text(text)
            await asyncio.sleep(0.1)
            assert bus.publish_inbound.call_args[0][0].content == text
            await ch.send(OutboundMessage(
                channel="websocket", chat_id=ready.chat_id, content=text,
            ))
            assert (await c.recv_message()).text == text
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_rapid_fire(bus: MagicMock) -> None:
    ch = _ch(bus, 29923)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29923/", client_id="r") as c:
            ready = await c.recv_ready()
            for i in range(50):
                await c.send_text(f"in-{i}")
            await asyncio.sleep(0.5)
            assert bus.publish_inbound.await_count == 50
            for i in range(50):
                await ch.send(OutboundMessage(
                    channel="websocket", chat_id=ready.chat_id, content=f"out-{i}",
                ))
            received = [(await c.recv_message()).text for _ in range(50)]
            assert received == [f"out-{i}" for i in range(50)]
    finally:
        await ch.stop(); await t


@pytest.mark.asyncio
async def test_invalid_json_as_plain_text(bus: MagicMock) -> None:
    ch = _ch(bus, 29924)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29924/", client_id="j") as c:
            await c.recv_ready()
            await c.send_text("{broken json")
            await asyncio.sleep(0.1)
            assert bus.publish_inbound.call_args[0][0].content == "{broken json"
    finally:
        await ch.stop(); await t
