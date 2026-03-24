"""Thin HTTP API for direct chat access with persistent sessions."""

from __future__ import annotations

import asyncio
from collections import defaultdict
import json
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.paths import get_cron_dir
from nanobot.config.schema import Config
from nanobot.cron.service import CronService
from nanobot.session.manager import SessionManager


class HttpApiServer:
    """Expose a minimal local HTTP API backed by the main agent loop."""

    def __init__(
        self,
        agent: AgentLoop,
        host: str = "127.0.0.1",
        port: int = 18789,
        token: str | None = None,
    ) -> None:
        self.agent = agent
        self.host = host
        self.port = port
        self.token = token or ""
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._session_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        self.app = web.Application()
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_post("/chat", self.handle_chat)
        self.app.router.add_post("/chat/stream", self.handle_chat_stream)

    async def start(self) -> None:
        """Start serving HTTP requests."""
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info("HTTP API listening on http://{}:{}", self.host, self.port)

    async def stop(self) -> None:
        """Stop the server and release resources."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    async def serve_forever(self) -> None:
        """Run until cancelled."""
        await self.start()
        try:
            await asyncio.Event().wait()
        finally:
            await self.stop()

    async def handle_health(self, request: web.Request) -> web.Response:
        """Simple liveness endpoint."""
        return web.json_response({"ok": True})

    async def handle_chat(self, request: web.Request) -> web.StreamResponse | web.Response:
        """Process one chat turn using a stable session id."""
        payload, error = await self._parse_chat_request(request)
        if error is not None:
            return error
        if payload["stream"]:
            return await self._stream_chat(request, payload)

        async with self._session_locks[payload["session_key"]]:
            reply = await self.agent.process_direct(
                content=payload["message"],
                session_key=payload["session_key"],
                channel=payload["channel"],
                chat_id=payload["chat_id"],
            )

        return web.json_response(
            {
                "session_id": payload["session_id"],
                "session_key": payload["session_key"],
                "reply": reply,
            }
        )

    async def handle_chat_stream(self, request: web.Request) -> web.StreamResponse | web.Response:
        """Stream progress and the final reply as SSE events."""
        payload, error = await self._parse_chat_request(request)
        if error is not None:
            return error
        return await self._stream_chat(request, payload)

    async def _stream_chat(
        self,
        request: web.Request,
        payload: dict[str, Any],
    ) -> web.StreamResponse:
        """Shared SSE implementation for /chat and /chat/stream."""
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        queue: asyncio.Queue[tuple[str, dict[str, Any] | None]] = asyncio.Queue()

        async def _on_progress(content: str, *, tool_hint: bool = False) -> None:
            await queue.put((
                "progress",
                {
                    "content": content,
                    "tool_hint": tool_hint,
                },
            ))

        async def _run() -> None:
            try:
                async with self._session_locks[payload["session_key"]]:
                    reply = await self.agent.process_direct(
                        content=payload["message"],
                        session_key=payload["session_key"],
                        channel=payload["channel"],
                        chat_id=payload["chat_id"],
                        on_progress=_on_progress,
                    )
                await queue.put((
                    "final",
                    {
                        "session_id": payload["session_id"],
                        "session_key": payload["session_key"],
                        "reply": reply,
                    },
                ))
            except Exception:
                logger.exception("HTTP stream failed for session {}", payload["session_key"])
                await queue.put(("error", {"error": "internal_error"}))
            finally:
                await queue.put(("done", {}))

        task = asyncio.create_task(_run())
        try:
            while True:
                event, data = await queue.get()
                await response.write(self._format_sse_event(event, data))
                if event == "done":
                    break
        except (ConnectionResetError, asyncio.CancelledError):
            task.cancel()
            raise
        finally:
            await asyncio.gather(task, return_exceptions=True)
            await response.write_eof()

        return response

    def _auth_error(self, request: web.Request) -> web.Response | None:
        """Return a 401 response when bearer auth is enabled and invalid."""
        if not self.token:
            return None
        expected = f"Bearer {self.token}"
        if request.headers.get("Authorization", "") != expected:
            return web.json_response({"error": "unauthorized"}, status=401)
        return None

    async def _parse_chat_request(
        self,
        request: web.Request,
    ) -> tuple[dict[str, Any] | None, web.Response | None]:
        """Validate and normalize one chat request body."""
        auth_error = self._auth_error(request)
        if auth_error is not None:
            return None, auth_error

        try:
            body = await request.json()
        except Exception:
            return None, web.json_response({"error": "invalid_json"}, status=400)

        if not isinstance(body, dict):
            return None, web.json_response({"error": "invalid_payload"}, status=400)

        session_id = str(body.get("session_id") or body.get("sessionId") or "").strip()
        message = body.get("message")
        if message is None:
            message = body.get("input")
        if not isinstance(message, str):
            message = "" if message is None else str(message)
        message = message.strip()

        if not session_id:
            return None, web.json_response({"error": "session_id_required"}, status=400)
        if not message:
            return None, web.json_response({"error": "message_required"}, status=400)

        channel = str(body.get("channel") or "http").strip() or "http"
        chat_id = str(body.get("chat_id") or body.get("chatId") or session_id).strip() or session_id
        session_key = str(
            body.get("session_key")
            or body.get("sessionKey")
            or f"{channel}:{session_id}"
        ).strip()
        stream = body.get("stream", False) is True

        return {
            "session_id": session_id,
            "message": message,
            "channel": channel,
            "chat_id": chat_id,
            "session_key": session_key,
            "stream": stream,
        }, None

    @staticmethod
    def _format_sse_event(event: str, data: dict[str, Any] | None) -> bytes:
        """Encode one SSE event."""
        payload = json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"))
        return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


async def run_http_api(
    config: Config,
    host: str = "127.0.0.1",
    port: int = 18789,
    token: str | None = None,
) -> None:
    """Run the local HTTP API until interrupted."""
    from nanobot.cli.commands import _make_provider

    http_cfg = config.gateway.http_api
    host = host or http_cfg.host
    port = port or http_cfg.port
    token = token if token is not None else (http_cfg.token or None)

    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)
    cron = CronService(get_cron_dir() / "jobs.json")
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
    )
    server = HttpApiServer(agent=agent, host=host, port=port, token=token)

    try:
        await cron.start()
        await server.serve_forever()
    finally:
        await agent.close_mcp()
        cron.stop()
        agent.stop()
        await server.stop()
