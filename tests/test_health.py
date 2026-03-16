"""Tests for health check endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Web app health endpoints (FastAPI)
# ---------------------------------------------------------------------------


def _make_app(*, running: bool = True):
    """Create a minimal FastAPI app with health routes."""
    from nanobot.web.app import create_app

    agent_loop = MagicMock()
    agent_loop._running = running
    session_manager = MagicMock()
    web_channel = MagicMock()
    return create_app(agent_loop, session_manager, web_channel)


class TestWebHealthEndpoints:
    """Health endpoints on the FastAPI web app."""

    def test_health_returns_ok(self) -> None:
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_ready_when_running(self) -> None:
        app = _make_app(running=True)
        client = TestClient(app)
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}

    def test_ready_when_not_running(self) -> None:
        app = _make_app(running=False)
        client = TestClient(app)
        resp = client.get("/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "not_ready"


# ---------------------------------------------------------------------------
# Gateway health server (stdlib asyncio TCP)
# ---------------------------------------------------------------------------


async def _query_health_server(port: int, path: str) -> tuple[int, dict]:
    """Open a raw TCP connection to the health server and return (status, body)."""
    import json

    reader, writer = await __import__("asyncio").open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    await writer.drain()
    data = await reader.read(4096)
    writer.close()
    text = data.decode()
    status_line = text.split("\r\n")[0]
    status_code = int(status_line.split(" ", 2)[1])
    body = text.split("\r\n\r\n", 1)[1]
    return status_code, json.loads(body)


class TestGatewayHealthServer:
    """Lightweight health server for the gateway command."""

    async def test_health_returns_ok(self, unused_tcp_port: int) -> None:
        from nanobot.web.health import start_health_server

        agent = SimpleNamespace(_running=True)
        server = await start_health_server(agent, host="127.0.0.1", port=unused_tcp_port)
        try:
            code, body = await _query_health_server(unused_tcp_port, "/health")
            assert code == 200
            assert body == {"status": "ok"}
        finally:
            server.close()
            await server.wait_closed()

    async def test_ready_when_running(self, unused_tcp_port: int) -> None:
        from nanobot.web.health import start_health_server

        agent = SimpleNamespace(_running=True)
        server = await start_health_server(agent, host="127.0.0.1", port=unused_tcp_port)
        try:
            code, body = await _query_health_server(unused_tcp_port, "/ready")
            assert code == 200
            assert body == {"status": "ready"}
        finally:
            server.close()
            await server.wait_closed()

    async def test_ready_when_not_running(self, unused_tcp_port: int) -> None:
        from nanobot.web.health import start_health_server

        agent = SimpleNamespace(_running=False)
        server = await start_health_server(agent, host="127.0.0.1", port=unused_tcp_port)
        try:
            code, body = await _query_health_server(unused_tcp_port, "/ready")
            assert code == 503
            assert body["status"] == "not_ready"
        finally:
            server.close()
            await server.wait_closed()

    async def test_unknown_path_returns_404(self, unused_tcp_port: int) -> None:
        from nanobot.web.health import start_health_server

        agent = SimpleNamespace(_running=True)
        server = await start_health_server(agent, host="127.0.0.1", port=unused_tcp_port)
        try:
            code, body = await _query_health_server(unused_tcp_port, "/unknown")
            assert code == 404
        finally:
            server.close()
            await server.wait_closed()


@pytest.fixture()
def unused_tcp_port() -> int:
    """Find an available TCP port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
