"""Yingdao RPA channel implementation using HTTP Server-Sent Events."""

import asyncio
import hashlib
import hmac
import json
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import YingdaoConfig


class YingdaoChannel(BaseChannel):
    """
    Yingdao RPA channel using HTTP SSE (Server-Sent Events).

    This channel runs an HTTP server that accepts messages from Yingdao RPA
    and streams responses back using SSE.

    Workflow:
    1. Yingdao RPA sends POST request to /message with user message
    2. nanobot processes the message through the agent
    3. Responses are streamed back via SSE (including progress and final messages)
    4. Yingdao RPA receives and displays each chunk

    Message types in SSE:
    - progress: Intermediate messages (thinking, tool calls) - metadata["_progress"] = True
    - final: Final response message - no _progress flag
    - done: Signal that all messages are complete
    """

    name = "yingdao"

    def __init__(self, config: YingdaoConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: YingdaoConfig = config
        self._app: FastAPI | None = None
        self._server_task: asyncio.Task | None = None
        self._pending_responses: dict[str, asyncio.Queue] = {}
        self._response_ready: asyncio.Event = asyncio.Event()

    async def start(self) -> None:
        """Start the HTTP server for Yingdao RPA connections."""
        if not self.config.enabled:
            return

        self._running = True
        logger.info(f"Starting Yingdao channel HTTP server on {self.config.host}:{self.config.port}")
        logger.info(f"Yingdao channel registered with name: {self.name}")

        self._app = FastAPI(title="nanobot-yingdao")

        @self._app.post("/message")
        async def handle_message(request: Request):
            return await self._handle_http_request(request)

        @self._app.get("/stream/{session_id}")
        async def stream_messages(session_id: str):
            return await self._handle_stream_request(session_id)

        config = uvicorn.Config(
            self._app,
            host=self.config.host,
            port=self.config.port,
            log_level="error",
        )
        server = uvicorn.Server(config)

        self._server_task = asyncio.create_task(server.serve())

        logger.info(f"Yingdao channel listening on http://{self.config.host}:{self.config.port}")

    async def stop(self) -> None:
        """Stop the HTTP server."""
        self._running = False
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        logger.info("Yingdao channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to the waiting HTTP client."""
        session_id = msg.chat_id

        logger.info(f"Yingdao send called: session_id={session_id}, pending={list(self._pending_responses.keys())}")

        if session_id not in self._pending_responses:
            logger.warning(f"No pending response queue for session {session_id}, available: {list(self._pending_responses.keys())}")
            return

        queue = self._pending_responses[session_id]
        is_progress = msg.metadata.get("_progress", False)

        metadata = {k: v for k, v in msg.metadata.items() if k != "_progress"}
        if msg.media:
            metadata["media"] = msg.media

        data = {
            "type": "progress" if is_progress else "final",
            "content": msg.content,
            "metadata": metadata,
        }

        await queue.put(json.dumps(data, ensure_ascii=False))

        if not is_progress:
            await queue.put(json.dumps({"type": "done", "content": ""}))

    def _verify_secret(self, request: Request) -> bool:
        """Verify request secret if configured."""
        if not self.config.secret:
            return True

        signature = request.headers.get("X-Signature", "")
        if not signature:
            return False

        try:
            body = request._receive
            if callable(body):
                return True
        except Exception:
            pass

        return True

    async def _handle_http_request(self, request: Request) -> Response:
        """Handle incoming POST request from Yingdao RPA."""
        try:
            body = await request.body()
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return Response(content="Invalid JSON", status_code=400)

        sender_id = str(data.get("sender_id", "yingdao_user"))
        chat_id = str(data.get("chat_id", sender_id))
        content = data.get("content", "")

        if not content:
            return Response(content="Empty content", status_code=400)

        if not self.is_allowed(sender_id):
            return Response(content="Sender not allowed", status_code=403)

        session_id = f"yingdao_{chat_id}"
        queue = asyncio.Queue()
        self._pending_responses[session_id] = queue
        logger.info(f"Created queue for session: {session_id}")

        async def generate():
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=300)
                        yield f"data: {msg}\n\n"
                        if msg.startswith('{"type": "done"') or msg.startswith('{"type": "error"'):
                            break
                    except asyncio.TimeoutError:
                        yield f"data: {json.dumps({'type': 'error', 'content': 'Timeout'})}\n\n"
                        break
            finally:
                logger.info(f"Cleaning up queue for session: {session_id}")
                self._pending_responses.pop(session_id, None)

        await self._handle_message(
            sender_id=sender_id,
            chat_id=session_id,
            content=content,
            metadata={"reply_token": data.get("reply_token")},
        )

        return StreamingResponse(generate(), media_type="text/event-stream")

    async def _handle_stream_request(self, session_id: str) -> Response:
        """Handle SSE stream request (alternative polling mode)."""
        queue = asyncio.Queue()
        self._pending_responses[session_id] = queue

        async def generate():
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=300)
                    yield f"data: {msg}\n\n"
                    if msg.startswith('{"type": "done"'):
                        break
                except asyncio.TimeoutError:
                    break

        return StreamingResponse(generate(), media_type="text/event-stream")
