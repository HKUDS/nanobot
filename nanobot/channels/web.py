"""Web chat channel — HTTP server with SSE token streaming."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import time
import uuid
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

        event: token       — LLM text token (streams live)
        event: progress    — non-tool progress line (rarely fires with streaming)
        event: tool_call   — a tool is about to execute {tool, call_str}
        event: tool_result — tool finished {tool, output, truncated}
        event: done        — turn complete; carries the final cleaned text
        event: error       — something went wrong
    """

    name = "web"
    _TOOL_OUTPUT_MAX = 4_000   # chars forwarded to browser per tool result

    def __init__(self, config: WebConfig, bus: MessageBus, agent_loop: "AgentLoop | None" = None):
        super().__init__(config, bus)
        self.config: WebConfig = config
        self._agent_loop = agent_loop
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        # chat_id (session UUID) → asyncio.Queue for proactive bus messages
        self._queues: dict[str, asyncio.Queue] = {}
        # chat_id → active agent asyncio.Task (for stop support)
        self._agent_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # BaseChannel interface
    # ------------------------------------------------------------------

    @staticmethod
    @web.middleware
    async def _cors_middleware(request: web.Request, handler) -> web.StreamResponse:
        """Add permissive CORS headers to every response."""
        if request.method == "OPTIONS":
            return web.Response(headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            })
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    async def start(self) -> None:
        self._running = True
        self._app = web.Application(middlewares=[self._cors_middleware])

        # Static routes
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/{filename}", self._handle_static)

        # Chat API
        self._app.router.add_post("/api/chat", self._handle_chat)
        self._app.router.add_post("/api/stop", self._handle_stop)
        self._app.router.add_get("/api/health", self._handle_health)

        # Session API
        self._app.router.add_get("/api/sessions", self._handle_get_sessions)
        self._app.router.add_post("/api/sessions", self._handle_create_session)
        self._app.router.add_get("/api/sessions/{id}", self._handle_get_session)
        self._app.router.add_put("/api/sessions/{id}", self._handle_update_session)
        self._app.router.add_patch("/api/sessions/{id}", self._handle_patch_session)
        self._app.router.add_delete("/api/sessions/{id}", self._handle_delete_session)

        # CORS preflight
        self._app.router.add_route("OPTIONS", "/{path_info:.*}", self._handle_options)

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
    # Session file storage
    # ------------------------------------------------------------------

    @property
    def _sessions_dir(self) -> Path:
        return Path.home() / ".nanobot" / "web-sessions"

    def _parse_session_md(self, content: str, session_id: str) -> dict:
        """Parse a session .md file into a dict with metadata and history."""
        meta: dict[str, Any] = {
            "id": session_id,
            "name": "Chat",
            "created": 0,
            "updated": 0,
            "pinned": False,
        }
        body = content

        if content.startswith("---\n"):
            end = content.find("\n---\n", 4)
            if end >= 0:
                fm = content[4:end]
                for line in fm.splitlines():
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        k, v = k.strip(), v.strip()
                        if k == "id":
                            meta["id"] = v
                        elif k == "name":
                            meta["name"] = v
                        elif k == "created":
                            meta["created"] = int(v) if v.isdigit() else 0
                        elif k == "updated":
                            meta["updated"] = int(v) if v.isdigit() else 0
                        elif k == "pinned":
                            meta["pinned"] = v.lower() == "true"
                body = content[end + 5:]

        # Parse ### human / ### assistant sections
        history: list[dict] = []
        parts = re.split(r"^### (human|assistant)\s*$", body, flags=re.MULTILINE)
        i = 1
        while i + 1 < len(parts):
            role = parts[i].strip()
            text = parts[i + 1].strip()
            if text:
                history.append({
                    "role": "user" if role == "human" else "bot",
                    "content": text,
                })
            i += 2

        meta["history"] = history
        return meta

    def _write_session_file(self, data: dict) -> None:
        """Write a session dict to its .md file."""
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self._sessions_dir / f"{data['id']}.md"
        lines: list[str] = ["---\n"]
        lines.append(f"id: {data['id']}\n")
        name = str(data.get("name", "Chat")).replace("\n", " ")
        lines.append(f"name: {name}\n")
        lines.append(f"created: {int(data.get('created', 0))}\n")
        lines.append(f"updated: {int(data.get('updated', 0))}\n")
        lines.append(f"pinned: {'true' if data.get('pinned') else 'false'}\n")
        lines.append("---\n")
        for msg in data.get("history", []):
            role = "human" if msg.get("role") == "user" else "assistant"
            lines.append(f"\n### {role}\n\n")
            lines.append(msg.get("content", "") + "\n")
        path.write_text("".join(lines), encoding="utf-8")

    def _read_session_file(self, session_id: str) -> dict | None:
        path = self._sessions_dir / f"{session_id}.md"
        if not path.exists():
            return None
        try:
            return self._parse_session_md(path.read_text(encoding="utf-8"), session_id)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Session API handlers
    # ------------------------------------------------------------------

    async def _handle_get_sessions(self, request: web.Request) -> web.Response:
        """List all sessions (metadata only, no history)."""
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        sessions = []
        for p in sorted(
            self._sessions_dir.glob("*.md"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            data = self._read_session_file(p.stem)
            if data:
                sessions.append({k: v for k, v in data.items() if k != "history"})
        return web.Response(text=json.dumps(sessions), content_type="application/json")

    async def _handle_get_session(self, request: web.Request) -> web.Response:
        """Get a single session with its full history."""
        sid = request.match_info["id"]
        data = self._read_session_file(sid)
        if not data:
            raise web.HTTPNotFound()
        return web.Response(text=json.dumps(data), content_type="application/json")

    async def _handle_create_session(self, request: web.Request) -> web.Response:
        """Create a new session, optionally pre-populated (used for migration)."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        now = int(time.time() * 1000)
        data = {
            "id": body.get("id") or str(uuid.uuid4()),
            "name": body.get("name", "New chat"),
            "created": body.get("created", now),
            "updated": body.get("updated", now),
            "pinned": bool(body.get("pinned", False)),
            "history": body.get("history", []),
        }
        self._write_session_file(data)
        result = {k: v for k, v in data.items() if k != "history"}
        return web.Response(text=json.dumps(result), content_type="application/json", status=201)

    async def _handle_update_session(self, request: web.Request) -> web.Response:
        """Replace session data (metadata + optional history)."""
        sid = request.match_info["id"]
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Expected JSON body")
        now = int(time.time() * 1000)
        data = self._read_session_file(sid) or {
            "id": sid,
            "name": "Chat",
            "created": now,
            "updated": now,
            "pinned": False,
            "history": [],
        }
        if "name" in body:
            data["name"] = body["name"]
        if "pinned" in body:
            data["pinned"] = bool(body["pinned"])
        if "history" in body:
            data["history"] = body["history"]
        data["updated"] = now
        self._write_session_file(data)
        return web.Response(
            text=json.dumps({k: v for k, v in data.items() if k != "history"}),
            content_type="application/json",
        )

    async def _handle_patch_session(self, request: web.Request) -> web.Response:
        """Partially update session metadata (name, pinned, touch)."""
        sid = request.match_info["id"]
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Expected JSON body")
        data = self._read_session_file(sid)
        if not data:
            raise web.HTTPNotFound()
        if "name" in body:
            data["name"] = body["name"]
        if "pinned" in body:
            data["pinned"] = bool(body["pinned"])
        data["updated"] = int(time.time() * 1000)
        self._write_session_file(data)
        return web.Response(
            text=json.dumps({k: v for k, v in data.items() if k != "history"}),
            content_type="application/json",
        )

    async def _handle_delete_session(self, request: web.Request) -> web.Response:
        """Delete a session file."""
        sid = request.match_info["id"]
        path = self._sessions_dir / f"{sid}.md"
        if path.exists():
            path.unlink()
        return web.Response(text=json.dumps({"ok": True}), content_type="application/json")

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

    async def _handle_options(self, request: web.Request) -> web.Response:
        return web.Response(headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        })

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

    async def _handle_stop(self, request: web.Request) -> web.Response:
        """Cancel the active agent task for a session."""
        try:
            data = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Expected JSON body")
        session_id: str = data.get("session_id", "")
        task = self._agent_tasks.get(session_id)
        if task and not task.done():
            task.cancel()
        return web.Response(
            text=json.dumps({"ok": True}),
            content_type="application/json",
        )

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

        async def on_tool_call(tool_name: str, call_str: str, arguments: dict) -> None:
            await q.put(("tool_call", tool_name, call_str, arguments))

        async def on_tool_result(tool_name: str, output: str) -> None:
            truncated = len(output) > self._TOOL_OUTPUT_MAX
            await q.put(("tool_result", tool_name, output[:self._TOOL_OUTPUT_MAX], truncated))

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
                    on_tool_call=on_tool_call,
                    on_tool_result=on_tool_result,
                )
                await q.put(("done", final or ""))
            except asyncio.CancelledError:
                await q.put(("error", "Request cancelled"))
                raise
            except Exception as exc:
                logger.exception("Web agent error for session {}", session_id)
                await q.put(("error", str(exc)))

        agent_task = asyncio.create_task(run_agent())
        self._agent_tasks[session_id] = agent_task

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
                elif kind == "tool_call":
                    await response.write(_sse("tool_call", {
                        "tool": item[1],
                        "call_str": item[2],
                        "args": item[3],
                    }))
                elif kind == "tool_result":
                    await response.write(_sse("tool_result", {
                        "tool": item[1],
                        "output": item[2],
                        "truncated": item[3],
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
            self._agent_tasks.pop(session_id, None)

        return response
