"""WebSocket handler for real-time dashboard events."""

from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from nanobot.web.events import DashboardEventBus


async def websocket_endpoint(ws: WebSocket, event_bus: DashboardEventBus) -> None:
    """Handle a single WebSocket connection — streams events to the client."""
    await ws.accept()
    queue = event_bus.subscribe()
    logger.info("Dashboard WebSocket client connected")

    try:
        # Send a welcome event
        await ws.send_json({"type": "connected", "message": "Dashboard connected"})

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await ws.send_json(event)
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                await ws.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        logger.info("Dashboard WebSocket client disconnected")
    except Exception as e:
        logger.debug("Dashboard WebSocket error: {}", e)
    finally:
        event_bus.unsubscribe(queue)
