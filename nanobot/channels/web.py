"""Web chat channel — HTTP server with SSE token streaming."""

from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WebConfig

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


class WebChannel(BaseChannel):
    """HTTP channel with Server-Sent Events for token-level streaming.

    Each browser tab gets a UUID session (stored in localStorage).
    POST /api/chat returns an SSE stream:

        event: token      — LLM text token (streams live)
        event: progress   — tool hint or intermediate progress line
        event: done       — turn complete; carries the final cleaned text
        event: error      — something went wrong
    """

    name = "web"

    def __init__(self, config: WebConfig, bus: MessageBus, agent_loop: "AgentLoop | None" = None):
        super().__init__(config, bus)
        self.config: WebConfig = config
        self._agent_loop = agent_loop
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        # chat_id (session UUID) → asyncio.Queue for proactive bus messages
        self._queues: dict[str, asyncio.Queue] = {}

    # ------------------------------------------------------------------
    # BaseChannel interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/{filename}", self._handle_static)
        self._app.router.add_post("/api/chat", self._handle_chat)
        self._app.router.add_get("/api/health", self._handle_health)

        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()
        logger.info("Web channel listening on {}:{}", self.config.host, self.config.port)

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def send(self, msg: OutboundMessage) -> None:
        """Receive bus-dispatched messages (e.g. from MessageTool) and forward to active SSE."""
        q = self._queues.get(msg.chat_id)
        if q:
            await q.put(msg)

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    def _static_dir(self) -> Path:
        """Resolve the frontend static directory.

        Resolution order:
        1. Explicit config.static_dir (absolute or relative to CWD)
        2. web/ next to the nanobot package root (repo layout or installed wheel)
        3. web/ relative to CWD as a last resort
        """
        if self.config.static_dir:
            return Path(self.config.static_dir).expanduser().resolve()
        # nanobot/channels/web.py → ../../.. = repo/package root
        pkg_root = Path(__file__).parent.parent.parent
        candidate = pkg_root / "web"
        if candidate.is_dir():
            return candidate
        return Path.cwd() / "web"

    async def _handle_index(self, request: web.Request) -> web.Response:
        return await self._serve_file(request, "index.html")

    async def _handle_static(self, request: web.Request) -> web.Response:
        return await self._serve_file(request, request.match_info["filename"])

    async def _serve_file(self, request: web.Request, filename: str) -> web.Response:
        static = self._static_dir()
        path = (static / filename).resolve()
        # Safety: don't escape the static directory
        if not str(path).startswith(str(static)):
            raise web.HTTPForbidden()
        if not path.exists() or not path.is_file():
            raise web.HTTPNotFound()
        mime, _ = mimetypes.guess_type(str(path))
        return web.Response(body=path.read_bytes(), content_type=mime or "application/octet-stream")

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.Response(
            text=json.dumps({"status": "ok"}),
            content_type="application/json",
        )

    async def _handle_chat(self, request: web.Request) -> web.StreamResponse:
        """Handle a chat POST and return an SSE stream."""
        try:
            data = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Expected JSON body")

        message: str = data.get("message", "").strip()
        session_id: str = data.get("session_id", "default")

        if not message:
            raise web.HTTPBadRequest(reason="message field is required")

        if not self.is_allowed(session_id):
            raise web.HTTPForbidden()

        # Per-request SSE queue (tokens + bus messages)
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._queues[session_id] = q

        # SSE callbacks
        async def on_token(text: str) -> None:
            await q.put(("token", text))

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            await q.put(("progress", content, tool_hint))

        # Launch agent as background task; result/errors go into the queue
        session_key = f"web:{session_id}"

        async def run_agent() -> None:
            try:
                if self._agent_loop is None:
                    raise RuntimeError("WebChannel has no agent_loop reference")
                final = await self._agent_loop.process_direct(
                    content=message,
                    session_key=session_key,
                    channel=self.name,
                    chat_id=session_id,
                    on_progress=on_progress,
                    on_token=on_token,
                )
                await q.put(("done", final or ""))
            except asyncio.CancelledError:
                await q.put(("error", "Request cancelled"))
                raise
            except Exception as exc:
                logger.exception("Web agent error for session {}", session_id)
                await q.put(("error", str(exc)))

        agent_task = asyncio.create_task(run_agent())

        # Prepare SSE response
        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        })
        response.enable_chunked_encoding()
        await response.prepare(request)

        def _sse(event: str, payload: dict) -> bytes:
            return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()

        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=120)
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    await response.write(b": ping\n\n")
                    continue

                if isinstance(item, OutboundMessage):
                    # Proactive message from MessageTool (goes through bus)
                    if item.metadata.get("_progress"):
                        await response.write(_sse("progress", {
                            "text": item.content,
                            "tool_hint": bool(item.metadata.get("_tool_hint")),
                        }))
                    else:
                        await response.write(_sse("done", {"text": item.content}))
                        break
                    continue

                kind = item[0]
                if kind == "token":
                    await response.write(_sse("token", {"text": item[1]}))
                elif kind == "progress":
                    await response.write(_sse("progress", {
                        "text": item[1],
                        "tool_hint": item[2],
                    }))
                elif kind == "done":
                    await response.write(_sse("done", {"text": item[1]}))
                    break
                elif kind == "error":
                    await response.write(_sse("error", {"message": item[1]}))
                    break

        except (asyncio.CancelledError, ConnectionResetError):
            agent_task.cancel()
        finally:
            self._queues.pop(session_id, None)

        return response
