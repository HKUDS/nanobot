"""Production listener regressions for HTTP upload + small WS references."""
import asyncio
import json
from pathlib import Path

import aiohttp
import pytest
from websockets.asyncio.client import connect

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import build_gateway_services


@pytest.fixture
async def gateway(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    bus = MessageBus()
    config = WebSocketConfig(port=0, path="/ws", token="test-secret", max_message_bytes=1048576)
    services = build_gateway_services(
        config=config, bus=bus, session_manager=SessionManager(tmp_path),
        static_dist_path=None, workspace_path=tmp_path,
        default_restrict_to_workspace=True, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
        config_path=tmp_path / "config.json",
    )
    channel = WebSocketChannel(config, bus, gateway=services)
    task = asyncio.create_task(channel.start())
    try:
        async with asyncio.timeout(10):
            while channel._server is None:
                if task.done():
                    await task
                await asyncio.sleep(.01)
        port = channel._server.sockets[0].getsockname()[1]
        yield channel, bus, f"http://127.0.0.1:{port}", f"ws://127.0.0.1:{port}/ws?token=test-secret"
    finally:
        await channel.stop()
        await task


async def event(ws, name):
    async with asyncio.timeout(5):
        while True:
            payload = json.loads(await ws.recv())
            if payload["event"] == name:
                return payload


@pytest.mark.parametrize("mime,name", [
    ("image/png", "image.png"), ("text/csv", "report.csv"), ("video/webm", "clip.webm"),
])
async def test_real_listener_large_binary_and_reference_delivery(gateway, mime, name):
    channel, bus, http_url, ws_url = gateway
    raw = b"x" * 1_453_245
    async with connect(ws_url) as ws, aiohttp.ClientSession() as http:
        ready = await event(ws, "ready")
        capability = ready["upload"]
        headers = {"Authorization": f"Bearer {capability['token']}", "Content-Type": mime,
                   "X-Attachment-Name": name}
        async with http.post(http_url + capability["path"], data=raw, headers=headers, expect100=True) as response:
            assert response.status == 201, await response.text()
            reference = (await response.json())["reference"]
        frame = {"type": "message", "chat_id": ready["chat_id"], "content": "look",
                 "webui": True, "turn_id": "binary-turn",
                 "media": [{"reference": reference, "name": name}]}
        assert len(json.dumps(frame)) < 1024
        await ws.send(json.dumps(frame))
        assert (await event(ws, "message_accepted"))["turn_id"] == "binary-turn"
        inbound = await asyncio.wait_for(bus.consume_inbound(), 2)
        path = Path(inbound.media[0])
        assert path.read_bytes() == raw
        assert path.parent == channel.gateway.uploads.store.media_dir
        # Lost ACK retry must not resolve a consumed reference or dispatch twice.
        await ws.send(json.dumps(frame))
        await event(ws, "message_accepted")
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(bus.consume_inbound(), .03)
        channel.gateway.uploads.store.clear()
        assert path.exists()


async def test_capability_is_required_owner_scoped_and_revoked(gateway):
    channel, _, http_url, ws_url = gateway
    async with aiohttp.ClientSession() as http:
        for token in ("", "test-secret", "client-selected-id"):
            async with http.post(http_url + "/api/attachments", data=b"secret",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"}) as response:
                assert response.status == 401
        async with connect(ws_url) as owner, connect(ws_url) as other:
            capability = (await event(owner, "ready"))["upload"]
            other_ready = await event(other, "ready")
            headers = {"Authorization": f"Bearer {capability['token']}", "Content-Type": "image/png"}
            async with http.post(http_url + capability["path"], data=b"image", headers=headers) as response:
                reference = (await response.json())["reference"]
            await other.send(json.dumps({"type": "message", "chat_id": other_ready["chat_id"],
                "content": "steal", "media": [{"reference": reference}], "turn_id": "foreign"}))
            assert (await event(other, "error"))["detail"] == "attachment_rejected"
        async with asyncio.timeout(5):
            while capability["token"] in channel.gateway.uploads._tokens:
                await asyncio.sleep(.01)
        async with http.post(http_url + capability["path"], data=b"image", headers=headers) as response:
            assert response.status == 401


async def test_inline_payload_rejected_and_failed_validation_keeps_upload(gateway):
    channel, bus, http_url, ws_url = gateway
    async with connect(ws_url) as ws, aiohttp.ClientSession() as http:
        ready = await event(ws, "ready")
        capability = ready["upload"]
        frame = {"type": "message", "chat_id": ready["chat_id"], "content": "look",
                 "webui": True, "turn_id": "retry-turn", "media": [{"data_url": "data:image/png;base64,eA=="}]}
        await ws.send(json.dumps(frame))
        assert (await event(ws, "error"))["detail"] == "attachment_rejected"
        headers = {"Authorization": f"Bearer {capability['token']}", "Content-Type": "image/png"}
        async with http.post(http_url + capability["path"], data=b"image", headers=headers) as response:
            reference = (await response.json())["reference"]
        frame["media"] = [{"reference": reference}, {"reference": "invalid"}]
        await ws.send(json.dumps(frame))
        await event(ws, "error")
        frame["media"] = [{"reference": reference}]
        await ws.send(json.dumps(frame))
        await event(ws, "message_accepted")
        assert (await bus.consume_inbound()).media



@pytest.mark.parametrize("mime,body", [
    ("image/svg+xml", b"<svg/>"), ("text/javascript", b"alert(1)"),
    ("image/png", b""), ("image/png", b"x" * (6 * 1024 * 1024 + 1)),
], ids=["svg", "javascript", "empty", "oversized"])
async def test_http_policy_rejection_does_not_leave_files(gateway, mime, body):
    channel, _, http_url, ws_url = gateway
    async with connect(ws_url) as ws, aiohttp.ClientSession() as http:
        capability = (await event(ws, "ready"))["upload"]
        async with http.post(http_url + capability["path"], data=body,
            headers={"Authorization": f"Bearer {capability['token']}", "Content-Type": mime},
            expect100=True,
        ) as response:
            assert response.status == 400
        assert not [p for p in channel.gateway.uploads.store.media_dir.rglob("*") if p.is_file()]


async def test_one_shot_handshake_token_is_not_an_upload_credential(gateway):
    channel, _, http_url, _ = gateway
    # Use the same one-shot token registry as the bootstrap endpoint.
    issued = channel.gateway.tokens.issue_token(60, audience="webui")
    ws_url = http_url.replace("http://", "ws://") + "/ws?token=" + issued
    async with connect(ws_url) as ws, aiohttp.ClientSession() as http:
        capability = (await event(ws, "ready"))["upload"]
        assert issued not in channel.gateway.tokens.issued_tokens
        for token, expected in [(issued, 401), (capability["token"], 201)]:
            async with http.post(http_url + capability["path"], data=b"binary",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "image/png"},
            ) as response:
                assert response.status == expected
