import asyncio
import json
import threading
from pathlib import Path

import aiohttp
import pytest
from websockets.asyncio.client import connect

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import load_config
from nanobot.runtime_admission import RuntimeBusyError
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


@pytest.mark.parametrize("finish", [True, False], ids=["complete", "disconnect"])
async def test_streaming_upload_blocks_maintenance_until_written_or_cleaned(gateway, finish):
    channel, bus, http_url, ws_url = gateway
    port = int(http_url.rsplit(":", 1)[1])
    store = channel.gateway.uploads.store
    async with connect(ws_url) as ws:
        capability = (await event(ws, "ready"))["upload"]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write((
                f"POST {capability['path']} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                f"Authorization: Bearer {capability['token']}\r\n"
                "Content-Type: image/png\r\nContent-Length: 8\r\n\r\npart"
            ).encode())
            await writer.drain()
            async with asyncio.timeout(3):
                while store._active == 0:
                    await asyncio.sleep(.01)
            with pytest.raises(RuntimeBusyError):
                with bus.admission.pause_if_idle(lambda: False):
                    pytest.fail("Maintenance ignored an in-progress binary write")
            assert not bus.admission.paused
            if finish:
                writer.write(b"done")
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), timeout=3)
                assert response.startswith(b"HTTP/1.1 201"), response
            else:
                writer.close()
                await writer.wait_closed()
            async with asyncio.timeout(3):
                while store._active:
                    await asyncio.sleep(.01)
            with bus.admission.pause_if_idle(lambda: False):
                assert bus.admission.paused
            if not finish:
                assert not tuple(store._journal.iterdir())
        finally:
            writer.close()
            await writer.wait_closed()


async def test_threaded_settings_write_stays_busy_after_browser_disconnect(gateway, monkeypatch):
    channel, bus, _, ws_url = gateway
    entered, release = threading.Event(), threading.Event()
    settings = channel.gateway.settings
    original = settings.config.run_serialized

    def delayed_save(*args, **kwargs):
        entered.set()
        assert release.wait(10), "Test did not release the settings writer"
        return original(*args, **kwargs)

    monkeypatch.setattr(settings.config, "run_serialized", delayed_save)

    def connection_url():
        token = channel.gateway.tokens.issue_token(300, audience="webui")
        return ws_url.replace("test-secret", token)

    def request(identifier, value):
        return json.dumps({"type": "webui_request", "request_id": identifier,
                           "action": "settings.runtime_config.update",
                           "payload": {"values": {"agents.defaults.max_tool_iterations": value}}})

    try:
        async with connect(connection_url()) as ws:
            await event(ws, "ready")
            await ws.send(request("slow-write", 31))
            assert await asyncio.to_thread(entered.wait, 3)
            with pytest.raises(RuntimeBusyError):
                with bus.admission.pause_if_idle(lambda: False):
                    pytest.fail("Maintenance ignored a threaded settings write")
        # Existing mutation ownership deliberately survives a lost browser;
        # losing its delivery task must not make the gateway appear idle.
        with pytest.raises(RuntimeBusyError):
            with bus.admission.pause_if_idle(lambda: False):
                pytest.fail("Browser disconnect released an unfinished write")
        operation = channel._commands.request_operations["slow-write"].task
        release.set()
        result = await asyncio.wait_for(asyncio.shield(operation), timeout=5)
        assert result.status is None, result
        assert load_config(settings.config.path).agents.defaults.max_tool_iterations == 31
        async with connect(connection_url()) as ws:
            await event(ws, "ready")
            with bus.admission.pause_if_idle(lambda: False):
                await ws.send(request("blocked-write", 32))
                rejected = await event(ws, "webui_response")
                assert rejected["error"]["status"] == 503
                assert load_config(settings.config.path).agents.defaults.max_tool_iterations == 31
            await ws.send(request("after-abort", 33))
            assert (await event(ws, "webui_response"))["ok"] is True
            assert load_config(settings.config.path).agents.defaults.max_tool_iterations == 33
    finally:
        release.set()


async def test_http_route_is_busy_until_its_async_work_finishes(gateway, monkeypatch):
    channel, bus, http_url, _ = gateway
    entered, release = asyncio.Event(), asyncio.Event()
    route = channel.gateway.http._dispatch_resolved

    async def delayed_route(*args, **kwargs):
        entered.set()
        await release.wait()
        return await route(*args, **kwargs)

    monkeypatch.setattr(channel.gateway.http, "_dispatch_resolved", delayed_route)
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer test-secret"}) as http:
        request = asyncio.create_task(http.get(http_url + "/webui/bootstrap"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            with pytest.raises(RuntimeBusyError):
                with bus.admission.pause_if_idle(lambda: False):
                    pytest.fail("Maintenance ignored a running HTTP handler")
            release.set()
            async with await asyncio.wait_for(request, timeout=3) as response:
                assert response.status == 200
                await response.read()
            with bus.admission.pause_if_idle(lambda: False):
                async with http.get(http_url + "/webui/bootstrap") as response:
                    assert response.status == 503
            async with http.get(http_url + "/webui/bootstrap") as response:
                assert response.status == 200
        finally:
            release.set()
            await asyncio.gather(request, return_exceptions=True)


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


async def test_stalled_upload_reports_timeout_and_keeps_connection_retryable(gateway):
    channel, _, http_url, ws_url = gateway
    channel.gateway.uploads.store.upload_idle_timeout = .05

    async def stalled():
        yield b"x"
        await asyncio.sleep(.15)
        yield b"y"

    async with connect(ws_url) as ws, aiohttp.ClientSession() as http:
        capability = (await event(ws, "ready"))["upload"]
        headers = {"Authorization": f"Bearer {capability['token']}",
                   "Content-Type": "image/png", "Content-Length": "2"}
        async with http.post(http_url + capability["path"], data=stalled(), headers=headers) as response:
            assert response.status == 400
            assert (await response.json())["error"] == "Attachment upload timed out"
        assert not [p for p in channel.gateway.uploads.store.media_dir.rglob("*") if p.is_file()]
        async with http.post(http_url + capability["path"], data=b"xy", headers=headers) as response:
            assert response.status == 201


async def test_stopping_listener_cancels_active_upload_before_clearing_store(gateway):
    channel, _, http_url, ws_url = gateway
    port = int(http_url.rsplit(":", 1)[1])
    async with connect(ws_url) as ws:
        capability = (await event(ws, "ready"))["upload"]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write((
                f"POST {capability['path']} HTTP/1.1\r\nHost: localhost\r\n"
                f"Authorization: Bearer {capability['token']}\r\n"
                "Content-Type: image/png\r\nContent-Length: 1024\r\n"
                "Expect: 100-continue\r\n\r\n"
            ).encode("ascii"))
            await writer.drain()
            assert b"100 Continue" in await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 2)
            writer.write(b"partial")
            await writer.drain()
            async with asyncio.timeout(3):
                await channel.stop()
                await reader.read()
                await ws.wait_closed()
            assert not [p for p in channel.gateway.uploads.store.media_dir.rglob("*") if p.is_file()]
        finally:
            writer.close()
            await writer.wait_closed()
