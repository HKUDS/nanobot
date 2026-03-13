"""Web UI channel — FastAPI + WebSocket + zero-npm HTML interface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WebUIConfig

# Optional deps — only needed when channel is enabled
try:
    import uvicorn
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

# Static HTML file lives next to this module
_STATIC_DIR = Path(__file__).parent / "static"
_INDEX_HTML  = _STATIC_DIR / "webui.html"

# Synthetic sender/chat IDs for the web UI
_WEB_SENDER = "web_user"
_WEB_CHAT   = "webui"


class WebUIChannel(BaseChannel):
    """
    Browser-based chat channel served via FastAPI + WebSocket.

    OpenClaw-compatible UI in a single HTML file (zero npm, ~5 MB extra RAM).

    Config keys (all optional):
        host        Bind host  (default: "0.0.0.0")
        port        HTTP port  (default: 7860)
        allow_from  ["*"] opens to all; empty list denies all (default: ["*"])
    """

    name = "webui"

    def __init__(self, config: WebUIConfig, bus: MessageBus) -> None:
        super().__init__(config, bus)
        self.config: WebUIConfig = config

        # Map  chat_id -> asyncio.Queue[str]  for WS streaming
        self._ws_queues: dict[str, asyncio.Queue[str | None]] = {}
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None  # type: ignore[name-defined]

    # ── BaseChannel interface ────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the FastAPI + WebSocket server."""
        if not _FASTAPI_AVAILABLE:
            logger.error(
                "WebUI channel requires fastapi and uvicorn. "
                "Install with:  pip install fastapi 'uvicorn[standard]'"
            )
            return

        self._running = True
        self._app = self._build_app()

        cfg = uvicorn.Config(
            self._app,
            host=self.config.host,
            port=self.config.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(cfg)

        logger.info(
            "WebUI channel listening on http://{}:{}", self.config.host, self.config.port
        )
        await self._server.serve()

    async def stop(self) -> None:
        """Gracefully stop the server."""
        self._running = False
        if self._server:
            self._server.should_exit = True

    async def send(self, msg: OutboundMessage) -> None:
        """Push an outbound message to all waiting WebSocket sessions."""
        q = self._ws_queues.get(msg.chat_id)
        if q is None:
            logger.debug("WebUI: no active WS for chat_id={}", msg.chat_id)
            return

        is_progress = msg.metadata.get("_progress", False)
        payload = json.dumps({
            "type":     "token" if is_progress else "message",
            "content":  msg.content,
            "media":    msg.media,
        })
        await q.put(payload)

        # Signal end-of-turn for non-progress (final) messages
        if not is_progress:
            await q.put(json.dumps({"type": "done"}))

    # ── FastAPI app builder ──────────────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="nanobot Web UI", version="0.1.0")

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # ── GET / ── serve the Control UI ──────────────────────────────────
        @app.get("/", response_class=HTMLResponse)
        async def serve_index():
            if _INDEX_HTML.exists():
                return _INDEX_HTML.read_text()
            return HTMLResponse(
                "<h1>nanobot WebUI</h1>"
                "<p>Static file not found: nanobot/channels/static/webui.html</p>"
            )

        # ── GET /status ────────────────────────────────────────────────────
        @app.get("/status")
        async def status():
            import resource, sys
            try:
                kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                mb = kb / 1024 if sys.platform != "darwin" else kb / (1024 * 1024)
                ram = f"~{int(mb)} MB"
            except Exception:
                ram = "n/a"
            return {"ok": True, "channel": self.name, "ram": ram}

        # ── WebSocket /ws ──────────────────────────────────────────────────
        @app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket, session: str = _WEB_CHAT):
            await websocket.accept()

            # One queue per active session
            q: asyncio.Queue[str | None] = asyncio.Queue()
            self._ws_queues[session] = q

            async def _receiver():
                """Read messages from the browser and push to the agent bus."""
                try:
                    while True:
                        raw = await websocket.receive_text()
                        data = json.loads(raw)
                        if data.get("type") == "chat":
                            text = data.get("text", "").strip()
                            if text:
                                await self._handle_message(
                                    sender_id=_WEB_SENDER,
                                    chat_id=session,
                                    content=text,
                                    metadata={"session": session},
                                )
                except WebSocketDisconnect:
                    pass

            async def _sender():
                """Flush queued tokens/messages back to the browser."""
                try:
                    while True:
                        payload = await asyncio.wait_for(q.get(), timeout=60.0)
                        if payload is None:
                            break
                        await websocket.send_text(payload)
                except asyncio.TimeoutError:
                    pass
                except WebSocketDisconnect:
                    pass

            try:
                await asyncio.gather(_receiver(), _sender())
            finally:
                self._ws_queues.pop(session, None)

        return app
