"""WebSocket gateway for external adapter integration."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

from loguru import logger
from pydantic import ValidationError
from websockets.asyncio.server import Server, serve
from websockets.exceptions import ConnectionClosed

from nanobot.bus.queue import MessageBus
from nanobot.transport.contracts import InboundTransportMessage, OutboundTransportEvent


class WebSocketGateway:
    """Bidirectional adapter gateway over WebSocket."""

    def __init__(self, bus: MessageBus, host: str = "127.0.0.1", port: int = 18791):
        self.bus = bus
        self.host = host
        self.port = port
        self._server: Server | None = None
        self._dispatch_task: asyncio.Task | None = None
        self._running = False
        self._clients: set[Any] = set()
        self._subscriptions: dict[Any, set[str]] = {}

    async def start(self) -> None:
        """Start gateway and outbound dispatcher."""
        if self._running:
            return
        self._running = True
        self._server = await serve(self._handle_client, self.host, self.port)
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
        logger.info("WebSocket gateway listening on ws://{}:{}", self.host, self.port)

    async def stop(self) -> None:
        """Stop gateway and close all active connections."""
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
            self._dispatch_task = None

        for ws in list(self._clients):
            try:
                await ws.close()
            except Exception:
                pass

        self._clients.clear()
        self._subscriptions.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(self, websocket) -> None:
        self._clients.add(websocket)
        self._subscriptions[websocket] = set()
        await self._send(websocket, {"type": "welcome", "version": 1})

        try:
            async for raw in websocket:
                await self._handle_frame(websocket, raw)
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            self._subscriptions.pop(websocket, None)

    async def _handle_frame(self, websocket, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            await self._send(websocket, {"type": "error", "error": "invalid_json"})
            return

        frame_type = payload.get("type")
        if frame_type == "ping":
            await self._send(websocket, {"type": "pong"})
            return

        if frame_type == "subscribe":
            channels = payload.get("channels")
            self._subscriptions[websocket] = self._normalize_channels(channels)
            await self._send(
                websocket,
                {
                    "type": "subscribed",
                    "channels": sorted(self._subscriptions[websocket]),
                },
            )
            return

        if frame_type == "inbound":
            body = payload.get("message", payload)
            try:
                inbound = InboundTransportMessage.model_validate(body)
            except ValidationError as e:
                await self._send(
                    websocket,
                    {"type": "error", "error": "invalid_inbound", "details": e.errors()},
                )
                return

            await self.bus.publish_inbound(inbound.to_bus_message())
            await self._send(
                websocket,
                {"type": "ack", "message_id": inbound.message_id or ""},
            )
            return

        await self._send(websocket, {"type": "error", "error": "unsupported_type"})

    def _normalize_channels(self, channels: Any) -> set[str]:
        if not isinstance(channels, Iterable) or isinstance(channels, (str, bytes)):
            return set()
        out = set()
        for item in channels:
            if isinstance(item, str) and item.strip():
                out.add(item.strip())
        return out

    async def _dispatch_outbound(self) -> None:
        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            event = OutboundTransportEvent.from_bus_message(msg).model_dump(mode="json")
            frame = {"type": "outbound", "event": event}

            dead_clients: list[Any] = []
            for ws in self._clients:
                subs = self._subscriptions.get(ws, set())
                if subs and msg.channel not in subs:
                    continue
                try:
                    await self._send(ws, frame)
                except ConnectionClosed:
                    dead_clients.append(ws)
                except Exception as e:
                    logger.warning("Failed to send outbound frame: {}", e)
                    dead_clients.append(ws)

            for ws in dead_clients:
                self._clients.discard(ws)
                self._subscriptions.pop(ws, None)

    @staticmethod
    async def _send(websocket, payload: dict[str, Any]) -> None:
        await websocket.send(json.dumps(payload, ensure_ascii=False))
