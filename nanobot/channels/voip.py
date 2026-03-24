"""VoIP channel implementation backed by the local VoIP service."""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
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
        self._call_contexts: dict[str, dict[str, Any]] = {}

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
        call_key = chat_id or session_key

        if event_type == "call_started":
            direction = str(event.get("direction", "")).strip() or "incoming"
            opening_text = str(event.get("opening_text", "")).strip()
            self._call_contexts[call_key] = {
                "direction": direction,
                "goal_text": opening_text,
                "waiting_for_real_turn": bool(direction == "outgoing" and opening_text),
            }
            greeting = opening_text or (self.config.greeting or "").strip()
            if greeting:
                await self._post(
                    "/channel/say",
                    {"chat_id": chat_id, "text": greeting, "interruptible": direction != "outgoing"},
                )
            return

        if event_type == "heard":
            text = str(event.get("text", "")).strip()
            if not text:
                return
            alt_text = str(event.get("alt_text", "")).strip()
            stt_source = str(event.get("stt_source", "")).strip()
            stt_similarity = event.get("stt_similarity")
            call_ctx = self._call_contexts.get(call_key, {})
            normalized = self._normalize_text(text)
            if self._should_ignore_turn(normalized, call_ctx):
                logger.info("Ignoring trivial VoIP turn for {}: {}", call_key, text)
                return
            content = self._inject_call_context(
                text,
                call_ctx,
                alt_text=alt_text,
                stt_source=stt_source,
                stt_similarity=stt_similarity,
            )
            if call_ctx.get("waiting_for_real_turn"):
                call_ctx["waiting_for_real_turn"] = False
            await self._handle_message(
                sender_id=str(event.get("sender_id", "caller")),
                chat_id=call_key,
                content=content,
                metadata={
                    "call_id": call_key,
                    "voip_goal": str(call_ctx.get("goal_text", "")).strip(),
                    "stt_alt_text": alt_text,
                    "stt_source": stt_source,
                    "stt_similarity": stt_similarity,
                },
                session_key=session_key,
            )
            return

        if event_type == "call_ended":
            self._call_contexts.pop(call_key, None)
            logger.info("VoIP call ended for {}", call_key)

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

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text or "")
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_text = ascii_text.lower()
        ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
        return re.sub(r"\s+", " ", ascii_text).strip()

    @classmethod
    def _should_ignore_turn(cls, normalized: str, call_ctx: dict[str, Any]) -> bool:
        if not normalized:
            return True
        words = normalized.split()
        trivial_greetings = {
            "allo",
            "bonjour",
            "bonsoir",
            "salut",
            "oui",
            "oui bonjour",
            "allo bonjour",
        }
        fillers = {"hum", "hmm", "euh", "hein", "ok", "d accord", "ouin"}
        if normalized in fillers:
            return True
        if call_ctx.get("direction") == "outgoing" and call_ctx.get("waiting_for_real_turn"):
            if normalized in trivial_greetings:
                return True
            if len(words) <= 2 and normalized in fillers.union({"allo", "bonjour", "salut"}):
                return True
        return False

    @staticmethod
    def _inject_call_context(
        text: str,
        call_ctx: dict[str, Any],
        *,
        alt_text: str = "",
        stt_source: str = "",
        stt_similarity: Any = None,
    ) -> str:
        goal_text = str(call_ctx.get("goal_text", "")).strip()
        direction = str(call_ctx.get("direction", "")).strip()
        transcript_context = (
            f"Transcription principale (STT {stt_source or 'unknown'}): {text}"
            if stt_source
            else f"Transcription principale: {text}"
        )
        if alt_text:
            transcript_context += f" Transcription alternative: {alt_text}"
        if stt_similarity is not None and stt_similarity != "":
            transcript_context += f" Similarité STT: {stt_similarity}"
        if direction != "outgoing" or not goal_text:
            return transcript_context
        return (
            "Contexte d'appel sortant: tu as appelé cette personne. "
            f"Objectif de l'appel: {goal_text} "
            "Reste dans cet objectif pendant tout l'appel. "
            "Ne nie jamais avoir appelé. "
            "Ne te réintroduis pas comme assistant générique si ce n'est pas utile. "
            "La transcription téléphonique peut être bruitée ou approximative. "
            "Si la phrase semble incohérente, ambiguë ou hors sujet, demande une courte clarification au lieu d'inventer. "
            "N'invente pas de nom, d'identité ou de détail personnel non confirmé dans cet appel. "
            "Réponds comme la personne qui appelle pour atteindre cet objectif. "
            f"Interlocuteur (transcription possiblement imparfaite): {transcript_context}"
        )
