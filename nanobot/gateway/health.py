"""Serve the local Gateway readiness endpoint used by launchers and updates."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, cast

from loguru import logger

if TYPE_CHECKING:
    from nanobot.channels.manager import ChannelManager
    from nanobot.gateway.runtime import GatewayHealthIdentity
    from nanobot.runtime_admission import RuntimeAdmission

_MAX_CONNECTIONS = 64
_READ_TIMEOUT_SECONDS = 2.0


def _readiness(channels: ChannelManager) -> tuple[bool, str]:
    try:
        websocket: object = channels.get_status().get("websocket")
    except Exception:
        logger.exception("Gateway readiness could not read channel status")
        websocket = None

    if isinstance(websocket, dict):
        status = cast(dict[str, object], websocket)
        state = status.get("state")
        return status.get("running") is True, state if isinstance(state, str) else "unavailable"
    if websocket is not None or "websocket" in channels.enabled_channels:
        return False, "unavailable"
    return True, "disabled"


async def serve_health(
    host: str,
    port: int,
    *,
    channels: ChannelManager,
    identity: GatewayHealthIdentity,
    admission: RuntimeAdmission,
    on_bound: Callable[[str, int], None],
) -> None:
    """Own the listener until cancelled, exposing live readiness and maintenance."""
    connection_slots = asyncio.Semaphore(_MAX_CONNECTIONS)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if connection_slots.locked():
            writer.close()
            return

        async with connection_slots:
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=_READ_TIMEOUT_SECONDS)
                request = data.split(b"\r\n", 1)[0].decode("utf-8", errors="replace").split(" ")
                if request[:2] == ["GET", "/health"]:
                    ready, websocket = _readiness(channels)
                    body = json.dumps({
                        "status": "ok" if ready else "degraded",
                        "process": "alive",
                        "ready": ready,
                        "websocket": websocket,
                        "runtime": asdict(identity),
                        "maintenance": admission.paused,
                    })
                    status = "200 OK" if ready else "503 Service Unavailable"
                    content_type = "application/json"
                else:
                    body = "Not Found"
                    status = "404 Not Found"
                    content_type = "text/plain"
                writer.write((
                    f"HTTP/1.0 {status}\r\n"
                    f"Content-Type: {content_type}\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    "Connection: close\r\n"
                    f"\r\n{body}"
                ).encode())
                await writer.drain()
            except (asyncio.TimeoutError, ConnectionError):
                pass
            finally:
                writer.close()

    server = await asyncio.start_server(handle, host, port)
    async with server:
        on_bound(host, port)
        await server.serve_forever()
