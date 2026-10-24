"""Rokid Rizon Platform SSE Channel — Connect to Rokid AI Glasses via SSE protocol.
Rokid 灵珠平台 SSE Channel —— 通过 SSE 协议接入 Rokid AI 眼镜.

The Rizon platform (https://rizon.rokid.com/) sends user voice/text input to a
configured custom URL via SSE (Server-Sent Events), and the server streams back
AI responses through SSE.
灵珠平台 (https://rizon.rokid.com/) 通过 SSE (Server-Sent Events) 向配置的
自定义 URL 发送用户语音/文本输入，服务器通过 SSE 流式返回 AI 响应。

Official protocol format / 官方协议格式:
  Request / 请求: POST /metis/agent/api/sse
    {
      "message_id": "1021",
      "agent_id": "40b8cc2b2f7843feb8cfe17b8921b877",
      "user_id": "用户ID",
      "metadata": {
        "context": {
          "location": "...", "latitude": "...", "longitude": "...",
          "currentTime": "...", "weather": "...", "battery": "..."
        }
      },
      "message": [
        {"role": "user", "type": "text", "text": "..."},
        {"role": "user", "type": "image", "text": "https://..."}
      ]
    }

  Response / 响应: SSE stream
    event:message
    data:{"role":"agent","type":"answer","answer_stream":"...","message_id":"1021","is_finish":false}

Configuration example / 配置示例 (nanobot.yaml):
    channels:
      rokid_sse:
        enabled: true
        host: "0.0.0.0"
        port: 18791
        auth_key: "your-secret-key"
        timeout: 120
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from rich.console import Console

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.channels.base import BaseChannel

logger = logging.getLogger(__name__)
console = Console()

# Lazy import aiohttp to avoid hard dependency when channel is disabled
web: Any = None  # type: ignore


def _import_aiohttp() -> Any:
    """Lazy import aiohttp.web to avoid import-time dependency."""
    global web
    if web is None:
        from aiohttp import web as _web

        web = _web
    return web


class RokidSSEChannel(BaseChannel):
    """Channel for Rokid Lingzhu (灵珠) platform via SSE protocol."""

    name = "rokid_sse"
    display_name = "Rokid SSE"

    def __init__(self, config: dict, bus: Any) -> None:
        super().__init__(config, bus)
        self.host = config.get("host", "0.0.0.0")
        self.port = config.get("port", 18791)
        self.auth_key = config.get("auth_key", "")
        self.timeout = config.get("timeout", 120)

        # HTTP server state
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

        # Per-request queues keyed by message_id (Lingzhu has no session_id)
        self._session_queues: dict[str, asyncio.Queue[OutboundMessage]] = {}

    # ── Lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        """Start the aiohttp SSE server."""
        _import_aiohttp()
        self._app = web.Application()
        self._app.router.add_post("/v1/rokid/sse", self._handle_sse)
        self._app.router.add_get("/v1/rokid/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        console.print(
            f"[green]✓[/green] Rokid SSE channel listening on "
            f"http://{self.host}:{self.port}/v1/rokid/sse"
        )

    async def stop(self) -> None:
        """Stop the aiohttp server."""
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    # ── SSE Handlers ────────────────────────────────────────────

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint for the Rokid SSE channel."""
        return web.json_response({"status": "ok", "channel": self.name})

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """Handle incoming SSE requests from Rokid Lingzhu platform."""
        # ── Auth check ──
        if self.auth_key:
            provided = request.headers.get("Authorization", "")
            if provided != f"Bearer {self.auth_key}":
                return web.Response(status=401, text="Unauthorized")

        # ── Parse request body ──
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.Response(status=400, text="Invalid JSON body")

        if not isinstance(body, dict):
            return web.Response(status=400, text="JSON body must be an object")

        # ── Extract official fields ──
        message_id = body.get("message_id", "")
        agent_id = body.get("agent_id", "")
        user_id = body.get("user_id", "")
        metadata = body.get("metadata", {})
        raw_messages = body.get("message", [])

        if not message_id:
            return web.Response(status=400, text="Missing message_id")

        # Build user content from message array (text + image URLs)
        user_message = self._extract_message(raw_messages)
        image_urls = self._extract_image_urls(raw_messages)

        # If images present, prepend markdown image links before text
        content_parts: list[str] = []
        for url in image_urls:
            content_parts.append(f"![image]({url})")
        if user_message:
            content_parts.append(user_message)
        full_content = "\n".join(content_parts)

        if not full_content:
            return web.Response(status=400, text="Missing message content")

        # Lingzhu has no session_id; register queue under multiple keys
        # so that agent-loop outbound routing (which may use chat_id or
        # session_key_override) can find it.
        session_key = message_id
        fallback_key = f"{self.name}:{user_id}"

        # Create a dedicated queue for this request
        session_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._session_queues[session_key] = session_queue
        self._session_queues[fallback_key] = session_queue

        # ── Prepare SSE response ──
        response = web.StreamResponse()
        response.headers["Content-Type"] = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Connection"] = "keep-alive"
        response.headers["X-Accel-Buffering"] = "no"  # Disable nginx buffering
        await response.prepare(request)

        # ── Process via MessageBus ──
        start_time = time.monotonic()
        full_text_parts: list[str] = []

        try:
            # Publish inbound message
            inbound_msg = InboundMessage(
                channel=self.name,
                sender_id=user_id,
                chat_id=user_id,
                content=full_content,
                metadata={
                    "rokid_body": body,
                    "message_id": message_id,
                    "agent_id": agent_id,
                    "context": metadata.get("context", {}),
                },
                session_key_override=session_key,
            )
            await self.bus.publish_inbound(inbound_msg)

            # Collect outbound messages via the session queue
            while True:
                elapsed = time.monotonic() - start_time
                remaining = self.timeout - elapsed
                if remaining <= 0:
                    logger.warning(
                        "Rokid SSE session %s timed out after %ds",
                        session_key,
                        self.timeout,
                    )
                    break

                try:
                    msg: OutboundMessage = await asyncio.wait_for(
                        session_queue.get(), timeout=min(remaining, 5.0)
                    )
                except asyncio.TimeoutError:
                    # No new messages for 5s — if we already have content, treat as done
                    if full_text_parts:
                        break
                    continue

                if msg.content:
                    full_text_parts.append(msg.content)
                    # Stream each delta with is_finish=false
                    await self._write_lingzhu_sse(
                        response,
                        answer_stream=msg.content,
                        message_id=message_id,
                        is_finish=False,
                    )

            # Send final completion event with is_finish=true
            await self._write_lingzhu_sse(
                response,
                answer_stream="",
                message_id=message_id,
                is_finish=True,
            )

        except asyncio.CancelledError:
            logger.info("Rokid SSE session %s cancelled", session_key)
            raise
        except Exception as exc:
            logger.exception("Rokid SSE session %s error: %s", session_key, exc)
            await self._write_lingzhu_sse(
                response,
                answer_stream=f"[Error: {exc}]",
                message_id=message_id,
                is_finish=True,
            )
        finally:
            self._session_queues.pop(session_key, None)
            self._session_queues.pop(fallback_key, None)

        return response

    # ── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _extract_message(raw_messages: list[dict[str, Any]]) -> str:
        """Extract text content from Lingzhu message array.

        Only items with type="text" are included.
        """
        if not isinstance(raw_messages, list):
            return ""
        texts = []
        for item in raw_messages:
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text", "")
                if isinstance(t, str):
                    texts.append(t)
        return "\n".join(texts)

    @staticmethod
    def _extract_image_urls(raw_messages: list[dict[str, Any]]) -> list[str]:
        """Extract image URLs from Lingzhu message array.

        Lingzhu puts the image URL in the 'text' field for type='image'.
        """
        if not isinstance(raw_messages, list):
            return []
        urls = []
        for item in raw_messages:
            if isinstance(item, dict) and item.get("type") == "image":
                url = item.get("text", "")
                if isinstance(url, str) and url.startswith("http"):
                    urls.append(url)
        return urls

    @staticmethod
    async def _write_lingzhu_sse(
        response: web.StreamResponse,
        answer_stream: str,
        message_id: str,
        is_finish: bool,
    ) -> None:
        """Write a single Lingzhu-format SSE event.

        Official format:
            event:message
            data:{"role":"agent","type":"answer","answer_stream":"...","message_id":"...","is_finish":false}
        """
        payload = {
            "role": "agent",
            "type": "answer",
            "answer_stream": answer_stream,
            "message_id": message_id,
            "is_finish": is_finish,
        }
        data = json.dumps(payload, ensure_ascii=False)
        chunk = f"event:message\ndata:{data}\n\n"
        await response.write(chunk.encode("utf-8"))
        await response.drain()

    # ── Channel interface (outbound routing) ────────────────────

    async def send(self, message: OutboundMessage) -> None:
        """Receive an outbound message from the agent via ChannelManager.

        Routes the message to the active SSE session queue if one exists
        for this request, otherwise drops it silently.
        """
        session_key = message.metadata.get("session_key", f"{self.name}:{message.chat_id}")
        queue = self._session_queues.get(session_key)

        # Also try chat_id directly as a fallback (agent loop may use raw id)
        if queue is None and message.chat_id:
            queue = self._session_queues.get(message.chat_id)

        if queue is not None:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("Rokid SSE session queue full for %s", session_key)
        else:
            active_keys = list(self._session_queues.keys())
            logger.info(
                "RokidSSEChannel.send: no active session for keys [%s, %s]. "
                "Active queues: %s",
                session_key,
                message.chat_id,
                active_keys,
            )

    async def send_delta(self, message: OutboundMessage) -> None:
        """Receive a streaming delta from the agent.

        Same routing logic as send — streams are delivered via the
        per-session queue to the SSE handler.
        """
        await self.send(message)
