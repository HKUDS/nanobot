"""Lightweight health-check HTTP server for the gateway command.

The gateway doesn't run FastAPI — it uses an async message bus.  This module
provides a minimal ``aiohttp``-free health endpoint using only the stdlib
``asyncio`` module so Docker HEALTHCHECK and orchestrators can verify liveness.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

_CONTENT_TYPE = "application/json"


async def start_health_server(
    agent_loop: Any,
    *,
    host: str = "0.0.0.0",
    port: int = 18790,
) -> asyncio.Server:
    """Start a tiny HTTP server that responds to ``GET /health`` and ``GET /ready``.

    Returns the ``asyncio.Server`` so the caller can close it on shutdown.
    """

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            parts = request_line.decode("utf-8", errors="replace").strip().split()
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) > 1 else ""

            # Drain remaining headers (we don't need them)
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                if line in (b"\r\n", b"\n", b""):
                    break

            if method != "GET" or path not in ("/health", "/ready"):
                body = json.dumps({"error": "not found"})
                status = "404 Not Found"
            elif path == "/health":
                body = json.dumps({"status": "ok"})
                status = "200 OK"
            else:  # /ready
                running = getattr(agent_loop, "_running", False) if agent_loop else False
                if running:
                    body = json.dumps({"status": "ready"})
                    status = "200 OK"
                else:
                    body = json.dumps({"status": "not_ready"})
                    status = "503 Service Unavailable"

            response = (
                f"HTTP/1.1 {status}\r\n"
                f"Content-Type: {_CONTENT_TYPE}\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n"
                "\r\n"
                f"{body}"
            )
            writer.write(response.encode())
            await writer.drain()
        except Exception:  # crash-barrier: health server must not crash the gateway
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(_handle, host, port)
    logger.info("Health server listening on {}:{}", host, port)
    return server
