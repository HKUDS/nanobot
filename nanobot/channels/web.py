"""Web channel — delivers messages to a website webhook for Supabase Realtime."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class WebChannel(BaseChannel):
    """
    Delivers outbound messages to a website webhook endpoint.

    The webhook saves messages to Supabase, and Supabase Realtime
    pushes them to the browser in real time.

    Config is read from environment variables:
      - WEBHOOK_URL: base URL of the website (e.g. https://redd.so)
      - WEBHOOK_SECRET: shared secret for authentication
      - FLY_MACHINE_ID: auto-set by Fly, used to identify the bot
    """

    name = "web"
    display_name = "Web"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        self._webhook_url = os.environ.get("WEBHOOK_URL", "")
        self._webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
        self._machine_id = os.environ.get("FLY_MACHINE_ID", "")

    async def start(self) -> None:
        """No listener needed — inbound messages come via the HTTP gateway."""
        self._running = True
        if self._webhook_url and self._webhook_secret and self._machine_id:
            logger.info("Web channel ready (webhook: {})", self._webhook_url)
        else:
            logger.warning("Web channel enabled but missing env vars (WEBHOOK_URL, WEBHOOK_SECRET, or FLY_MACHINE_ID)")
        # Stay alive until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """POST message to the website webhook for Realtime delivery."""
        if not self._webhook_url or not self._webhook_secret or not self._machine_id:
            return
        if not msg.content:
            return

        url = f"{self._webhook_url}/api/messages/ingest"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    url,
                    json={"machine_id": self._machine_id, "content": msg.content},
                    headers={"X-Webhook-Secret": self._webhook_secret},
                )
        except Exception as e:
            logger.warning("Web channel delivery failed: {}", e)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {"enabled": False, "allowFrom": ["*"]}
