"""Interactive WebSocket API channel."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_logs_dir
from nanobot.config.schema import ApiConfig
from nanobot.utils.helpers import ensure_dir


class APIChannel(BaseChannel):
    """WebSocket channel for interactive API chat."""

    name = "api"

    def __init__(self, config: ApiConfig, bus: MessageBus, host: str, port: int):
        super().__init__(config, bus)
        self.config: ApiConfig = config
        self.host = host
        self.port = port
        self._server = None
        self._chat_connections: dict[str, set[Any]] = defaultdict(set)
        self._conn_chats: dict[Any, set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._log_lock = asyncio.Lock()
        self._log_file = self._init_log_file()

    def _init_log_file(self) -> Path:
        """Create API log path under instance runtime logs directory."""
        logs_dir = ensure_dir(get_logs_dir() / "api")
        return logs_dir / "chat_events.jsonl"

    async def start(self) -> None:
        """Start WebSocket API server."""
        import websockets

        self._running = True
        self._server = await websockets.serve(self._on_connection, self.host, self.port)
        logger.info(
            "API channel started at ws://{}:{}{}",
            self.host,
            self.port,
            self.config.path,
        )
        await self._append_log(
            "server_started",
            host=self.host,
            port=self.port,
            path=self.config.path,
            log_file=str(self._log_file),
        )

        try:
            await self._server.wait_closed()
        finally:
            self._server = None
            self._running = False

    async def stop(self) -> None:
        """Stop WebSocket API server."""
        await self._append_log("server_stopping")
        self._running = False
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        async with self._lock:
            all_connections = list(self._conn_chats.keys())
            self._chat_connections.clear()
            self._conn_chats.clear()

        for connection in all_connections:
            try:
                await connection.close()
            except Exception:
                continue
        await self._append_log("server_stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Push outbound bus messages to API clients."""
        payload = self._build_outbound_payload(msg)
        encoded = json.dumps(payload, ensure_ascii=False)

        async with self._lock:
            targets = list(self._chat_connections.get(msg.chat_id, set()))

        if not targets:
            logger.debug("API channel: no active client for chat_id {}", msg.chat_id)
            return

        stale: list[Any] = []
        for connection in targets:
            try:
                await connection.send(encoded)
            except Exception:
                stale.append(connection)

        await self._append_log(
            "outbound",
            chat_id=msg.chat_id,
            request_id=payload.get("requestId"),
            message_type=payload.get("type"),
            content_preview=self._preview(msg.content),
            recipients=len(targets),
            stale_connections=len(stale),
        )

        if stale:
            async with self._lock:
                for connection in stale:
                    for chat_id in self._conn_chats.get(connection, set()):
                        self._chat_connections.get(chat_id, set()).discard(connection)
                    self._conn_chats.pop(connection, None)

    async def _on_connection(self, connection) -> None:
        """Handle one WebSocket client connection."""
        path, query = self._extract_request_info(connection)
        if self.config.path and path != self.config.path:
            await self._append_log("connection_rejected", reason="path_mismatch", path=path)
            await connection.close(code=4404, reason="Not Found")
            return

        token = self._extract_token(connection, query)
        if self.config.token and token != self.config.token:
            await self._append_log("connection_rejected", reason="unauthorized", path=path)
            await connection.close(code=4401, reason="Unauthorized")
            return

        await self._send_json(connection, {"type": "ready", "channel": self.name})
        await self._append_log(
            "connection_opened",
            path=path,
            remote=self._remote_addr(connection),
        )

        try:
            async for raw in connection:
                await self._handle_client_message(connection, raw, query)
        except Exception as e:
            logger.debug("API channel connection closed: {}", e)
            await self._append_log("connection_error", error=str(e), remote=self._remote_addr(connection))
        finally:
            await self._remove_connection(connection)
            await self._append_log("connection_closed", remote=self._remote_addr(connection))

    async def _handle_client_message(self, connection, raw: Any, query: dict[str, list[str]]) -> None:
        """Parse and route one client payload."""
        if not isinstance(raw, str):
            await self._send_error(connection, "Only text JSON frames are supported.")
            return

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            await self._send_error(connection, "Invalid JSON payload.")
            return

        if not isinstance(payload, dict):
            await self._send_error(connection, "Payload must be a JSON object.")
            return

        msg_type = str(payload.get("type") or "chat").lower()
        if msg_type == "ping":
            await self._send_json(connection, {"type": "pong"})
            return
        if msg_type != "chat":
            await self._send_error(connection, f"Unsupported message type: {msg_type}")
            return

        parsed = self._parse_chat_payload(payload, query)
        if isinstance(parsed, str):
            await self._send_error(connection, parsed, payload.get("requestId") or payload.get("request_id"))
            return

        if not self.is_allowed(parsed["sender_id"]):
            await self._send_error(
                connection,
                "Access denied for senderId.",
                parsed["metadata"].get("request_id"),
            )
            return

        await self._bind_connection(parsed["chat_id"], connection)
        await self._append_log(
            "inbound",
            sender_id=parsed["sender_id"],
            chat_id=parsed["chat_id"],
            request_id=parsed["metadata"].get("request_id"),
            session_key=parsed["session_key"],
            content_preview=self._preview(parsed["content"]),
            media_count=len(parsed["media"]),
            remote=self._remote_addr(connection),
        )
        await self._handle_message(
            sender_id=parsed["sender_id"],
            chat_id=parsed["chat_id"],
            content=parsed["content"],
            media=parsed["media"],
            metadata=parsed["metadata"],
            session_key=parsed["session_key"],
        )

    @staticmethod
    def _extract_request_info(connection) -> tuple[str, dict[str, list[str]]]:
        """Return URL path and query dict from WebSocket request."""
        request = getattr(connection, "request", None)
        raw_path = getattr(request, "path", "") if request else ""
        parsed = urlparse(raw_path)
        return parsed.path or "/", parse_qs(parsed.query, keep_blank_values=True)

    @staticmethod
    def _query_first(query: dict[str, list[str]], key: str) -> str:
        """Get first query value by key."""
        values = query.get(key, [])
        return values[0] if values else ""

    def _extract_token(self, connection, query: dict[str, list[str]]) -> str:
        """Extract bearer token from query or Authorization header."""
        token = self._query_first(query, "token")
        if token:
            return token

        request = getattr(connection, "request", None)
        headers = getattr(request, "headers", None)
        auth_header = ""
        if headers is not None:
            auth_header = headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return ""

    def _parse_chat_payload(
        self,
        payload: dict[str, Any],
        query: dict[str, list[str]],
    ) -> dict[str, Any] | str:
        """Validate and normalize an inbound chat payload."""
        sender_id = str(
            payload.get("senderId")
            or payload.get("sender_id")
            or self._query_first(query, "senderId")
            or self._query_first(query, "sender_id")
            or ""
        ).strip()
        if not sender_id:
            return "senderId is required."

        chat_id = str(
            payload.get("chatId")
            or payload.get("chat_id")
            or self._query_first(query, "chatId")
            or self._query_first(query, "chat_id")
            or sender_id
        ).strip()
        if not chat_id:
            return "chatId is required."

        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            return "content must be a non-empty string."

        media = payload.get("media")
        if media is None:
            media_list: list[str] = []
        elif isinstance(media, list):
            media_list = [str(item) for item in media]
        else:
            return "media must be an array of strings."

        metadata_raw = payload.get("metadata")
        if metadata_raw is None:
            metadata: dict[str, Any] = {}
        elif isinstance(metadata_raw, dict):
            metadata = dict(metadata_raw)
        else:
            return "metadata must be a JSON object."

        request_id = payload.get("requestId") or payload.get("request_id")
        if request_id is not None:
            metadata["request_id"] = str(request_id)

        session_key = (
            payload.get("sessionKey")
            or payload.get("session_key")
            or metadata.get("session_key")
            or metadata.get("sessionKey")
        )
        if session_key is not None:
            session_key = str(session_key)

        return {
            "sender_id": sender_id,
            "chat_id": chat_id,
            "content": content,
            "media": media_list,
            "metadata": metadata,
            "session_key": session_key,
        }

    @staticmethod
    def _build_outbound_payload(msg: OutboundMessage) -> dict[str, Any]:
        """Convert outbound bus message to WebSocket JSON payload."""
        metadata = dict(msg.metadata or {})
        is_progress = bool(metadata.get("_progress"))
        payload = {
            "type": "progress" if is_progress else "message",
            "channel": msg.channel,
            "chatId": msg.chat_id,
            "content": msg.content,
            "metadata": metadata,
        }
        if request_id := metadata.get("request_id"):
            payload["requestId"] = str(request_id)
        if metadata.get("_tool_hint"):
            payload["toolHint"] = True
        if msg.reply_to:
            payload["replyTo"] = msg.reply_to
        if msg.media:
            payload["media"] = list(msg.media)
        return payload

    async def _bind_connection(self, chat_id: str, connection) -> None:
        """Track which connection is subscribed to which chat_id."""
        async with self._lock:
            self._chat_connections[chat_id].add(connection)
            self._conn_chats[connection].add(chat_id)

    async def _remove_connection(self, connection) -> None:
        """Remove a closed connection from all chat mappings."""
        async with self._lock:
            chat_ids = self._conn_chats.pop(connection, set())
            for chat_id in chat_ids:
                conns = self._chat_connections.get(chat_id, set())
                conns.discard(connection)
                if not conns and chat_id in self._chat_connections:
                    self._chat_connections.pop(chat_id, None)

    async def _send_error(self, connection, message: str, request_id: Any = None) -> None:
        """Send JSON error payload to client."""
        payload: dict[str, Any] = {"type": "error", "error": message}
        if request_id is not None:
            payload["requestId"] = str(request_id)
        await self._send_json(connection, payload)
        await self._append_log(
            "error",
            request_id=payload.get("requestId"),
            error=message,
            remote=self._remote_addr(connection),
        )

    @staticmethod
    async def _send_json(connection, payload: dict[str, Any]) -> None:
        """Send JSON payload through WebSocket."""
        await connection.send(json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _preview(text: str, max_chars: int = 200) -> str:
        """Build a compact single-line preview for logs."""
        compact = text.replace("\r", "\\r").replace("\n", "\\n")
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars] + "..."

    @staticmethod
    def _remote_addr(connection) -> str:
        """Format remote address string for logging."""
        remote = getattr(connection, "remote_address", None)
        if isinstance(remote, tuple):
            return f"{remote[0]}:{remote[1]}"
        return str(remote) if remote is not None else ""

    async def _append_log(self, event: str, **fields: Any) -> None:
        """Append one JSON log event to API log file."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "channel": self.name,
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)

        def _write() -> None:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            with self._log_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

        async with self._log_lock:
            await asyncio.to_thread(_write)
