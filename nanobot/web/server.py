"""Minimal async HTTP server for ClawLink identity and health endpoints.

Uses only the Python standard library (asyncio) — no extra dependencies.

The ClawLink Protocol (https://github.com/SilverstreamsAI/ClawNexus) allows
discovery tools to identify running AI framework instances on the network.
Responding to ``/.well-known/claw-identity.json`` lets NanoBot be
auto-discovered by any ClawLink-compatible scanner (e.g. ClawNexus).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from nanobot import __version__

logger = logging.getLogger(__name__)

IDENTITY_PAYLOAD = json.dumps({
    "implementation": "nanobot",
    "version": __version__,
    "protocol": "clawlink/1.0",
}).encode()

HEALTH_PAYLOAD = json.dumps({
    "status": "ok",
    "framework": "nanobot",
    "version": __version__,
}).encode()

NOT_FOUND_PAYLOAD = json.dumps({"error": "Not Found"}).encode()


def _http_response(status: int, phrase: str, body: bytes) -> bytes:
    """Build a minimal HTTP/1.1 response."""
    return (
        f"HTTP/1.1 {status} {phrase}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode() + body


_ROUTES: dict[str, tuple[int, str, bytes]] = {
    "/.well-known/claw-identity.json": (200, "OK", IDENTITY_PAYLOAD),
    "/health": (200, "OK", HEALTH_PAYLOAD),
}


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Handle a single HTTP request."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not request_line:
            return

        parts = request_line.decode("utf-8", errors="replace").strip().split()
        method = parts[0] if parts else ""
        path = parts[1] if len(parts) > 1 else ""

        if method == "GET" and path in _ROUTES:
            status, phrase, body = _ROUTES[path]
            writer.write(_http_response(status, phrase, body))
        else:
            writer.write(_http_response(404, "Not Found", NOT_FOUND_PAYLOAD))

        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        writer.close()


async def start_http_server(
    host: str = "0.0.0.0",
    port: int = 18790,
) -> asyncio.Server | None:
    """Start the ClawLink identity HTTP server.

    Returns the server instance, or *None* if the port is unavailable.
    """
    try:
        server = await asyncio.start_server(_handle_client, host, port)
        logger.info("HTTP server listening on %s:%d", host, port)
        return server
    except OSError as exc:
        logger.warning(
            "Could not start HTTP server on %s:%d (%s) — skipping",
            host,
            port,
            exc,
        )
        return None
