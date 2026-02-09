"""Telnyx Voice channel — give your nanobot a phone number.

Receives inbound calls via Telnyx webhooks, transcribes speech using
Telnyx's real-time STT (Speech-to-Text) WebSocket API, sends the
transcript to the agent, and speaks the response back using Telnyx's
streaming TTS (Text-to-Speech) WebSocket API.

Inspired by ClawdTalk (https://github.com/anthropics/clawdtalk), the
voice calling integration for Clawdbot.

Telnyx Voice AI stack:
  - TTS: wss://api.telnyx.com/v2/text-to-speech/speech
    Voices: Telnyx NaturalHD, ElevenLabs, MiniMax, AWS Neural, Azure Neural
  - STT: wss://api.telnyx.com/v2/speech-to-text/transcription
    Engines: Telnyx, Deepgram (nova-2/nova-3/flux), Google, Azure
  - Call Control: https://api.telnyx.com/v2/calls
    Programmable voice with answer, speak, gather, transfer, etc.

Requires:
  - A Telnyx account with a phone number
  - A Call Control Application pointing webhooks to
    http://<your-host>:<port>/telnyx/voice
  - aiohttp, websockets

Config example (~/.nanobot/config.json):
  {
    "channels": {
      "telnyx_voice": {
        "enabled": true,
        "apiKey": "KEYxxxxxxxx",
        "webhookPort": 8088,
        "ttsVoice": "Telnyx.NaturalHD.astra",
        "sttEngine": "telnyx",
        "language": "en-US",
        "allowFrom": ["+14155551234"]
      }
    }
  }
"""

from __future__ import annotations

import asyncio
import base64
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
TELNYX_TTS_WS = "wss://api.telnyx.com/v2/text-to-speech/speech"
TELNYX_STT_WS = "wss://api.telnyx.com/v2/speech-to-text/transcription"


