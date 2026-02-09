"""Telnyx Voice channel — give your nanobot a phone number.

Receives inbound calls via Telnyx webhooks, transcribes speech,
sends the transcript to the agent, and speaks the response back
using Telnyx TTS.

Requires:
  - A Telnyx account with a phone number
  - A TeXML Application or Call Control Application pointing webhooks
    to http://<your-host>:<port>/telnyx/voice
  - aiohttp (already a common dependency)

Config example (~/.nanobot/config.json):
  {
    "channels": {
      "telnyx_voice": {
        "enabled": true,
        "apiKey": "KEYxxxxxxxx",
        "webhookPort": 8088,
        "voice": "female",
        "language": "en-US",
        "allowFrom": ["+14155551234"]
      }
    }
  }
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, TYPE_CHECKING

import aiohttp
from aiohttp import web
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TelnyxVoiceConfig

if TYPE_CHECKING:
    pass

TELNYX_API = "https://api.telnyx.com/v2"


class TelnyxVoiceChannel(BaseChannel):
    """
    Voice channel using Telnyx Call Control + TTS.

    Flow:
      1. Inbound call arrives -> webhook POST /telnyx/voice
      2. Answer the call
      3. call.answered -> start gather (speech recognition)
      4. call.gather.ended -> transcript -> publish to bus as inbound message
      5. Agent responds -> OutboundMessage -> speak with TTS
      6. After speaking -> gather again (conversation loop)
    """

    name = "telnyx_voice"

    def __init__(self, config: TelnyxVoiceConfig, bus: MessageBus):
        super().__init__(config, bus)
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._session: aiohttp.ClientSession | None = None
        self._active_calls: dict[str, str] = {}  # call_control_id -> caller number

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Start the webhook server."""
        self._running = True
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            }
        )

        self._app = web.Application()
        self._app.router.add_post("/telnyx/voice", self._handle_webhook)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.config.webhook_port)
        await site.start()

        logger.info(
            f"Telnyx Voice channel listening on port {self.config.webhook_port}"
        )

        # Keep running
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the webhook server and hang up active calls."""
        self._running = False

        # Hang up active calls
        for cc_id in list(self._active_calls):
            await self._api_call(f"calls/{cc_id}/actions/hangup", {})

        self._active_calls.clear()

        if self._runner:
            await self._runner.cleanup()
        if self._session:
            await self._session.close()

    # -- webhook handler -----------------------------------------------------

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """Handle Telnyx webhook events."""
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400)

        data = body.get("data", {})
        event_type = data.get("event_type", "")
        payload = data.get("payload", {})
        cc_id = payload.get("call_control_id", "")

        logger.debug(f"Telnyx event: {event_type} cc_id={cc_id[:12]}...")

        if event_type == "call.initiated":
            direction = payload.get("direction", "")
            caller = payload.get("from", "")

            if direction == "incoming":
                if not self.is_allowed(caller):
                    logger.warning(f"Rejected call from {caller}")
                    await self._api_call(
                        f"calls/{cc_id}/actions/reject", {}
                    )
                    return web.Response(status=200)

                self._active_calls[cc_id] = caller
                await self._api_call(
                    f"calls/{cc_id}/actions/answer",
                    {"client_state": ""},
                )

        elif event_type == "call.answered":
            await self._start_gather(cc_id)

        elif event_type == "call.gather.ended":
            transcript = payload.get("digits", "") or ""
            # Speech results come in the speech object
            speech = payload.get("speech", {})
            if speech:
                transcript = speech.get("result", "") or transcript

            caller = self._active_calls.get(cc_id, "unknown")

            if transcript.strip():
                logger.info(f"Transcript from {caller}: {transcript}")
                await self._handle_message(
                    sender_id=caller,
                    chat_id=cc_id,
                    content=transcript.strip(),
                    metadata={
                        "call_control_id": cc_id,
                        "channel_type": "voice",
                    },
                )
            else:
                # No speech detected, gather again
                await self._start_gather(cc_id)

        elif event_type == "call.speak.ended":
            # After speaking, listen again
            await self._start_gather(cc_id)

        elif event_type in ("call.hangup", "call.machine.detection.ended"):
            self._active_calls.pop(cc_id, None)

        return web.Response(status=200)

    # -- outbound (TTS) ------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        """Speak the agent's response on the active call."""
        cc_id = msg.chat_id

        if cc_id not in self._active_calls:
            logger.warning(f"No active call for {cc_id}, dropping message")
            return

        await self._api_call(
            f"calls/{cc_id}/actions/speak",
            {
                "payload": msg.content,
                "voice": self.config.voice,
                "language": self.config.language,
            },
        )

    # -- helpers -------------------------------------------------------------

    async def _start_gather(self, cc_id: str) -> None:
        """Start speech gathering (listen for caller input)."""
        await self._api_call(
            f"calls/{cc_id}/actions/gather",
            {
                "input_type": "speech",
                "language": self.config.language,
                "inter_digit_timeout": 5,
                "maximum_timeout": 30,
            },
        )

    async def _api_call(self, endpoint: str, payload: dict) -> dict | None:
        """Make a Telnyx API call."""
        if not self._session:
            return None

        url = f"{TELNYX_API}/{endpoint}"
        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error(f"Telnyx API error {resp.status}: {text}")
                    return None
                return await resp.json()
        except Exception as e:
            logger.error(f"Telnyx API call failed: {e}")
            return None
