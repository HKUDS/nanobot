"""Tests for the webhook channel."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.channels.webhook import EndpointConfig, WebhookChannel, WebhookConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_channel(
    endpoints: dict | None = None,
    secret: str | None = None,
) -> WebhookChannel:
    eps = endpoints or {
        "alert": EndpointConfig(prompt="Process alert: {payload}"),
        "ping": EndpointConfig(prompt="Ping received"),
    }
    cfg = WebhookConfig(
        enabled=True,
        host="127.0.0.1",
        port=0,  # OS picks free port
        secret=secret,
        allow_from=["*"],
        endpoints=eps,
    )
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    ch = WebhookChannel(cfg.model_dump(by_alias=True), bus)
    return ch


async def _start_channel(ch: WebhookChannel) -> int:
    """Start the channel in the background and return the listening port."""
    task = asyncio.create_task(ch.start())
    # Give the server time to bind
    await asyncio.sleep(0.05)
    assert ch._server is not None
    port = ch._server.sockets[0].getsockname()[1]
    return port


async def _http_request(
    port: int,
    method: str = "POST",
    path: str = "/event/alert",
    body: str = "",
    headers: dict | None = None,
) -> tuple[int, dict]:
    """Send a raw HTTP request and parse the JSON response."""
    hdrs = headers or {}
    hdrs.setdefault("Content-Length", str(len(body.encode())))
    header_lines = "\r\n".join(f"{k}: {v}" for k, v in hdrs.items())
    raw = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n{header_lines}\r\n\r\n{body}"

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(raw.encode())
    await writer.drain()

    data = await asyncio.wait_for(reader.read(4096), timeout=5)
    writer.close()
    await writer.wait_closed()

    text = data.decode()
    status_line = text.splitlines()[0]
    status_code = int(status_line.split()[1])
    json_start = text.index("{")
    resp_body = json.loads(text[json_start:])
    return status_code, resp_body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_from_dict():
    """Config is correctly parsed from a camelCase dict."""
    ch = _make_channel()
    assert ch.config.host == "127.0.0.1"
    assert "alert" in ch.config.endpoints
    assert ch.config.endpoints["alert"].prompt == "Process alert: {payload}"


@pytest.mark.asyncio
async def test_method_not_allowed():
    ch = _make_channel()
    port = await _start_channel(ch)
    try:
        status, body = await _http_request(port, method="GET", path="/event/alert")
        assert status == 405
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_unknown_endpoint():
    ch = _make_channel()
    port = await _start_channel(ch)
    try:
        status, body = await _http_request(port, path="/event/nonexistent")
        assert status == 404
        assert "unknown event" in body["error"]
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_auth_required():
    ch = _make_channel(secret="s3cret")
    port = await _start_channel(ch)
    try:
        # No token
        status, _ = await _http_request(port, path="/event/alert")
        assert status == 401

        # Wrong token
        status, _ = await _http_request(
            port, path="/event/alert", headers={"Authorization": "Bearer wrong"}
        )
        assert status == 401
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_auth_success():
    ch = _make_channel(secret="s3cret")
    port = await _start_channel(ch)
    try:
        status, body = await _http_request(
            port,
            path="/event/alert",
            body="test payload",
            headers={"Authorization": "Bearer s3cret"},
        )
        assert status == 200
        assert body["event"] == "alert"
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_event_publishes_to_bus():
    ch = _make_channel()
    port = await _start_channel(ch)
    try:
        status, body = await _http_request(
            port, path="/event/alert", body="server is down"
        )
        assert status == 200
        # Give the handler a moment to call _handle_message
        await asyncio.sleep(0.05)
        ch.bus.publish_inbound.assert_called_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.channel == "webhook"
        assert msg.chat_id == "alert"
        assert "server is down" in msg.content
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_payload_template():
    ch = _make_channel()
    port = await _start_channel(ch)
    try:
        status, _ = await _http_request(
            port, path="/event/alert", body="disk full"
        )
        assert status == 200
        await asyncio.sleep(0.05)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.content == "Process alert: disk full"
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_no_payload_uses_prompt_as_is():
    ch = _make_channel()
    port = await _start_channel(ch)
    try:
        status, _ = await _http_request(port, path="/event/ping", body="")
        assert status == 200
        await asyncio.sleep(0.05)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.content == "Ping received"
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_send_is_noop():
    """Outbound send() should not raise."""
    ch = _make_channel()
    await ch.send(MagicMock())
