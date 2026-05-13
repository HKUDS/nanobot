"""Desktop WebSocket channel for Tauri desktop app."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base


class DesktopConfig(Base):
    """Desktop channel configuration."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 18791
    allow_from: list[str] = Field(default_factory=lambda: ["*"])


class DesktopChannel(BaseChannel):
    """
    Desktop channel that runs a WebSocket server on localhost.

    The Tauri desktop app's chat UI connects to this WebSocket endpoint
    to exchange messages with the nanobot agent.
    """

    name = "desktop"
    display_name = "Desktop"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return DesktopConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = DesktopConfig.model_validate(config)
        super().__init__(config, bus)
        self._server = None
        self._clients: set = set()

    async def start(self) -> None:
        """Start the WebSocket server and listen for connections."""
        import websockets

        host = self.config.host
        port = self.config.port

        self._running = True

        async def handler(websocket):
            self._clients.add(websocket)
            remote = websocket.remote_address
            logger.info("Desktop client connected from {}", remote)

            # Send ready status
            try:
                await websocket.send(json.dumps({"type": "status", "status": "ready"}))
            except Exception:
                pass

            try:
                async for raw in websocket:
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON from desktop client: {}", raw[:100])
                        continue

                    msg_type = data.get("type")

                    if msg_type == "message":
                        content = data.get("content", "").strip()
                        if not content:
                            continue
                        await self._handle_message(
                            sender_id="desktop-user",
                            chat_id="desktop",
                            content=content,
                            media=data.get("media") or [],
                        )

                    elif msg_type == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))

            except Exception as e:
                if self._running:
                    logger.debug("Desktop client disconnected: {}", e)
            finally:
                self._clients.discard(websocket)
                logger.info("Desktop client disconnected from {}", remote)

        logger.info("Starting Desktop WebSocket server on ws://{}:{}...", host, port)
        self._server = await websockets.serve(handler, host, port)
        logger.info("Desktop channel ready on ws://{}:{}", host, port)

        # Block until stopped
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False

        # Close all client connections
        for ws in list(self._clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        logger.info("Desktop channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to all connected desktop clients."""
        if not self._clients:
            return

        is_progress = msg.metadata.get("_progress", False)
        is_tool_hint = msg.metadata.get("_tool_hint", False)

        payload = {
            "type": "progress" if is_progress else "response",
            "content": msg.content,
            "chat_id": msg.chat_id,
        }
        if is_tool_hint:
            payload["tool_hint"] = True
        if msg.media:
            payload["media"] = msg.media

        raw = json.dumps(payload, ensure_ascii=False)

        dead: list = []
        for ws in list(self._clients):
            try:
                await ws.send(raw)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._clients.discard(ws)