class TelnyxVoiceChannel(BaseChannel):
    """
    Voice channel using Telnyx Call Control + streaming TTS/STT.

    Flow:
      1. Inbound call arrives via webhook POST /telnyx/voice
      2. Answer the call
      3. call.answered -> start gather (speech recognition via Telnyx STT)
      4. call.gather.ended -> transcript -> publish to bus as inbound message
      5. Agent responds -> OutboundMessage -> speak with Telnyx TTS
      6. After speaking -> gather again (conversation loop)

    Standalone TTS/STT WebSocket endpoints are also available for
    non-telephony use cases (voice notes, audio transcription, etc.):
      - TTS: wss://api.telnyx.com/v2/text-to-speech/speech?voice={voice}
      - STT: wss://api.telnyx.com/v2/speech-to-text/transcription?transcription_engine={engine}
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
        """Start the webhook server for receiving Telnyx call events."""
        self._running = True
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            }
        )

        self._app = web.Application()
        self._app.router.add_post("/telnyx/voice", self._handle_webhook)
        self._app.router.add_get("/health", self._health_check)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.config.webhook_port)
        await site.start()

        logger.info(
            f"Telnyx Voice channel listening on port {self.config.webhook_port}"
        )
        logger.info(
            f"  TTS voice: {self.config.tts_voice}"
        )
        logger.info(
            f"  STT engine: {self.config.stt_engine}"
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
        """Handle Telnyx call control webhook events."""
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
            # Greet the caller, then start listening
            greeting = "Hello! How can I help you?"
            await self._speak(cc_id, greeting)

        elif event_type == "call.gather.ended":
            transcript = ""
            # Speech results from Telnyx STT
            speech = payload.get("speech", {})
            if speech:
                transcript = speech.get("result", "")
            # Fallback to digits (DTMF)
            if not transcript:
                transcript = payload.get("digits", "")

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
                # No speech detected, listen again
                await self._start_gather(cc_id)

        elif event_type == "call.speak.ended":
            # After speaking, listen for the next utterance
            await self._start_gather(cc_id)

        elif event_type in ("call.hangup", "call.machine.detection.ended"):
            caller = self._active_calls.pop(cc_id, None)
            if caller:
                logger.info(f"Call ended: {caller}")

        return web.Response(status=200)

    async def _health_check(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "ok",
            "channel": "telnyx_voice",
            "active_calls": len(self._active_calls),
        })

    # -- outbound (TTS) ------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        """Speak the agent's response on the active call using Telnyx TTS."""
        cc_id = msg.chat_id

        if cc_id not in self._active_calls:
            logger.warning(f"No active call for {cc_id}, dropping message")
            return

        await self._speak(cc_id, msg.content)

    # -- Telnyx TTS (on-call) ------------------------------------------------

    async def _speak(self, cc_id: str, text: str) -> None:
        """Speak text on an active call using Telnyx Call Control speak command.

        Uses the Telnyx TTS engine configured in tts_voice. Telnyx supports
        multiple TTS providers through a single API:
          - Telnyx NaturalHD (default, good balance of quality and cost)
          - Telnyx Natural / Kokoro (budget-friendly, high-volume)
          - ElevenLabs (premium, expressive)
          - MiniMax (multilingual, expressive)
          - AWS Neural (Amazon Polly)
          - Azure Neural / Azure Neural HD

        Voice format: "Provider.Tier.voicename"
        Examples:
          - "Telnyx.NaturalHD.astra"
          - "ElevenLabs.Flash.aria"
          - "MiniMax.speech-2.6-turbo.English_Trustworth_Man"
        """
        await self._api_call(
            f"calls/{cc_id}/actions/speak",
            {
                "payload": text,
                "voice": self.config.tts_voice,
                "language": self.config.language,
            },
        )

    # -- Telnyx STT (speech gather) ------------------------------------------

    async def _start_gather(self, cc_id: str) -> None:
        """Start speech gathering on an active call using Telnyx STT.

        Telnyx STT supports multiple transcription engines:
          - "telnyx"   : In-house engine, best accuracy and lowest latency
          - "deepgram" : Deepgram nova-2/nova-3/flux models
          - "google"   : Google STT with interim results
          - "azure"    : Azure STT, strong multilingual support

        The standalone STT WebSocket endpoint is also available for
        non-telephony transcription:
          wss://api.telnyx.com/v2/speech-to-text/transcription
        """
        gather_params: dict[str, Any] = {
            "input_type": "speech",
            "language": self.config.language,
            "inter_digit_timeout": 5,
            "maximum_timeout": 30,
        }

        # Set STT engine if specified (default is Telnyx's built-in)
        if self.config.stt_engine:
            gather_params["transcription_engine"] = self.config.stt_engine

        await self._api_call(
            f"calls/{cc_id}/actions/gather",
            gather_params,
        )

    # -- Standalone TTS WebSocket (non-telephony) ----------------------------

    async def synthesize_speech(self, text: str) -> bytes:
        """Synthesize speech using Telnyx TTS WebSocket (standalone, no call needed).

        Useful for generating audio files, voice notes, or pre-recorded messages.
        Returns raw mp3 audio bytes.

        WebSocket endpoint: wss://api.telnyx.com/v2/text-to-speech/speech
        """
        import websockets

        url = f"{TELNYX_TTS_WS}?voice={self.config.tts_voice}"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        audio_chunks: list[bytes] = []

        async with websockets.connect(url, extra_headers=headers) as ws:
            # Initialize session
            await ws.send(json.dumps({"text": " "}))

            # Send text
            await ws.send(json.dumps({"text": text}))

            # Signal end of input
            await ws.send(json.dumps({"text": ""}))

            # Collect audio frames
            async for message in ws:
                data = json.loads(message)
                if "audio" in data:
                    audio_chunks.append(base64.b64decode(data["audio"]))

        return b"".join(audio_chunks)

    # -- Standalone STT WebSocket (non-telephony) ----------------------------

    async def transcribe_audio(self, audio_data: bytes, input_format: str = "mp3") -> str:
        """Transcribe audio using Telnyx STT WebSocket (standalone, no call needed).

        Useful for transcribing voice notes, audio files, or recordings.
        Returns the full transcript as a string.

        WebSocket endpoint: wss://api.telnyx.com/v2/speech-to-text/transcription

        Supported engines: telnyx, deepgram, google, azure
        Supported formats: mp3, wav, ogg, webm, flac
        """
        import websockets

        engine = self.config.stt_engine or "telnyx"
        url = (
            f"{TELNYX_STT_WS}"
            f"?transcription_engine={engine}"
            f"&input_format={input_format}"
        )
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        transcripts: list[str] = []

        async with websockets.connect(url, extra_headers=headers) as ws:
            # Start receiving task
            async def receive():
                async for message in ws:
                    data = json.loads(message)
                    if "transcript" in data and data.get("is_final"):
                        transcripts.append(data["transcript"])

            recv_task = asyncio.create_task(receive())

            # Send audio in chunks (16KB)
            chunk_size = 16384
            for i in range(0, len(audio_data), chunk_size):
                await ws.send(audio_data[i:i + chunk_size])
                await asyncio.sleep(0.05)  # Simulate real-time streaming

            # Wait for final transcripts
            await asyncio.sleep(2)
            recv_task.cancel()

        return " ".join(transcripts)

    # -- helpers -------------------------------------------------------------

    async def _api_call(self, endpoint: str, payload: dict) -> dict | None:
        """Make a Telnyx Call Control API call."""
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
