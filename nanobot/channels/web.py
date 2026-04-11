"""Web UI channel — browser-based chat via WebSocket.

Starts an aiohttp server that serves a static chat frontend and communicates
with clients over WebSocket.  No Node.js required — pure Python backend with
vanilla HTML/CSS/JS on the frontend.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web
from loguru import logger
from pydantic import Field as PydanticField

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base

# ---------------------------------------------------------------------------
# Static assets directory (shipped alongside this module)
# ---------------------------------------------------------------------------
_STATIC_DIR = Path(__file__).resolve().parent / "web_static"

# ---------------------------------------------------------------------------
# Media directories for upload/download
# ---------------------------------------------------------------------------
_MEDIA_DIR = Path.home() / ".nanobot" / "media"
_MEDIA_SEARCH_DIRS = [
    Path.home() / ".nanobot" / "media",
    Path.home() / ".nanobot" / "workspace",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class WebConfig(Base):
    """Web channel configuration."""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    allow_from: list[str] = PydanticField(default_factory=lambda: ["*"])
    streaming: bool = True
    bearer_token: str = ""  # Set explicitly, or a random token is generated at startup


# ---------------------------------------------------------------------------
# Per-client streaming accumulator
# ---------------------------------------------------------------------------

@dataclass
class _StreamBuf:
    text: str = ""
    stream_id: str | None = None


# ---------------------------------------------------------------------------
# File-based message history (persists across gateway restarts)
# Each chat_id gets ~/.nanobot/web_history/{chat_id}.jsonl
# Each line: {"ts": float, "type": "message"|"user_message", "content": "...", "media": [...]}
# ---------------------------------------------------------------------------

_HISTORY_MAX = 200  # max lines to keep per file
_HISTORY_DIR = Path.home() / ".nanobot" / "web_history"


def _history_file(chat_id: str) -> Path:
    return _HISTORY_DIR / f"{chat_id}.jsonl"


def _append_history(chat_id: str, entry: dict[str, Any]) -> None:
    """Append one entry to the history file, trimming to _HISTORY_MAX lines."""
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = _history_file(chat_id)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    # Trim if over limit — read, slice, rewrite
    with open(path) as f:
        lines = f.readlines()
    if len(lines) > _HISTORY_MAX:
        with open(path, "w") as f:
            f.writelines(lines[-_HISTORY_MAX:])


def _read_history_since(chat_id: str, last_seen: float) -> list[dict[str, Any]]:
    """Return all history entries with ts > last_seen (up to _HISTORY_MAX)."""
    path = _history_file(chat_id)
    if not path.exists():
        return []
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("ts", 0) > last_seen:
                    results.append(entry)
            except json.JSONDecodeError:
                pass
    return results


def _name_file(chat_id: str) -> Path:
    return _HISTORY_DIR / f"{chat_id}.name"


def _get_chat_name(chat_id: str) -> str | None:
    path = _name_file(chat_id)
    if path.exists():
        return path.read_text().strip() or None
    return None


def _set_chat_name(chat_id: str, name: str) -> None:
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    _name_file(chat_id).write_text(name.strip()[:80])


_RENAME_PREFIX = "rename chat:"


def _check_rename(chat_id: str, content: str) -> str | None:
    """If content starts with 'rename chat: ...', save the name and return it."""
    lower = content.strip().lower()
    if lower.startswith(_RENAME_PREFIX):
        name = content.strip()[len(_RENAME_PREFIX):].strip()
        if name:
            _set_chat_name(chat_id, name)
            return name
    return None


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

class WebChannel(BaseChannel):
    """Browser-based chat channel served over HTTP + WebSocket."""

    name = "web"
    display_name = "Web"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WebConfig = config

        # WebSocket connections: chat_id → {client_id: ws}
        # Multiple devices can subscribe to the same chat_id.
        self._clients: dict[str, dict[str, web.WebSocketResponse]] = {}
        # Streaming buffers keyed by chat_id
        self._stream_bufs: dict[str, _StreamBuf] = {}

        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _check_auth(self, request: web.Request) -> bool:
        """Validate bearer token. Always required — generated at startup if not configured.

        Uses constant-time comparison to avoid leaking the token through
        per-byte timing differences.
        """
        token = self.config.bearer_token

        # Check Authorization header first, then query param fallback (for browser WebSocket)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and hmac.compare_digest(auth_header[7:], token):
            return True

        if hmac.compare_digest(request.query.get("token", ""), token):
            return True

        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True

        # Fail closed: generate a token if none was configured
        if not self.config.bearer_token:
            self.config.bearer_token = uuid.uuid4().hex
            from nanobot.config.loader import get_config_path
            logger.error(
                "No bearer_token configured — generated ephemeral token (will change on restart): {}\n"
                "  Set channels.web.bearerToken in {} for a persistent key.",
                self.config.bearer_token,
                get_config_path(),
            )

        @web.middleware
        async def auth_middleware(request: web.Request, handler):
            # Allow static assets and index page without auth
            path = request.path
            if path == "/" or path.startswith("/static"):
                return await handler(request)
            if not self._check_auth(request):
                raise web.HTTPUnauthorized(text="Invalid or missing bearer token")
            return await handler(request)

        # 16 MiB request body cap sized for media uploads (1920px JPEGs are
        # typically 200-500 KB, voice notes up to a few MB). aiohttp's default
        # is 1 MiB which silently rejects longer voice notes.
        self._app = web.Application(
            middlewares=[auth_middleware],
            client_max_size=16 * 1024 * 1024,
        )
        self._app.router.add_get("/ws", self._ws_handler)
        self._app.router.add_post("/upload", self._upload_handler)
        self._app.router.add_get("/media/{filename}", self._media_handler)
        self._app.router.add_get("/history/{chat_id}", self._history_handler)
        self._app.router.add_get("/chats", self._chats_handler)
        self._app.router.add_post("/chats/{chat_id}/rename", self._rename_handler)
        # Serve static frontend
        if _STATIC_DIR.is_dir():
            self._app.router.add_get("/", self._index_handler)
            self._app.router.add_static("/static", _STATIC_DIR, show_index=False)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()
        logger.info("Web UI listening on http://{}:{}", self.config.host, self.config.port)

        # Keep the channel alive until stopped
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._running = False
        # Close all WebSocket connections
        for conns in list(self._clients.values()):
            for ws in list(conns.values()):
                await ws.close()
        self._clients.clear()
        if self._runner:
            await self._runner.cleanup()
        logger.info("Web UI stopped")

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    async def _index_handler(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(_STATIC_DIR / "index.html")

    async def _upload_handler(self, request: web.Request) -> web.Response:
        """Accept multipart file upload, save to media directory."""
        _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            reader = await request.multipart()
        except Exception:
            return web.Response(status=400, text="Expected multipart/form-data")

        field = await reader.next()
        if field is None or field.name != "file":
            return web.Response(status=400, text="Expected 'file' field")

        original = field.filename or "upload.bin"
        safe_name = Path(original).name  # strip any directory components
        unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        dest = _MEDIA_DIR / unique_name

        with open(dest, "wb") as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                f.write(chunk)

        logger.info("Media uploaded: {}", dest)
        return web.json_response({
            "path": str(dest),
            "url": f"/media/{unique_name}",
        })

    async def _media_handler(self, request: web.Request) -> web.FileResponse:
        """Serve a media file by filename, searching known directories."""
        filename = request.match_info["filename"]
        if ".." in filename or filename.startswith("/"):
            raise web.HTTPForbidden()

        for search_dir in _MEDIA_SEARCH_DIRS:
            filepath = search_dir / filename
            if filepath.is_file():
                return web.FileResponse(filepath)

        raise web.HTTPNotFound()

    async def _history_handler(self, request: web.Request) -> web.Response:
        """REST endpoint: GET /history/{chat_id}?since=<timestamp>"""
        chat_id = request.match_info["chat_id"]
        since = float(request.query.get("since", "0"))
        messages = _read_history_since(chat_id, since)
        return web.json_response({"messages": messages})

    async def _chats_handler(self, request: web.Request) -> web.Response:
        """REST endpoint: GET /chats?ids=id1,id2,...

        Returns metadata for the requested chat IDs (preview, timestamps).
        Only returns data for IDs the client claims to own — no enumeration.
        """
        ids_param = request.query.get("ids", "")
        if not ids_param:
            return web.json_response({"chats": []})

        requested_ids = [i.strip() for i in ids_param.split(",") if i.strip()]
        chats = []
        for cid in requested_ids:
            path = _history_file(cid)
            if not path.exists():
                continue
            try:
                first_user_msg = ""
                first_ts = 0.0
                last_ts = 0.0
                msg_count = 0
                with open(path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg_count += 1
                        ts = entry.get("ts", 0)
                        if first_ts == 0:
                            first_ts = ts
                        if ts > last_ts:
                            last_ts = ts
                        if not first_user_msg and entry.get("type") == "user_message":
                            first_user_msg = (entry.get("content") or "")[:80]
                custom_name = _get_chat_name(cid)
                chats.append({
                    "id": cid,
                    "name": custom_name or "",
                    "preview": first_user_msg or "(no messages)",
                    "first_ts": first_ts,
                    "last_ts": last_ts,
                    "count": msg_count,
                })
            except Exception:
                continue

        # Sort by most recent first
        chats.sort(key=lambda c: c["last_ts"], reverse=True)
        return web.json_response({"chats": chats})

    async def _rename_handler(self, request: web.Request) -> web.Response:
        """REST endpoint: POST /chats/{chat_id}/rename  body: {"name": "..."}"""
        chat_id = request.match_info["chat_id"]
        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400, text="Expected JSON body")
        new_name = (data.get("name") or "").strip()[:80]
        if not new_name:
            return web.Response(status=400, text="Missing name")
        _set_chat_name(chat_id, new_name)
        # Notify any connected clients on this chat
        rename_payload = {"type": "chat_renamed", "name": new_name}
        for peer in list(self._clients.get(chat_id, {}).values()):
            if not peer.closed:
                await peer.send_json(rename_payload)
        return web.json_response({"ok": True, "name": new_name})

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        # max_msg_size caps inbound frames at 1 MiB (defense against a rogue
        # client sending a huge frame to exhaust memory — real chat frames
        # are KB, and media uploads go through POST /upload separately).
        # heartbeat enables transport-level ping/pong so half-dead TCP
        # connections get noticed promptly instead of lingering until the
        # OS keepalive fires.
        ws = web.WebSocketResponse(max_msg_size=1_048_576, heartbeat=20.0)
        await ws.prepare(request)

        # client_id identifies the device/connection, chat_id identifies the conversation.
        # Multiple devices can subscribe to the same chat_id.
        client_id: str | None = request.query.get("client_id")
        if client_id and len(client_id) > 128:
            client_id = client_id[:128]
        if not client_id:
            client_id = uuid.uuid4().hex[:12]

        chat_id: str | None = request.query.get("chat_id")
        if chat_id and len(chat_id) > 128:
            chat_id = chat_id[:128]
        if not chat_id:
            # Backwards-compat: if no chat_id provided, use client_id as both
            chat_id = client_id

        sender_id = client_id

        # Register connection — replace any stale ws for this same device
        conns = self._clients.setdefault(chat_id, {})
        old = conns.get(client_id)
        if old and not old.closed:
            await old.close()
        conns[client_id] = ws

        # Confirm connection with both IDs so clients can persist them
        await ws.send_json({"type": "connected", "client_id": client_id, "chat_id": chat_id})
        logger.info("Web client connected: {} (chat {})", client_id, chat_id)

        try:
            async for raw in ws:
                if raw.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(raw.data)
                    except json.JSONDecodeError:
                        await ws.send_json({"type": "error", "error": "Invalid JSON"})
                        continue

                    msg_type = data.get("type", "message")
                    if msg_type == "message":
                        content = data.get("content", "").strip()
                        media = data.get("media") or []
                        if not content and not media:
                            continue
                        # Record user message in history
                        ts = time.time()
                        user_payload = {
                            "ts": ts,
                            "type": "user_message",
                            "content": content,
                            "media": media,
                        }
                        _append_history(chat_id, user_payload)
                        # Broadcast to other devices on this chat
                        for cid, peer in list(self._clients.get(chat_id, {}).items()):
                            if cid != client_id and not peer.closed:
                                await peer.send_json(user_payload)
                        await self._handle_message(
                            sender_id=sender_id,
                            chat_id=chat_id,
                            content=content,
                            media=media,
                            metadata={},
                        )
                    elif msg_type == "sync":
                        # Client requests missed messages since a timestamp
                        last_seen = float(data.get("last_seen", 0))
                        missed = _read_history_since(chat_id, last_seen)
                        await ws.send_json({"type": "sync", "messages": missed})
                        logger.info("Web client {} synced: {} messages since {}", client_id, len(missed), last_seen)
                    elif msg_type == "ping":
                        await ws.send_json({"type": "pong"})
                    elif msg_type == "rename":
                        new_name = (data.get("name") or data.get("content") or "").strip()[:80]
                        if new_name:
                            _set_chat_name(chat_id, new_name)
                            # Notify all devices on this chat
                            rename_payload = {"type": "chat_renamed", "name": new_name}
                            for peer in list(self._clients.get(chat_id, {}).values()):
                                if not peer.closed:
                                    await peer.send_json(rename_payload)
                elif raw.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        except asyncio.CancelledError:
            pass
        finally:
            # Only remove our entry if it hasn't been replaced by a reconnect
            conns = self._clients.get(chat_id, {})
            is_current = conns.get(client_id) is ws
            logger.debug("Web cleanup: {} (chat {}), is_current={}, conns_before={}",
                         client_id, chat_id, is_current, len(conns))
            if is_current:
                conns.pop(client_id, None)
            # Clean up empty chat entries and stream buffers
            if chat_id in self._clients and not self._clients[chat_id]:
                del self._clients[chat_id]
                self._stream_bufs.pop(chat_id, None)
            logger.info("Web client disconnected: {} (chat {}), removed={}", client_id, chat_id, is_current)

        return ws

    # ------------------------------------------------------------------
    # Outbound: send full message
    # ------------------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        conns_for_chat = self._clients.get(msg.chat_id, {})
        live_count = sum(1 for ws in conns_for_chat.values() if not ws.closed)
        logger.info("Web.send() chat_id={}, all_chats={}, conns_for_chat={}, live={}",
                     msg.chat_id, list(self._clients.keys()), list(conns_for_chat.keys()), live_count)
        ts = time.time()
        payload = {
            "ts": ts,
            "type": "message",
            "content": msg.content,
            "media": msg.media,
        }
        # Always persist to disk so reconnecting clients can catch up
        _append_history(msg.chat_id, payload)

        # Check if the bot is renaming the chat
        new_name = _check_rename(msg.chat_id, msg.content)

        conns = self._clients.get(msg.chat_id, {})
        if not conns:
            logger.debug("Web: no active connection for chat_id={}, message buffered", msg.chat_id)
            return
        for ws in list(conns.values()):
            if not ws.closed:
                await ws.send_json(payload)
                if new_name:
                    await ws.send_json({"type": "chat_renamed", "name": new_name})

    # ------------------------------------------------------------------
    # Outbound: streaming deltas
    # ------------------------------------------------------------------

    async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
        meta = metadata or {}
        stream_id = meta.get("_stream_id")
        is_end = meta.get("_stream_end", False)
        conns_for_chat = self._clients.get(chat_id, {})
        live_count = sum(1 for ws in conns_for_chat.values() if not ws.closed)
        logger.debug("Web.send_delta() chat_id={}, stream_end={}, all_chats={}, live={}",
                      chat_id, is_end, list(self._clients.keys()), live_count)

        if meta.get("_stream_end"):
            buf = self._stream_bufs.pop(chat_id, None)
            final_text = (buf.text if buf else "") + delta
            if final_text:
                ts = time.time()
                # Persist the completed streamed message
                _append_history(chat_id, {
                    "ts": ts,
                    "type": "message",
                    "content": final_text,
                    "media": [],
                })
                new_name = _check_rename(chat_id, final_text)
                for ws in list(self._clients.get(chat_id, {}).values()):
                    if not ws.closed:
                        await ws.send_json({
                            "type": "stream_end",
                            "content": final_text,
                            "ts": ts,
                        })
                        if new_name:
                            await ws.send_json({"type": "chat_renamed", "name": new_name})
            return

        # Accumulate streaming text even if client is disconnected
        buf = self._stream_bufs.get(chat_id)
        if buf is None or (stream_id is not None and buf.stream_id is not None and buf.stream_id != stream_id):
            buf = _StreamBuf(stream_id=stream_id)
            self._stream_bufs[chat_id] = buf
        elif buf.stream_id is None:
            buf.stream_id = stream_id

        buf.text += delta

        for ws in list(self._clients.get(chat_id, {}).values()):
            if not ws.closed:
                await ws.send_json({
                    "type": "stream_delta",
                    "delta": delta,
                })

    @property
    def supports_streaming(self) -> bool:
        return super().supports_streaming
