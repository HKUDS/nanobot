"""Inter-agent communication channel.

Enables direct HTTP-based communication between nanobot instances, allowing
multiple agents to collaborate autonomously on tasks without human mediation.

Each instance exposes a lightweight HTTP API. When one agent needs to consult
another, it POSTs to the target's API endpoint and awaits the response — all
within the normal agent tool loop, with full session isolation and audit logging.

API
---
POST /inter-agent/chat
    {
        "message": "...",
        "session_id": "collab_abc123",
        "from_instance": "alice",
        "round_count": 3
    }
    → {"response": "...", "is_final": false, "instance": "bob", "session_id": "..."}

GET /inter-agent/health
    → {"status": "ok", "instance": "bob", "port": 18801}

Configuration (config.json)
----------------------------
{
  "channels": {
    "interagent": {
      "enabled": true,
      "apiPort": 18801,
      "instanceName": "bob",
      "auditWebhookUrl": "https://...",
      "maxRoundsPerSession": 30
    }
  }
}

Session isolation
-----------------
Each inter-agent conversation uses a unique session_id as the session key
(``inter_agent:<session_id>``), completely isolated from the human-facing
chat sessions of both instances.

Audit webhook
-------------
Every message — both inbound and outbound — is pushed to ``auditWebhookUrl``
so a human supervisor can monitor all inter-agent conversations in real time.
Long messages are automatically split into chunks to respect webhook limits.

Round-limit guard
-----------------
``maxRoundsPerSession`` (default 30) caps how many turns this instance will
participate in before the initiating agent pauses and asks the human whether
to continue. The initiating agent is responsible for enforcing this; the
receiving instance exposes the current ``round_count`` in every request so
the initiator can track it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp.web
from loguru import logger
from pydantic import Field

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class InterAgentConfig(Base):
    """Configuration for the inter-agent communication channel."""

    enabled: bool = False
    api_port: int = 18800
    instance_name: str = ""
    audit_webhook_url: str = ""
    max_rounds_per_session: int = 30


# ---------------------------------------------------------------------------
# Pending-response registry  (session_id → Future[str])
# ---------------------------------------------------------------------------

_pending: dict[str, asyncio.Future[str]] = {}

# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

_CHUNK = 3800  # safe chunk size under Feishu's 4096-char webhook limit

_FINAL_SIGNALS = [
    "最终方案", "讨论结束", "达成共识", "已确认",
    "final proposal", "discussion complete", "consensus reached",
    "DISCUSSION_COMPLETE",
]


class InterAgentChannel(BaseChannel):
    """HTTP API channel for real-time inter-agent communication."""

    name = "interagent"
    display_name = "Inter-Agent"

    # ------------------------------------------------------------------
    # Plugin architecture hooks
    # ------------------------------------------------------------------

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return InterAgentConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = InterAgentConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: InterAgentConfig = config
        self._runner: aiohttp.web.AppRunner | None = None

    # ------------------------------------------------------------------
    # BaseChannel interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        app = aiohttp.web.Application()
        app.router.add_get("/inter-agent/health", self._handle_health)
        app.router.add_post("/inter-agent/chat", self._handle_chat)

        self._runner = aiohttp.web.AppRunner(app)
        await self._runner.setup()
        site = aiohttp.web.TCPSite(self._runner, "0.0.0.0", self.config.api_port)
        await site.start()
        logger.info(
            "Inter-agent API listening on port {} (instance: {})",
            self.config.api_port,
            self.config.instance_name,
        )
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._running = False
        if self._runner:
            await self._runner.cleanup()

    async def send(self, msg: OutboundMessage) -> None:
        """Resolve the pending future so the HTTP handler can return the response."""
        future = _pending.pop(msg.chat_id, None)
        if future and not future.done():
            future.set_result(msg.content)

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    async def _handle_health(self, _request: aiohttp.web.Request) -> aiohttp.web.Response:
        return aiohttp.web.json_response({
            "status": "ok",
            "instance": self.config.instance_name,
            "port": self.config.api_port,
        })

    async def _handle_chat(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return aiohttp.web.json_response({"error": "invalid JSON"}, status=400)

        message: str = body.get("message", "").strip()
        session_id: str = body.get("session_id", "")
        from_instance: str = body.get("from_instance", "unknown")
        round_count: int = int(body.get("round_count", 0))

        if not message or not session_id:
            return aiohttp.web.json_response(
                {"error": "message and session_id are required"}, status=400
            )

        logger.info(
            "Inter-agent message from {} | session={} | round={}",
            from_instance, session_id, round_count,
        )

        # Audit: inbound message
        asyncio.create_task(self._push_audit(
            from_instance, self.config.instance_name, session_id, round_count, message
        ))

        # Register future before publishing so send() can resolve it
        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()
        _pending[session_id] = future

        # Inject into the agent via the message bus (isolated session)
        await self.bus.publish_inbound(InboundMessage(
            channel=self.name,
            sender_id=from_instance,
            chat_id=session_id,
            content=message,
            metadata={"from_instance": from_instance, "round_count": round_count},
            session_key_override=f"interagent:{session_id}",
        ))

        # Wait for the agent to respond (2-minute timeout)
        try:
            response = await asyncio.wait_for(future, timeout=120.0)
        except asyncio.TimeoutError:
            _pending.pop(session_id, None)
            return aiohttp.web.json_response({"error": "agent response timeout"}, status=504)

        # Audit: outbound reply
        asyncio.create_task(self._push_audit(
            self.config.instance_name, from_instance, session_id, round_count, response
        ))

        return aiohttp.web.json_response({
            "response": response,
            "is_final": _is_final(response),
            "instance": self.config.instance_name,
            "session_id": session_id,
        })

    # ------------------------------------------------------------------
    # Audit webhook
    # ------------------------------------------------------------------

    async def _push_audit(
        self,
        from_instance: str,
        to_instance: str,
        session_id: str,
        round_count: int,
        message: str,
    ) -> None:
        """Push message to audit webhook, chunking if it exceeds the size limit."""
        url = self.config.audit_webhook_url
        if not url:
            return

        header = (
            f"【实例间对话】\n"
            f"{from_instance} → {to_instance}\n"
            f"Session: {session_id}  轮次: {round_count}\n\n"
        )
        chunks = [message[i:i + _CHUNK] for i in range(0, max(len(message), 1), _CHUNK)]
        total = len(chunks)

        try:
            async with aiohttp.ClientSession() as http:
                for idx, chunk in enumerate(chunks):
                    page = f"（{idx + 1}/{total}）\n" if total > 1 else ""
                    payload = {
                        "msg_type": "text",
                        "content": {"text": header + page + chunk},
                    }
                    await http.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10))
        except Exception as exc:
            logger.warning("Inter-agent audit webhook failed: {}", exc)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _is_final(text: str) -> bool:
    """Return True when the response signals that the discussion is concluded."""
    lower = text.lower()
    return any(sig.lower() in lower for sig in _FINAL_SIGNALS)
