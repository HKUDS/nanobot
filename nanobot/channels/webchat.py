"""Web Chat channel implementation with WebSocket support."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from aiohttp import web, WSMsgType
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base


class WebChatConfig(Base):
    """Web Chat channel configuration."""

    enabled: bool = True  # Enabled by default for easy local development
    host: str = "0.0.0.0"
    port: int = 8080
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    streaming: bool = True
    static_path: str | None = None  # Custom static files path
    show_typing: bool = True  # Show "typing..." indicator while processing
    typing_emoji: str = "🔄"  # Emoji to show while processing
    max_upload_size: int = 10 * 1024 * 1024  # 10MB max upload size
    max_msg_size: int = 10 * 1024 * 1024  # 10MB max WebSocket message size
    allowed_extensions: list[str] = Field(
        default_factory=lambda: ["jpg", "jpeg", "png", "gif", "webp", "pdf", "txt", "doc", "docx", "zip"]
    )


class WebChatChannel(BaseChannel):
    """
    Web Chat channel that provides a web-based chat interface.

    Features:
    - WebSocket-based real-time messaging
    - Optional Server-Sent Events (SSE) fallback
    - Built-in HTML chat interface
    - Support for streaming responses
    - Multi-user support with session management
    """

    name = "webchat"
    display_name = "Web Chat"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebChatConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebChatConfig.model_validate(config)
        super().__init__(config, bus)
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        # Map chat_id -> list of WebSocket connections
        self._connections: dict[str, list[web.WebSocketResponse]] = defaultdict(list)
        # Map session_id -> chat_id for tracking user sessions
        self._session_chat_map: dict[str, str] = {}
        # Message buffers for streaming (chat_id -> accumulated content)
        self._stream_buffers: dict[str, str] = {}
        # Track typing state per chat_id
        self._typing_sent: set[str] = set()

    def _get_media_dir(self) -> Path:
        """Get the media directory for webchat uploads."""
        return get_media_dir("webchat")

    def _is_allowed_file(self, filename: str) -> bool:
        """Check if file extension is allowed."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        allowed = getattr(self.config, "allowed_extensions", [])
        return ext in allowed

    async def _save_uploaded_file(self, data: bytes, filename: str) -> str | None:
        """Save uploaded file data to media directory, return local path."""
        max_size = getattr(self.config, "max_upload_size", 10 * 1024 * 1024)
        if len(data) > max_size:
            logger.warning("WebChat: file {} exceeds max size limit", filename)
            return None

        if not self._is_allowed_file(filename):
            logger.warning("WebChat: file type not allowed for {}", filename)
            return None

        try:
            media_dir = self._get_media_dir()
            # Generate unique filename to avoid collisions
            import time
            unique_prefix = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
            safe_filename = f"{unique_prefix}_{filename}"
            file_path = media_dir / safe_filename
            await asyncio.to_thread(file_path.write_bytes, data)
            logger.debug("WebChat: saved file to {}", file_path)
            return str(file_path)
        except Exception as e:
            logger.error("WebChat: failed to save file {}: {}", filename, e)
            return None

    async def _save_base64_media(self, base64_data: str, filename: str) -> str | None:
        """Decode base64 data and save to media directory, return local path."""
        try:
            import base64
            # Handle data URI format: data:image/png;base64,xxxxx
            if "," in base64_data:
                base64_data = base64_data.split(",", 1)[1]
            data = base64.b64decode(base64_data)
            return await self._save_uploaded_file(data, filename)
        except Exception as e:
            logger.error("WebChat: failed to decode base64 media {}: {}", filename, e)
            return None

    async def _cleanup_port(self, port: int) -> bool:
        """Check if port is in use and try to kill stale processes.
        
        Returns True if port is now available.
        """
        # Check if port is available
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        try:
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            if result != 0:
                # Port is free
                return True
        except Exception:
            sock.close()
            return True

        # Port is in use, find the process
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                if not pid:
                    continue
                try:
                    pid_int = int(pid)
                    # Get process info
                    proc_result = subprocess.run(
                        ["ps", "-p", pid, "-o", "comm="],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    proc_name = proc_result.stdout.strip()
                    
                    # Only kill Python processes (likely stale nanobot instances)
                    if "Python" in proc_name or "python" in proc_name.lower():
                        logger.warning(
                            "Port {} is in use by PID {} ({}). Killing stale process...",
                            port, pid, proc_name
                        )
                        try:
                            os.kill(pid_int, signal.SIGTERM)
                            # Wait briefly for graceful shutdown
                            await asyncio.sleep(0.5)
                        except ProcessLookupError:
                            pass  # Process already gone
                        except PermissionError:
                            logger.warning("Cannot kill PID {}: permission denied", pid_int)
                except (ValueError, subprocess.TimeoutExpired):
                    continue
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Cannot check port {}: lsof not available", port)

        # Recheck if port is now free
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        try:
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            return result != 0
        except Exception:
            sock.close()
            return True

    async def start(self) -> None:
        """Start the Web Chat HTTP/WebSocket server."""
        self._running = True
        host = getattr(self.config, "host", "0.0.0.0")
        port = getattr(self.config, "port", 8080)

        # Check and cleanup stale processes on the port
        if not await self._cleanup_port(port):
            logger.warning(
                "Port {} is still in use after cleanup attempt. "
                "WebChat may fail to start.",
                port
            )

        self._app = web.Application()
        self._app.router.add_get("/ws", self._handle_websocket)
        self._app.router.add_post("/api/message", self._handle_http_message)
        self._app.router.add_post("/api/upload", self._handle_file_upload)
        self._app.router.add_get("/api/health", self._handle_health)
        self._app.router.add_get("/media/{filename:.*}", self._handle_media)

        # Serve custom static files if configured
        static_path = getattr(self.config, "static_path", None)
        if static_path and Path(static_path).exists():
            self._app.router.add_static("/static", static_path)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()

        logger.info("Web Chat server started at http://{}:{}", host, port)

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Web Chat server."""
        self._running = False

        # Close all WebSocket connections
        for chat_id, connections in list(self._connections.items()):
            for ws in connections:
                if not ws.closed:
                    await ws.close()
        self._connections.clear()
        self._session_chat_map.clear()

        # Cleanup server
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        logger.info("Web Chat server stopped")

    async def _send_typing(self, chat_id: str, is_typing: bool = True) -> None:
        """Send typing indicator to web clients."""
        connections = self._connections.get(chat_id, [])
        if not connections:
            return

        payload = {
            "type": "typing",
            "is_typing": is_typing,
            "emoji": getattr(self.config, "typing_emoji", "🔄"),
        }

        for ws in connections:
            if not ws.closed:
                try:
                    await ws.send_json(payload)
                except Exception as e:
                    logger.warning("Failed to send typing indicator: {}", e)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to web clients."""
        chat_id = msg.chat_id
        connections = self._connections.get(chat_id, [])

        if not connections:
            logger.debug("No active WebSocket connections for chat_id: {}", chat_id)
            return

        # Clear typing indicator when sending actual message
        if chat_id in self._typing_sent:
            await self._send_typing(chat_id, is_typing=False)
            self._typing_sent.discard(chat_id)

        # Convert local file paths to HTTP URLs for media
        media_urls = []
        for item in (msg.media or []):
            if isinstance(item, str):
                # Local file path -> HTTP URL
                if item.startswith("/") or item.startswith("~"):
                    filename = Path(item).name
                    media_urls.append({"url": f"/media/{filename}", "type": "file"})
                else:
                    # Already a URL
                    media_urls.append({"url": item, "type": "file"})
            elif isinstance(item, dict):
                # Already formatted media item
                media_urls.append(item)
            else:
                media_urls.append(str(item))

        payload = {
            "type": "message",
            "content": msg.content,
            "media": media_urls,
            "metadata": msg.metadata,
        }

        for ws in connections:
            if not ws.closed:
                try:
                    await ws.send_json(payload)
                except Exception as e:
                    logger.warning("Failed to send message via WebSocket: {}", e)

    async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
        """Send a streaming delta to web clients."""
        meta = metadata or {}
        connections = self._connections.get(chat_id, [])

        if not connections:
            return

        # Clear typing indicator on first delta
        if chat_id in self._typing_sent:
            await self._send_typing(chat_id, is_typing=False)
            self._typing_sent.discard(chat_id)

        # Accumulate buffer for potential re-sends
        if chat_id not in self._stream_buffers:
            self._stream_buffers[chat_id] = ""
        self._stream_buffers[chat_id] += delta

        payload = {
            "type": "delta",
            "delta": delta,
            "content": self._stream_buffers[chat_id],
            "is_end": meta.get("_stream_end", False),
            "metadata": meta,
        }

        for ws in connections:
            if not ws.closed:
                try:
                    await ws.send_json(payload)
                except Exception as e:
                    logger.warning("Failed to send delta via WebSocket: {}", e)

        # Clean up buffer on stream end
        if meta.get("_stream_end"):
            self._stream_buffers.pop(chat_id, None)

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connections."""
        max_msg_size = getattr(self.config, "max_msg_size", 4 * 1024 * 1024)
        ws = web.WebSocketResponse(max_msg_size=max_msg_size)
        await ws.prepare(request)

        # Get or create session/chat ID
        session_id = request.query.get("session_id") or str(uuid.uuid4())
        chat_id = self._session_chat_map.get(session_id)
        if not chat_id:
            chat_id = f"webchat_{session_id}"
            self._session_chat_map[session_id] = chat_id

        # Track connection
        self._connections[chat_id].append(ws)
        logger.info("WebSocket client connected: session={}, chat_id={}", session_id, chat_id)

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        text = data.get("text", "").strip()
                        media = []

                        # Handle inline base64 media (images)
                        inline_media = data.get("media", [])
                        for item in inline_media:
                            if isinstance(item, dict):
                                base64_data = item.get("data", "")
                                filename = item.get("filename", "image.png")
                            else:
                                base64_data = str(item)
                                filename = "image.png"
                            if base64_data:
                                file_path = await self._save_base64_media(base64_data, filename)
                                if file_path:
                                    media.append(file_path)
                                    logger.debug("WebSocket: saved inline media to {}", file_path)

                        if text or media:
                            # Show typing indicator before processing
                            if getattr(self.config, "show_typing", True):
                                await self._send_typing(chat_id, is_typing=True)
                                self._typing_sent.add(chat_id)

                            # Build content text
                            content = text
                            if media and not text:
                                # If only media, show placeholder text
                                media_names = [Path(p).name for p in media]
                                content = f"[{', '.join(['file: ' + n for n in media_names])}]"

                            await self._handle_message(
                                sender_id=session_id,
                                chat_id=chat_id,
                                content=content,
                                media=media if media else None,
                                metadata={"session_id": session_id, "via": "websocket"},
                            )
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON from WebSocket client")
                elif msg.type == WSMsgType.ERROR:
                    logger.error("WebSocket error: {}", ws.exception())
        except Exception as e:
            logger.error("WebSocket handler error: {}", e)
        finally:
            # Remove connection
            if chat_id in self._connections:
                self._connections[chat_id] = [c for c in self._connections[chat_id] if c != ws]
                if not self._connections[chat_id]:
                    del self._connections[chat_id]
            logger.info("WebSocket client disconnected: session={}, chat_id={}", session_id, chat_id)

        return ws

    async def _handle_http_message(self, request: web.Request) -> web.Response:
        """Handle HTTP POST messages (for non-WebSocket clients)."""
        try:
            data = await request.json()
            text = data.get("text", "").strip()
            session_id = data.get("session_id") or str(uuid.uuid4())
            media = []

            # Handle inline base64 media
            inline_media = data.get("media", [])
            for item in inline_media:
                if isinstance(item, dict):
                    base64_data = item.get("data", "")
                    filename = item.get("filename", "image.png")
                else:
                    base64_data = str(item)
                    filename = "image.png"
                if base64_data:
                    file_path = await self._save_base64_media(base64_data, filename)
                    if file_path:
                        media.append(file_path)

            if not text and not media:
                return web.json_response({"error": "Empty message"}, status=400)

            chat_id = f"webchat_{session_id}"

            # Build content text
            content = text
            if media and not text:
                media_names = [Path(p).name for p in media]
                content = f"[{', '.join(['file: ' + n for n in media_names])}]"

            await self._handle_message(
                sender_id=session_id,
                chat_id=chat_id,
                content=content,
                media=media if media else None,
                metadata={"session_id": session_id, "via": "http"},
            )

            return web.json_response({"status": "ok", "chat_id": chat_id})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error("Error handling HTTP message: {}", e)
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_file_upload(self, request: web.Request) -> web.Response:
        """Handle HTTP file upload requests."""
        try:
            # Support both multipart form and JSON with base64
            content_type = request.headers.get("Content-Type", "")
            session_id = request.query.get("session_id") or str(uuid.uuid4())
            chat_id = f"webchat_{session_id}"

            media_paths = []
            text = ""

            if "multipart/form-data" in content_type:
                # Handle multipart file upload
                reader = await request.multipart()
                while True:
                    field = await reader.next()
                    if field is None:
                        break

                    if field.name == "file":
                        filename = field.filename or "upload.bin"
                        data = await field.read()
                        file_path = await self._save_uploaded_file(data, filename)
                        if file_path:
                            media_paths.append(file_path)
                            text += f"[file: {Path(filename).name}] "
                    elif field.name == "text":
                        text = (await field.text()).strip()

            elif "application/json" in content_type:
                # Handle JSON with base64 media
                data = await request.json()
                text = data.get("text", "").strip()

                # Accept array of base64 items or single item
                media_items = data.get("media", [])
                if isinstance(media_items, str):
                    media_items = [{"data": media_items, "filename": "image.png"}]
                elif isinstance(media_items, list):
                    media_items = [
                        {"data": item if isinstance(item, str) else item.get("data", ""),
                         "filename": item.get("filename", "image.png") if isinstance(item, dict) else "image.png"}
                        for item in media_items
                    ]

                for item in media_items:
                    if item.get("data"):
                        file_path = await self._save_base64_media(item["data"], item.get("filename", "image.png"))
                        if file_path:
                            media_paths.append(file_path)
            else:
                return web.json_response({"error": "Unsupported content type"}, status=400)

            if not text and not media_paths:
                return web.json_response({"error": "No content"}, status=400)

            if not text and media_paths:
                media_names = [Path(p).name for p in media_paths]
                text = f"[{', '.join(['file: ' + n for n in media_names])}]"

            # Show typing indicator
            if getattr(self.config, "show_typing", True):
                await self._send_typing(chat_id, is_typing=True)
                self._typing_sent.add(chat_id)

            await self._handle_message(
                sender_id=session_id,
                chat_id=chat_id,
                content=text,
                media=media_paths if media_paths else None,
                metadata={"session_id": session_id, "via": "http_upload"},
            )

            return web.json_response({
                "status": "ok",
                "chat_id": chat_id,
                "media": [str(Path(p).name) for p in media_paths]
            })

        except Exception as e:
            logger.error("Error handling file upload: {}", e)
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "ok",
            "channel": self.name,
            "running": self._running,
            "active_sessions": len(self._session_chat_map),
            "active_connections": sum(len(conns) for conns in self._connections.values()),
        })

    async def _handle_media(self, request: web.Request) -> web.Response:
        """Serve uploaded media files."""
        filename = request.match_info.get("filename", "")
        if not filename:
            return web.Response(status=404)

        # Security: prevent path traversal
        if ".." in filename or filename.startswith("/"):
            return web.Response(status=403)

        # Find the file in media directory
        media_dir = self._get_media_dir()
        file_path = media_dir / filename

        # Also check subdirectories
        if not file_path.exists():
            # Try to find by partial match (unique prefix)
            for part in filename.split("_"):
                if len(part) >= 8:
                    for f in media_dir.glob(f"*{part}*"):
                        if f.name == filename:
                            file_path = f
                            break

        if not file_path.exists() or not file_path.is_file():
            return web.Response(status=404)

        # Determine content type
        import mimetypes
        content_type, _ = mimetypes.guess_type(str(file_path))
        if not content_type:
            content_type = "application/octet-stream"

        return web.Response(
            body=file_path.read_bytes(),
            content_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"}
        )
