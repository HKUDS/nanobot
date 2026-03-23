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


# MIME types / extensions treated as readable text (injected into message)
_TEXT_MIMES = frozenset({
    "text/plain", "text/markdown", "text/csv", "text/html", "text/css",
    "text/javascript", "text/x-python", "text/x-sh", "text/x-shellscript",
    "application/json", "application/xml", "application/javascript",
    "application/x-yaml", "application/x-sh",
})
_TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".csv",
    ".yaml", ".yml", ".xml", ".html", ".css", ".sh", ".sql",
    ".rs", ".go", ".java", ".c", ".cpp", ".h", ".rb", ".php",
    ".toml", ".ini", ".conf", ".log",
})


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
    _TEXT_FILE_MAX   = 50_000  # chars read from text files injected into message

    def __init__(self, config: "WebConfig | dict", bus: MessageBus, agent_loop: "AgentLoop | None" = None):
        if isinstance(config, dict):
            config = WebConfig(**config)
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

        # Upload API
        self._app.router.add_post("/api/upload", self._handle_upload)
        self._app.router.add_get("/api/uploads/{path:.+}", self._handle_get_upload)

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

    @property
    def _uploads_dir(self) -> Path:
        return Path.home() / ".nanobot" / "web-uploads"

    def _parse_session_md(self, content: str, session_id: str) -> dict:
        """Parse a session .md file → dict with metadata and history."""
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

        # Prefer the embedded JSON history block (lossless round-trip)
        json_match = re.search(r"<!--JSON\n(\{.*?\})\n-->", body, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                meta["history"] = parsed.get("history", [])
                return meta
            except Exception:
                pass

        # Fallback: parse ### human / ### assistant markdown sections
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
        """Write session dict to .md — embeds full JSON for lossless reload."""
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

        # Embed full JSON history so all fields (hints, attachments, pinned) survive reload
        history = data.get("history", [])
        lines.append("\n<!--JSON\n")
        lines.append(json.dumps({"history": history}) + "\n")
        lines.append("-->\n")

        # Human-readable sections for reviewing in a text editor
        for msg in history:
            role = "human" if msg.get("role") == "user" else "assistant"
            lines.append(f"\n### {role}\n\n")
            atts = msg.get("attachments") or []
            if atts:
                att_names = ", ".join(a.get("name", "?") for a in atts)
                lines.append(f"[attachments: {att_names}]\n\n")
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

    def _find_upload(self, uid: str) -> Path | None:
        """Find an uploaded file by its UUID prefix."""
        matches = list(self._uploads_dir.glob(f"{uid}*"))
        return matches[0] if matches else None

    # ------------------------------------------------------------------
    # Upload handlers
    # ------------------------------------------------------------------

    async def _handle_upload(self, request: web.Request) -> web.Response:
        """Accept a multipart file upload, save it, return {id, name, mime, url}."""
        try:
            reader = await request.multipart()
        except Exception:
            raise web.HTTPBadRequest(reason="Expected multipart/form-data")

        field = await reader.next()
        if field is None or field.name != "file":
            raise web.HTTPBadRequest(reason="Expected field named 'file'")

        filename = field.filename or "upload"
        content = await field.read(decode=True)

        uid = str(uuid.uuid4())
        suffix = Path(filename).suffix.lower()
        # Sanitize suffix — only allow safe alphanumeric extensions
        if not re.match(r"^\.[a-z0-9]+$", suffix):
            suffix = ""

        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        save_path = self._uploads_dir / f"{uid}{suffix}"
        save_path.write_bytes(content)

        mime, _ = mimetypes.guess_type(filename)
        mime = mime or "application/octet-stream"

        return web.Response(
            text=json.dumps({
                "id": uid,
                "name": filename,
                "mime": mime,
                "url": f"/api/uploads/{uid}{suffix}",
            }),
            content_type="application/json",
            status=201,
        )

    async def _handle_get_upload(self, request: web.Request) -> web.Response:
        """Serve an uploaded file by its UUID path."""
        path_info = request.match_info.get("path", "")
        # Validate: must be UUID (optionally + .ext), no path traversal
        uid = path_info.split(".")[0]
        try:
            uuid.UUID(uid)
        except ValueError:
            raise web.HTTPBadRequest()

        upload_path = self._find_upload(uid)
        if not upload_path:
            raise web.HTTPNotFound()

        mime, _ = mimetypes.guess_type(str(upload_path))
        return web.Response(
            body=upload_path.read_bytes(),
            content_type=mime or "application/octet-stream",
        )

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
        """Create a new session (optionally pre-populated for migration)."""
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
            "id": sid, "name": "Chat",
            "created": now, "updated": now, "pinned": False, "history": [],
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
        if self.config.static_dir:
            return Path(self.config.static_dir).expanduser().resolve()
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
        if not str(path).startswith(str(static)):
            raise web.HTTPForbidden()
        if not path.exists() or not path.is_file():
            raise web.HTTPNotFound()
        mime, _ = mimetypes.guess_type(str(path))
        return web.Response(body=path.read_bytes(), content_type=mime or "application/octet-stream")

    async def _handle_stop(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Expected JSON body")
        session_id: str = data.get("session_id", "")
        task = self._agent_tasks.get(session_id)
        if task and not task.done():
            task.cancel()
        return web.Response(text=json.dumps({"ok": True}), content_type="application/json")

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.Response(text=json.dumps({"status": "ok"}), content_type="application/json")

    async def _handle_chat(self, request: web.Request) -> web.StreamResponse:
        """Handle a chat POST and return an SSE stream."""
        try:
            data = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Expected JSON body")

        message: str = data.get("message", "").strip()
        session_id: str = data.get("session_id", "default")
        attachments: list[dict] = data.get("attachments", [])

        if not message and not attachments:
            raise web.HTTPBadRequest(reason="message or attachments required")

        if not self.is_allowed(session_id):
            raise web.HTTPForbidden()

        # Process attachments: images → multimodal image_url blocks, text files → <file> block
        media_paths: list[str] = []
        file_blocks: list[str] = []

        for att in attachments:
            uid = att.get("id", "")
            try:
                uuid.UUID(uid)
            except ValueError:
                continue
            upload_path = self._find_upload(uid)
            if not upload_path:
                continue
            mime = att.get("mime", "") or mimetypes.guess_type(str(upload_path))[0] or ""
            name = att.get("name", upload_path.name)
            if mime.startswith("image/"):
                media_paths.append(str(upload_path))
            elif mime in _TEXT_MIMES or upload_path.suffix.lower() in _TEXT_EXTENSIONS:
                try:
                    text_content = upload_path.read_text(encoding="utf-8", errors="replace")
                    if len(text_content) > self._TEXT_FILE_MAX:
                        text_content = text_content[:self._TEXT_FILE_MAX] + "\n… (truncated)"
                    name = att.get("name", upload_path.name)
                    file_blocks.append(f'<file name="{name}">\n{text_content}\n</file>')
                except Exception:
                    pass

        # Prepend file content blocks to the message text
        if file_blocks:
            prefix = "\n\n".join(file_blocks)
            message = prefix + ("\n\n" + message if message else "")

        # Per-request SSE queue (tokens + bus messages)
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._queues[session_id] = q

        async def on_stream(text: str) -> None:
            await q.put(("token", text))

        _tool_active = [False]  # True once the first tool_call has been emitted

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            if tool_hint:
                tool_name = content.split("(")[0].strip() if "(" in content else content
                await q.put(("tool_call", tool_name, content))
                _tool_active[0] = True
            elif _tool_active[0]:
                await q.put(("tool_stream", content))
            else:
                await q.put(("progress", content, False))

        session_key = f"web:{session_id}"

        async def run_agent() -> None:
            try:
                if self._agent_loop is None:
                    raise RuntimeError("WebChannel has no agent_loop reference")
                result = await self._agent_loop.process_direct(
                    content=message,
                    session_key=session_key,
                    channel=self.name,
                    chat_id=session_id,
                    media=media_paths or None,
                    on_progress=on_progress,
                    on_stream=on_stream,
                )
                final = result.content if result else ""
                await q.put(("done", final or ""))
            except asyncio.CancelledError:
                await q.put(("error", "Request cancelled"))
                raise
            except Exception as exc:
                logger.exception("Web agent error for session {}", session_id)
                await q.put(("error", str(exc)))

        agent_task = asyncio.create_task(run_agent())
        self._agent_tasks[session_id] = agent_task

        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
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
                    await response.write(b": ping\n\n")
                    continue

                if isinstance(item, OutboundMessage):
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
                elif kind == "tool_call":
                    await response.write(_sse("tool_call", {"tool": item[1], "call_str": item[2]}))
                elif kind == "tool_stream":
                    await response.write(_sse("tool_stream", {"text": item[1]}))
                elif kind == "progress":
                    await response.write(_sse("progress", {"text": item[1], "tool_hint": item[2]}))
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
