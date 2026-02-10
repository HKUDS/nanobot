"""OpenAI-Compatible HTTP Server channel."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from aiohttp import web
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage, StreamChunk
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import OpenAPIConfig

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


class OpenAPIChannel(BaseChannel):
    """
    OpenAI-Compatible HTTP Server channel.

    Provides a /v1/chat/completions endpoint that accepts OpenAI-format
    requests and returns OpenAI-format responses (both streaming and non-streaming).
    """

    name = "openapi"

    def __init__(
        self,
        config: OpenAPIConfig,
        bus: MessageBus,
        session_manager: SessionManager | None = None,
    ):
        super().__init__(config, bus)
        self.config: OpenAPIConfig = config
        self.session_manager = session_manager
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

        # Futures waiting for non-streaming responses
        self._pending_responses: dict[str, asyncio.Future[str]] = {}

    async def start(self) -> None:
        """Start the HTTP server."""
        self._running = True

        # Create aiohttp application
        self._app = web.Application()
        self._app.router.add_post("/v1/chat/completions", self._handle_chat_completions)
        self._app.router.add_get("/health", self._handle_health)

        # Subscribe to outbound messages (for non-streaming responses)
        self.bus.subscribe_outbound(self.name, self._on_outbound)

        # Start server
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await self._site.start()

        logger.info(
            f"OpenAPI server started at http://{self.config.host}:{self.config.port}"
        )

        # Keep running
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the HTTP server."""
        self._running = False

        # Cancel all pending requests
        for future in self._pending_responses.values():
            if not future.done():
                future.cancel()
        self._pending_responses.clear()

        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        logger.info("OpenAPI server stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """
        Receive outbound message from agent.

        Called by the bus dispatcher for non-streaming responses.
        """
        await self._on_outbound(msg)

    async def _on_outbound(self, msg: OutboundMessage) -> None:
        """Handle outbound message - resolve pending future."""
        future = self._pending_responses.pop(msg.chat_id, None)
        if future and not future.done():
            future.set_result(msg.content)

    def _verify_api_key(self, request: web.Request) -> bool:
        """Verify API key from Authorization header."""
        if not self.config.api_keys:
            return True  # No keys configured, allow all

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False

        token = auth_header[7:]  # Remove "Bearer " prefix
        return token in self.config.api_keys

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "ok"})

    async def _handle_chat_completions(
        self, request: web.Request
    ) -> web.StreamResponse:
        """
        Handle POST /v1/chat/completions

        Supports both streaming and non-streaming responses.
        """
        # Verify API Key
        if not self._verify_api_key(request):
            return web.json_response(
                {
                    "error": {
                        "message": "Invalid API key",
                        "type": "invalid_request_error",
                    }
                },
                status=401,
            )

        # Parse request
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}},
                status=400,
            )

        messages = body.get("messages", [])
        stream = body.get("stream", False)
        user = body.get("user", "anonymous")

        if not messages:
            return web.json_response(
                {
                    "error": {
                        "message": "messages is required",
                        "type": "invalid_request_error",
                    }
                },
                status=400,
            )

        # Extract last user message as content
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_content = content
                elif isinstance(content, list):
                    # Handle multimodal content
                    text_parts = [
                        p.get("text", "") for p in content if p.get("type") == "text"
                    ]
                    user_content = "\n".join(text_parts)
                break

        if not user_content:
            return web.json_response(
                {
                    "error": {
                        "message": "No user message found",
                        "type": "invalid_request_error",
                    }
                },
                status=400,
            )

        # Check user permission
        if not self.is_allowed(user):
            return web.json_response(
                {"error": {"message": "User not allowed", "type": "permission_error"}},
                status=403,
            )

        # Generate unique IDs
        request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        chat_id = f"{user}:{uuid.uuid4().hex[:8]}"

        if stream:
            return await self._handle_stream(
                request_id, chat_id, user, user_content, request
            )
        else:
            return await self._handle_non_stream(
                request_id, chat_id, user, user_content
            )

    async def _handle_non_stream(
        self,
        request_id: str,
        chat_id: str,
        user: str,
        content: str,
    ) -> web.Response:
        """Handle non-streaming request."""
        # Create future to wait for response
        future: asyncio.Future[str] = asyncio.Future()
        self._pending_responses[chat_id] = future

        # Send message to bus
        await self._handle_message(
            sender_id=user,
            chat_id=chat_id,
            content=content,
        )

        # Wait for response
        try:
            response_content = await asyncio.wait_for(
                future, timeout=self.config.timeout
            )
        except asyncio.TimeoutError:
            self._pending_responses.pop(chat_id, None)
            return web.json_response(
                {"error": {"message": "Request timeout", "type": "timeout_error"}},
                status=504,
            )
        except asyncio.CancelledError:
            return web.json_response(
                {"error": {"message": "Request cancelled", "type": "cancelled_error"}},
                status=499,
            )

        # Build OpenAI format response
        response = {
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.config.model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": response_content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": len(content) // 4,  # Estimate
                "completion_tokens": len(response_content) // 4,
                "total_tokens": (len(content) + len(response_content)) // 4,
            },
        }

        return web.json_response(response)

    async def _handle_stream(
        self,
        request_id: str,
        chat_id: str,
        user: str,
        content: str,
        request: web.Request,
    ) -> web.StreamResponse:
        """Handle streaming request."""
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        # Queue for collecting stream chunks
        chunk_queue: asyncio.Queue[StreamChunk | None] = asyncio.Queue()

        async def stream_callback(chunk: StreamChunk) -> None:
            """Receive stream data and put into queue."""
            await chunk_queue.put(chunk)
            if chunk.is_final:
                await chunk_queue.put(None)  # Termination signal

        # Send message with stream callback
        msg = InboundMessage(
            channel=self.name,
            sender_id=user,
            chat_id=chat_id,
            content=content,
            stream_callback=stream_callback,
        )

        await self.bus.publish_inbound(msg)

        # Read from queue and send SSE
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        chunk_queue.get(), timeout=self.config.timeout
                    )
                except asyncio.TimeoutError:
                    error_data = json.dumps(
                        {
                            "error": {
                                "message": "Stream timeout",
                                "type": "timeout_error",
                            }
                        }
                    )
                    await response.write(f"data: {error_data}\n\n".encode())
                    break

                if chunk is None:
                    break

                # Build SSE data
                sse_data: dict[str, Any] = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": self.config.model_name,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                }

                if chunk.content:
                    sse_data["choices"][0]["delta"]["content"] = chunk.content

                if chunk.is_final:
                    sse_data["choices"][0]["finish_reason"] = (
                        chunk.finish_reason or "stop"
                    )
                    sse_data["choices"][0]["delta"] = {}

                await response.write(f"data: {json.dumps(sse_data)}\n\n".encode())

            # Send done marker
            await response.write(b"data: [DONE]\n\n")

        except Exception as e:
            logger.error(f"Stream error: {e}")
            error_data = json.dumps({"error": {"message": str(e)}})
            await response.write(f"data: {error_data}\n\n".encode())
            await response.write(b"data: [DONE]\n\n")

        return response
