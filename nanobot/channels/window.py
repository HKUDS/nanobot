
"""Window iOS channel implementation using HTTP + WebSocket."""

import asyncio
import json
import uuid
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web
from loguru import logger

from nanobot import __version__
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WindowConfig
from nanobot.session.manager import SessionManager


class WindowChannel(BaseChannel):
    """Window app channel speaking Window Protocol v1."""

    name = "window"

    def __init__(self, config: WindowConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WindowConfig = config
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._clients: set[web.WebSocketResponse] = set()
        self._clients_by_chat: dict[str, set[web.WebSocketResponse]] = defaultdict(set)
        self._chat_by_ws: dict[web.WebSocketResponse, str] = {}
        self._pending_replies: dict[str, deque[str]] = defaultdict(deque)
        self._busy = False
        self._context_remaining: float = 1.0
        self._tokens_used: int = 0
        self._session_manager = SessionManager(Path.home() / ".nanobot" / "workspace")

    async def start(self) -> None:
        """Start HTTP + WebSocket endpoints for Window clients."""
        if not self.config.api_key:
            logger.warning("Window channel disabled: missing channels.window.api_key")
            return

        self._running = True

        app = web.Application()
        app.router.add_get('/status', self._handle_status)
        app.router.add_get('/messages', self._handle_messages)
        app.router.add_get('/ws', self._handle_ws)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self.config.host, port=self.config.port)
        await self._site.start()

        logger.info(f"Window channel listening on http://{self.config.host}:{self.config.port}")

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop channel server and disconnect clients."""
        self._running = False

        clients = list(self._clients)
        for ws in clients:
            await ws.close()

        self._clients.clear()
        self._clients_by_chat.clear()
        self._chat_by_ws.clear()

        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send outbound agent response back to Window websocket clients."""
        reply_to = None
        pending = self._pending_replies.get(msg.chat_id)
        if pending and len(pending) > 0:
            reply_to = pending.popleft()

        event = {
            "type": "message.complete",
            "reply_to": reply_to,
            "id": f"msg_{uuid.uuid4().hex[:12]}",
            "content": msg.content,
            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }

        await self._send_to_chat(msg.chat_id, event)

        if not any(self._pending_replies.values()):
            await self._set_busy(False)

    async def _handle_status(self, request: web.Request) -> web.Response:
        if not self._check_bearer_auth(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        return web.json_response(
            {
                "agent": "nanobot",
                "status": "busy" if self._busy else "idle",
                "context_remaining": self._context_remaining,
                "tokens_used": self._tokens_used,
                "version": __version__,
            }
        )

    async def _handle_messages(self, request: web.Request) -> web.Response:
        if not self._check_bearer_auth(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        limit_raw = request.query.get("limit", "20")
        try:
            limit = max(1, min(100, int(limit_raw)))
        except ValueError:
            limit = 20

        before = request.query.get("before")
        chat_id = request.query.get("chat_id", "ios-default")
        session = self._session_manager.get_or_create(f"window:{chat_id}")

        entries = []
        for idx, msg in enumerate(session.messages):
            role = msg.get("role", "user")
            if role not in {"user", "assistant"}:
                continue

            timestamp = msg.get("timestamp", datetime.utcnow().isoformat())
            ts_for_compare = timestamp
            if ts_for_compare.endswith("Z"):
                ts_for_compare = ts_for_compare[:-1]

            if before:
                before_cmp = before[:-1] if before.endswith("Z") else before
                if ts_for_compare >= before_cmp:
                    continue

            event_role = "agent" if role == "assistant" else "user"
            iso_ts = timestamp if timestamp.endswith("Z") else f"{timestamp}Z"
            entries.append(
                {
                    "id": f"msg_hist_{idx}",
                    "role": event_role,
                    "content": msg.get("content", ""),
                    "timestamp": iso_ts,
                }
            )

        return web.json_response({"messages": entries[-limit:]})

    async def _handle_ws(self, request: web.Request) -> web.StreamResponse:
        token = request.query.get("token", "")
        if token != self.config.api_key:
            return web.json_response({"error": "unauthorized"}, status=401)

        chat_id = request.query.get("chat_id", "ios-default")

        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        self._clients.add(ws)
        self._clients_by_chat[chat_id].add(ws)
        self._chat_by_ws[ws] = chat_id

        await self._send_json(
            ws,
            {
                "type": "connected",
                "agent": "nanobot",
                "status": "busy" if self._busy else "idle",
                "context_remaining": self._context_remaining,
                "tokens_used": self._tokens_used,
            },
        )

        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue

                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue

                if payload.get("type") != "message.send":
                    continue

                content = str(payload.get("content", "")).strip()
                if not content:
                    continue

                message_id = str(payload.get("id") or uuid.uuid4().hex)
                self._pending_replies[chat_id].append(message_id)

                await self._set_busy(True)

                await self.bus.publish_inbound(
                    InboundMessage(
                        channel=self.name,
                        sender_id=chat_id,
                        chat_id=chat_id,
                        content=content,
                        metadata={"message_id": message_id},
                    )
                )

        finally:
            self._clients.discard(ws)
            chat = self._chat_by_ws.pop(ws, None)
            if chat and chat in self._clients_by_chat:
                self._clients_by_chat[chat].discard(ws)
                if not self._clients_by_chat[chat]:
                    self._clients_by_chat.pop(chat, None)

        return ws

    async def emit_to_chat(self, chat_id: str, data: dict[str, Any]) -> None:
        """Public method for external callers (e.g. WindowTaskTool) to emit WS events."""
        await self._send_to_chat(chat_id, data)

    def update_context_remaining(self, value: float, tokens_used: int = 0) -> None:
        """Update context remaining and token count from agent loop token usage."""
        self._context_remaining = max(0.0, min(1.0, value))
        self._tokens_used = tokens_used

    async def _set_busy(self, busy: bool) -> None:
        if self._busy == busy:
            return

        self._busy = busy
        await self._broadcast(
            {
                "type": "status.update",
                "status": "busy" if busy else "idle",
                "context_remaining": self._context_remaining,
                "tokens_used": self._tokens_used,
            }
        )

    def _check_bearer_auth(self, request: web.Request) -> bool:
        auth = request.headers.get("Authorization", "")
        prefix = "Bearer "
        if not auth.startswith(prefix):
            return False
        token = auth[len(prefix) :].strip()
        return token == self.config.api_key

    async def _broadcast(self, data: dict[str, Any]) -> None:
        clients = list(self._clients)
        for ws in clients:
            await self._send_json(ws, data)

    async def _send_to_chat(self, chat_id: str, data: dict[str, Any]) -> None:
        clients = list(self._clients_by_chat.get(chat_id, set()))
        for ws in clients:
            await self._send_json(ws, data)

    async def _send_json(self, ws: web.WebSocketResponse, data: dict[str, Any]) -> None:
        if ws.closed:
            return
        try:
            await ws.send_json(data)
        except Exception as exc:
            logger.debug(f"Window channel send error: {exc}")
