"""Web chat channel — HTTP server with SSE token streaming via message bus."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import time
import uuid
from pathlib import Path
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


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


def _sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


class WebChannel(BaseChannel):
    """HTTP channel with Server-Sent Events for token-level streaming.

    Uses the standard nanobot message bus for all agent communication —
    no modifications to core agent files required.

    Each browser tab gets a UUID session (stored in localStorage).
    POST /api/chat returns an SSE stream:

        event: token    — LLM text token (streams live)
        event: progress — tool hint or brief status text  {text, tool_hint}
        event: done     — turn complete; carries the final cleaned text
        event: error    — something went wrong
    """

    name = "web"
    display_name = "Web Chat"

    _TOOL_OUTPUT_MAX = 4_000   # chars forwarded to browser per tool result
    _TEXT_FILE_MAX   = 50_000  # chars read from text files injected into message

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        cfg = config if isinstance(config, dict) else vars(config)
        self._host: str = cfg.get("host", "0.0.0.0")
        self._port: int = int(cfg.get("port", 8080))
        raw_static = cfg.get("staticDir") or cfg.get("static_dir", "")
        self._static_path: str = str(raw_static) if raw_static else ""
        self._allow_from: list = cfg.get("allowFrom") or cfg.get("allow_from") or ["*"]

        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        # session_id → asyncio.Queue  (SSE drain loop reads from this)
        self._queues: dict[str, asyncio.Queue] = {}

    # ------------------------------------------------------------------
    # BaseChannel interface
    # ------------------------------------------------------------------

    def is_allowed(self, sender_id: str) -> bool:
        if not self._allow_from or "*" in self._allow_from:
            return True
        return str(sender_id) in self._allow_from

    async def send(self, msg: OutboundMessage) -> None:
        """Route bus outbound messages into the waiting SSE queue."""
        q = self._queues.get(msg.chat_id)
        if q is None:
            return
        await q.put(msg)

    async def start(self) -> None:
        self._running = True

        self._app = web.Application(middlewares=[self._cors_middleware])

        # Static content
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/{filename}", self._handle_static)

        # Chat + lifecycle
        self._app.router.add_post("/api/chat", self._handle_chat)
        self._app.router.add_post("/api/stop", self._handle_stop)
        self._app.router.add_get("/api/health", self._handle_health)

        # File uploads
        self._app.router.add_post("/api/upload", self._handle_upload)
        self._app.router.add_get("/api/uploads/{path:.+}", self._handle_get_upload)

        # Session CRUD
        self._app.router.add_get("/api/sessions", self._handle_get_sessions)
        self._app.router.add_post("/api/sessions", self._handle_create_session)
        self._app.router.add_get("/api/sessions/{id}", self._handle_get_session)
        self._app.router.add_put("/api/sessions/{id}", self._handle_update_session)
        self._app.router.add_patch("/api/sessions/{id}", self._handle_patch_session)
        self._app.router.add_delete("/api/sessions/{id}", self._handle_delete_session)

        self._app.router.add_route("OPTIONS", "/{path_info:.*}", self._handle_options)

        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("Web channel listening on {}:{}", self._host, self._port)

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # ------------------------------------------------------------------
    # CORS middleware
    # ------------------------------------------------------------------

    @staticmethod
    @web.middleware
    async def _cors_middleware(request: web.Request, handler) -> web.StreamResponse:
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

    async def _handle_options(self, request: web.Request) -> web.Response:
        return web.Response(headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        })

    # ------------------------------------------------------------------
    # Static file serving
    # ------------------------------------------------------------------

    def _get_static_dir(self) -> Path:
        if self._static_path:
            return Path(self._static_path).expanduser().resolve()
        # Bundled inside the installed package (nanobot/web/)
        pkg_web = Path(__file__).parent.parent / "web"
        if pkg_web.is_dir():
            return pkg_web
        # Development fallback: web/ at the repo root
        repo_root = Path(__file__).parent.parent.parent
        candidate = repo_root / "web"
        return candidate if candidate.is_dir() else Path.cwd() / "web"

    async def _handle_index(self, request: web.Request) -> web.Response:
        return await self._serve_static_file("index.html")

    async def _handle_static(self, request: web.Request) -> web.Response:
        return await self._serve_static_file(request.match_info["filename"])

    async def _serve_static_file(self, filename: str) -> web.Response:
        static = self._get_static_dir()
        path = (static / filename).resolve()
        if not str(path).startswith(str(static)):
            raise web.HTTPForbidden()
        if not path.exists() or not path.is_file():
            raise web.HTTPNotFound()
        mime, _ = mimetypes.guess_type(str(path))
        return web.Response(body=path.read_bytes(), content_type=mime or "application/octet-stream")

    # ------------------------------------------------------------------
    # Health + stop
    # ------------------------------------------------------------------

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.Response(text=json.dumps({"status": "ok"}), content_type="application/json")

    async def _handle_stop(self, request: web.Request) -> web.Response:
        """Signal the agent loop to stop the current session via the bus."""
        try:
            data = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Expected JSON body")
        session_id: str = data.get("session_id", "")
        if session_id:
            # Close the SSE stream immediately from the client's perspective
            q = self._queues.get(session_id)
            if q:
                await q.put(None)  # sentinel → SSE loop closes
            # Ask the agent loop to cancel the session via the /stop command
            await self.bus.publish_inbound(InboundMessage(
                channel=self.name,
                sender_id="web",
                chat_id=session_id,
                content="/stop",
            ))
        return web.Response(text=json.dumps({"ok": True}), content_type="application/json")

    # ------------------------------------------------------------------
    # Chat SSE endpoint
    # ------------------------------------------------------------------

    async def _handle_chat(self, request: web.Request) -> web.StreamResponse:
        """Accept a chat POST and return an SSE stream backed by the agent bus."""
        try:
            data = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Expected JSON body")

        message: str = data.get("message", "").strip()
        session_id: str = data.get("session_id", str(uuid.uuid4()))
        attachments: list[dict] = data.get("attachments", [])

        if not message and not attachments:
            raise web.HTTPBadRequest(reason="message or attachments required")

        if not self.is_allowed(session_id):
            raise web.HTTPForbidden()

        # Resolve attachments → media paths (images) or <file> blocks (text)
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
                    file_blocks.append(f'<file name="{name}">\n{text_content}\n</file>')
                except Exception:
                    pass

        if file_blocks:
            prefix = "\n\n".join(file_blocks)
            message = prefix + ("\n\n" + message if message else "")

        # Register an SSE queue for this session before publishing so send()
        # can start delivering stream deltas as soon as the loop picks up the message.
        q: asyncio.Queue = asyncio.Queue()
        self._queues[session_id] = q

        # Publish inbound message to the agent bus.
        # _wants_stream: True tells _dispatch() to route token deltas back via bus.
        await self.bus.publish_inbound(InboundMessage(
            channel=self.name,
            sender_id="web",
            chat_id=session_id,
            content=message,
            media=media_paths,
        ))

        # Set up the SSE response
        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })
        response.enable_chunked_encoding()
        await response.prepare(request)

        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=120)
                except asyncio.TimeoutError:
                    await response.write(b": ping\n\n")
                    continue

                # None sentinel → stop requested
                if item is None:
                    await response.write(_sse("error", {"message": "Stopped"}))
                    break

                # OutboundMessage from the bus
                meta = item.metadata or {}

                if meta.get("_progress"):
                    await response.write(_sse("progress", {
                        "text": item.content,
                        "tool_hint": bool(meta.get("_tool_hint")),
                    }))

                else:
                    # Final complete response
                    await response.write(_sse("done", {"text": item.content}))
                    break

        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self._queues.pop(session_id, None)

        return response

    # ------------------------------------------------------------------
    # Upload handlers
    # ------------------------------------------------------------------

    @property
    def _uploads_dir(self) -> Path:
        return Path.home() / ".nanobot" / "web-uploads"

    def _find_upload(self, uid: str) -> Path | None:
        matches = list(self._uploads_dir.glob(f"{uid}*"))
        return matches[0] if matches else None

    async def _handle_upload(self, request: web.Request) -> web.Response:
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
        path_info = request.match_info.get("path", "")
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
    # Session storage
    # ------------------------------------------------------------------

    @property
    def _sessions_dir(self) -> Path:
        return Path.home() / ".nanobot" / "web-sessions"

    def _parse_session_md(self, content: str, session_id: str) -> dict:
        meta: dict[str, Any] = {
            "id": session_id, "name": "Chat",
            "created": 0, "updated": 0, "pinned": False,
        }
        body = content
        if content.startswith("---\n"):
            end = content.find("\n---\n", 4)
            if end >= 0:
                for line in content[4:end].splitlines():
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

        json_match = re.search(r"<!--JSON\n(\{.*?\})\n-->", body, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                meta["history"] = parsed.get("history", [])
                return meta
            except Exception:
                pass

        history: list[dict] = []
        parts = re.split(r"^### (human|assistant)\s*$", body, flags=re.MULTILINE)
        i = 1
        while i + 1 < len(parts):
            role = parts[i].strip()
            text = parts[i + 1].strip()
            if text:
                history.append({"role": "user" if role == "human" else "bot", "content": text})
            i += 2
        meta["history"] = history
        return meta

    def _write_session_file(self, data: dict) -> None:
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self._sessions_dir / f"{data['id']}.md"
        lines: list[str] = [
            "---\n",
            f"id: {data['id']}\n",
            f"name: {str(data.get('name', 'Chat')).replace(chr(10), ' ')}\n",
            f"created: {int(data.get('created', 0))}\n",
            f"updated: {int(data.get('updated', 0))}\n",
            f"pinned: {'true' if data.get('pinned') else 'false'}\n",
            "---\n",
            "\n<!--JSON\n",
            json.dumps({"history": data.get("history", [])}) + "\n",
            "-->\n",
        ]
        for msg in data.get("history", []):
            role = "human" if msg.get("role") == "user" else "assistant"
            lines.append(f"\n### {role}\n\n{msg.get('content', '')}\n")
        path.write_text("".join(lines), encoding="utf-8")

    def _read_session_file(self, session_id: str) -> dict | None:
        path = self._sessions_dir / f"{session_id}.md"
        if not path.exists():
            return None
        try:
            return self._parse_session_md(path.read_text(encoding="utf-8"), session_id)
        except Exception:
            return None

    async def _handle_get_sessions(self, request: web.Request) -> web.Response:
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        sessions = []
        for p in sorted(self._sessions_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
            data = self._read_session_file(p.stem)
            if data:
                sessions.append({k: v for k, v in data.items() if k != "history"})
        return web.Response(text=json.dumps(sessions), content_type="application/json")

    async def _handle_get_session(self, request: web.Request) -> web.Response:
        data = self._read_session_file(request.match_info["id"])
        if not data:
            raise web.HTTPNotFound()
        return web.Response(text=json.dumps(data), content_type="application/json")

    async def _handle_create_session(self, request: web.Request) -> web.Response:
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
        return web.Response(
            text=json.dumps({k: v for k, v in data.items() if k != "history"}),
            content_type="application/json", status=201,
        )

    async def _handle_update_session(self, request: web.Request) -> web.Response:
        sid = request.match_info["id"]
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Expected JSON body")
        now = int(time.time() * 1000)
        data = self._read_session_file(sid) or {
            "id": sid, "name": "Chat", "created": now, "updated": now, "pinned": False, "history": [],
        }
        for field in ("name", "pinned", "history"):
            if field in body:
                data[field] = bool(body[field]) if field == "pinned" else body[field]
        data["updated"] = now
        self._write_session_file(data)
        return web.Response(
            text=json.dumps({k: v for k, v in data.items() if k != "history"}),
            content_type="application/json",
        )

    async def _handle_patch_session(self, request: web.Request) -> web.Response:
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
        path = self._sessions_dir / f"{request.match_info['id']}.md"
        if path.exists():
            path.unlink()
        return web.Response(text=json.dumps({"ok": True}), content_type="application/json")
