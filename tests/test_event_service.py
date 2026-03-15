"""Tests for the HTTP webhook EventService."""

import asyncio

import pytest

from nanobot.config.schema import EventEndpointConfig, EventsConfig
from nanobot.event.service import EventService


def _make_config(secret: str | None = "testsecret") -> EventsConfig:
    return EventsConfig(
        enabled=True,
        secret=secret,
        endpoints={
            "deploy": EventEndpointConfig(message="New deploy happened"),
        },
    )


def _find_free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _raw_http(port: int, method: str, path: str, headers: dict[str, str] | None = None, body: str = "") -> tuple[int, str]:
    """Send a raw HTTP request and return (status_code, response_body)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    body_bytes = body.encode("utf-8")
    header_lines = [f"{method} {path} HTTP/1.1", f"Host: 127.0.0.1:{port}", f"Content-Length: {len(body_bytes)}"]
    for k, v in (headers or {}).items():
        header_lines.append(f"{k}: {v}")
    raw = "\r\n".join(header_lines) + "\r\n\r\n"
    writer.write(raw.encode("utf-8") + body_bytes)
    await writer.drain()

    response = await asyncio.wait_for(reader.read(8192), timeout=5)
    writer.close()
    await writer.wait_closed()

    text = response.decode("utf-8", errors="replace")
    status_line, _, rest = text.partition("\r\n")
    status_code = int(status_line.split()[1])
    _, _, resp_body = rest.partition("\r\n\r\n")
    return status_code, resp_body


@pytest.fixture
async def event_service():
    """Start an EventService on a random port, yield (service, port), then stop."""
    port = _find_free_port()
    cfg = _make_config(secret="testsecret")
    svc = EventService(cfg, host="127.0.0.1", port=port)

    task = asyncio.create_task(svc.start())
    await asyncio.sleep(0.1)  # let server bind

    yield svc, port

    svc.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.fixture
async def event_service_no_auth():
    """EventService with no secret (auth disabled)."""
    port = _find_free_port()
    cfg = _make_config(secret=None)
    svc = EventService(cfg, host="127.0.0.1", port=port)

    task = asyncio.create_task(svc.start())
    await asyncio.sleep(0.1)

    yield svc, port

    svc.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_event_auth_ok(event_service):
    """POST with correct Bearer token returns 200."""
    svc, port = event_service
    called = []

    async def handler(name, endpoint, payload):
        called.append((name, payload))
        return "ok"

    svc.on_event = handler

    status, body = await _raw_http(
        port, "POST", "/event/deploy",
        headers={"Authorization": "Bearer testsecret"},
    )
    assert status == 200
    assert '"status":"ok"' in body.replace(" ", "")
    # Give the fire task a moment to complete
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_event_auth_fail(event_service):
    """POST with wrong Bearer token returns 401."""
    _, port = event_service

    status, body = await _raw_http(
        port, "POST", "/event/deploy",
        headers={"Authorization": "Bearer wrongtoken"},
    )
    assert status == 401
    assert "unauthorized" in body.lower()


@pytest.mark.asyncio
async def test_event_no_auth(event_service_no_auth):
    """When secret is None, POST without Authorization header returns 200."""
    svc, port = event_service_no_auth

    async def handler(name, endpoint, payload):
        return "ok"

    svc.on_event = handler

    status, body = await _raw_http(port, "POST", "/event/deploy")
    assert status == 200


@pytest.mark.asyncio
async def test_event_unknown_endpoint(event_service):
    """POST to an unknown event name returns 404."""
    _, port = event_service

    status, body = await _raw_http(
        port, "POST", "/event/unknown",
        headers={"Authorization": "Bearer testsecret"},
    )
    assert status == 404
    assert "unknown" in body.lower()


@pytest.mark.asyncio
async def test_event_method_not_allowed(event_service):
    """GET request returns 405."""
    _, port = event_service

    status, body = await _raw_http(
        port, "GET", "/event/deploy",
        headers={"Authorization": "Bearer testsecret"},
    )
    assert status == 405


@pytest.mark.asyncio
async def test_event_payload_passed(event_service):
    """Request body is passed to the callback as payload."""
    svc, port = event_service
    received: list[tuple[str, str]] = []

    async def handler(name, endpoint, payload):
        received.append((name, payload))
        return "ok"

    svc.on_event = handler

    payload_data = '{"version": "2.0", "branch": "main"}'
    status, _ = await _raw_http(
        port, "POST", "/event/deploy",
        headers={"Authorization": "Bearer testsecret", "Content-Type": "application/json"},
        body=payload_data,
    )
    assert status == 200
    await asyncio.sleep(0.1)

    assert len(received) == 1
    assert received[0][0] == "deploy"
    assert received[0][1] == payload_data


@pytest.mark.asyncio
async def test_event_empty_payload(event_service):
    """Empty body results in empty string payload."""
    svc, port = event_service
    received: list[tuple[str, str]] = []

    async def handler(name, endpoint, payload):
        received.append((name, payload))
        return "ok"

    svc.on_event = handler

    status, _ = await _raw_http(
        port, "POST", "/event/deploy",
        headers={"Authorization": "Bearer testsecret"},
        body="",
    )
    assert status == 200
    await asyncio.sleep(0.1)

    assert len(received) == 1
    assert received[0][1] == ""
