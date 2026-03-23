"""VoIP channel implementation backed by the local VoIP service."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import VoipConfig


class VoipChannel(BaseChannel):
    """VoIP channel that exchanges events with the local telephony backend."""

    name = "voip"

    def __init__(self, config: VoipConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: VoipConfig = config
        self._http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Start polling the local VoIP backend for call events."""
        self._running = True
        self._http = httpx.AsyncClient(timeout=max(30.0, float(self.config.poll_timeout_seconds) + 5.0))
        logger.info("Starting VoIP channel against {}", self.config.api_url)

        while self._running:
            try:
                event = await self._poll_event()
                if not event:
                    continue
                await self._handle_event(event)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("VoIP channel polling error: {}", exc)
                await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the VoIP channel."""
        self._running = False
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """Speak outbound assistant messages into the active call."""
        if not self._http:
            logger.warning("VoIP HTTP client not initialized")
            return

        if not msg.content:
            return

        if (msg.metadata or {}).get("_progress"):
            return

        spoken = self._to_spoken_text(msg.content)
        if not spoken:
            return

        await self._post("/channel/say", {"chat_id": msg.chat_id, "text": spoken})

    async def _poll_event(self) -> dict[str, Any] | None:
        payload = {"timeout": self.config.poll_timeout_seconds}
        data = await self._post("/channel/poll", payload)
        event = data.get("event")
        return event if isinstance(event, dict) else None

    async def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("event", "")).strip()
        chat_id = str(event.get("chat_id", "")).strip()
        session_key = str(event.get("session_key", "")).strip() or f"voip:{chat_id or 'call'}"

        if event_type == "call_started":
            greeting = (self.config.greeting or "").strip()
            if greeting:
                await self._post("/channel/say", {"chat_id": chat_id, "text": greeting})
            return

        if event_type == "heard":
            text = str(event.get("text", "")).strip()
            if not text:
                return
            await self._handle_message(
                sender_id=str(event.get("sender_id", "caller")),
                chat_id=chat_id or session_key,
                content=text,
                metadata={"call_id": chat_id or session_key},
                session_key=session_key,
            )
            return

        if event_type == "call_ended":
            logger.info("VoIP call ended for {}", chat_id or session_key)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert self._http is not None
        url = f"{self.config.api_url.rstrip('/')}{path}"
        response = await self._http.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _to_spoken_text(content: str) -> str:
        text = (content or "").strip()
        if not text:
            return ""

        stripped = text.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            inner = "\n".join(stripped.splitlines()[1:-1]).strip()
            try:
                payload = json.loads(inner)
                if isinstance(payload, dict):
                    reply = payload.get("reply")
                    if isinstance(reply, str) and reply.strip():
                        text = reply.strip()
            except Exception:
                text = inner or text

        text = re.sub(r"```[\s\S]*?```", " ", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
        text = text.replace("|", " ")
        text = text.replace("*", "")
        text = text.replace("_", " ")
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return ""

        sentences = re.split(r"(?<=[.!?])\s+", text)
        spoken = " ".join([sentence for sentence in sentences if sentence.strip()][:2]).strip()
        if not spoken:
            spoken = text
        if len(spoken) > 280:
            spoken = spoken[:277].rstrip() + "..."
        return spoken
