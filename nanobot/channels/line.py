from __future__ import annotations

import base64
import asyncio
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import LineConfig

from .base import BaseChannel


LINE_API_BASE = "https://api.line.me/v2/bot"
LINE_API_DATA_BASE = "https://api-data.line.me/v2/bot"
SUPPORTED_INBOUND_MEDIA_TYPES = {"image", "video", "audio", "file"}
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
REPLY_TOKEN_MAX_AGE_SECONDS = 25
DEFAULT_TIMEOUT_SECONDS = 15.0


class LineChannel(BaseChannel):
    """LINE Messaging API channel via webhook + outbound REST API."""

    name = "line"

    def __init__(self, config: LineConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: LineConfig = config
        self.channel_access_token = config.channel_access_token
        self.channel_secret = config.channel_secret
        self.webhook_path = config.webhook_path
        self._media_dir = Path.home() / ".nanobot" / "media"

    async def start(self) -> None:
        """LINE uses webhook callbacks, no polling loop is needed."""
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def handle_webhook(self, body_bytes: bytes, headers: dict[str, str]) -> dict[str, Any]:
        """Handle incoming LINE webhook request payload."""
        signature = headers.get("x-line-signature") or headers.get("X-Line-Signature")
        if self.channel_secret:
            if not signature:
                logger.warning("LINE webhook missing signature header")
                return {"status": "error", "message": "missing signature"}
            if not self._verify_signature(body_bytes, signature):
                logger.warning("LINE webhook signature mismatch")
                return {"status": "error", "message": "invalid signature"}

        try:
            body = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.exception("Failed to parse LINE webhook body: {}", e)
            return {"status": "error", "message": "invalid json"}

        events = body.get("events", [])
        if not isinstance(events, list):
            logger.warning("LINE webhook events is not a list")
            return {"status": "error", "message": "invalid events"}

        for event in events:
            if not isinstance(event, dict):
                logger.warning("LINE webhook event has invalid type: {}", type(event))
                continue
            try:
                await self._handle_event(event)
            except Exception as e:  # noqa: BLE001
                logger.exception("Unhandled LINE event processing error: {}", e)

        return {"status": "ok"}

    def _verify_signature(self, body_bytes: bytes, signature: str) -> bool:
        digest = hmac.new(
            self.channel_secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).digest()
        expected_signature = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected_signature, signature.strip())

    async def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type != "message":
            logger.debug("Ignoring non-message LINE event: {}", event_type)
            return

        source = event.get("source", {})
        user_id = source.get("userId") or "unknown"
        chat_id = source.get("groupId") or source.get("roomId") or user_id

        line_metadata = {
            "event_id": event.get("webhookEventId") or event.get("eventId"),
            "reply_token": event.get("replyToken"),
            "event_timestamp": event.get("timestamp"),
            "source": source,
            "mode": event.get("mode"),
        }
        metadata = {"line": line_metadata}

        await self._start_loading_animation(user_id)

        message = event.get("message", {})
        if not isinstance(message, dict):
            logger.warning("LINE message payload is not an object")
            return

        msg_type = message.get("type")
        content = ""
        media_paths: list[str] = []

        if msg_type == "text":
            content = str(message.get("text", ""))
        elif msg_type in SUPPORTED_INBOUND_MEDIA_TYPES:
            message_id = message.get("id")
            if message_id:
                downloaded_path = await self._download_message_content(str(message_id), str(msg_type))
                if downloaded_path:
                    media_paths.append(downloaded_path)
                    content = f"[{msg_type}: {downloaded_path}]"
                else:
                    content = f"[{msg_type}: download failed]"
            else:
                content = f"[{msg_type}: missing message id]"
        else:
            logger.debug("Ignoring unsupported LINE message type: {}", msg_type)
            return

        if not content and not media_paths:
            return

        await self._handle_message(
            sender_id=user_id,
            chat_id=chat_id,
            content=content,
            media=media_paths or None,
            metadata=metadata,
        )

    async def _download_message_content(self, message_id: str, media_type: str) -> str | None:
        if not self.channel_access_token:
            logger.warning("Cannot download LINE media without channel_access_token")
            return None

        self._media_dir.mkdir(parents=True, exist_ok=True)
        file_ext = self._extension_for_media(media_type)
        target_path = self._media_dir / f"line_{message_id}{file_ext}"
        url = f"{LINE_API_DATA_BASE}/message/{message_id}/content"
        headers = {"Authorization": f"Bearer {self.channel_access_token}"}

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                response = await client.get(url, headers=headers)
            if response.status_code >= 400:
                logger.error(
                    "Failed to download LINE media: {} {} - {}",
                    response.status_code,
                    response.reason_phrase,
                    response.text,
                )
                return None
            target_path.write_bytes(response.content)
            return str(target_path)
        except httpx.TimeoutException as e:
            logger.warning("Timeout while downloading LINE media {}: {}", message_id, e)
            return None
        except httpx.RequestError as e:
            logger.warning("Network error while downloading LINE media {}: {}", message_id, e)
            return None
        except OSError as e:
            logger.error("Failed to save LINE media {}: {}", message_id, e)
            return None

    async def _start_loading_animation(self, chat_id: str) -> None:
        """Display LINE loading animation for user chats when possible."""
        if not self.channel_access_token or not chat_id or not chat_id.startswith("U"):
            return

        headers = {
            "Authorization": f"Bearer {self.channel_access_token}",
            "Content-Type": "application/json",
        }
        payload = {"chatId": chat_id, "loadingSeconds": 5}
        url = f"{LINE_API_BASE}/chat/loading/start"

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.debug(
                    "LINE loading animation failed: {} {} - {}",
                    resp.status_code,
                    resp.reason_phrase,
                    resp.text,
                )
        except httpx.RequestError as e:
            logger.debug("LINE loading animation request error: {}", e)

    def _extension_for_media(self, media_type: str) -> str:
        mapping = {
            "image": ".jpg",
            "video": ".mp4",
            "audio": ".m4a",
            "file": ".bin",
        }
        return mapping.get(media_type, ".bin")

    def _build_messages(self, msg: OutboundMessage) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        text = (msg.content or "").strip()
        if text:
            messages.append({"type": "text", "text": text[:5000]})

        for media_item in msg.media or []:
            image_url = self._as_public_https_url(media_item)
            if image_url is None:
                logger.warning("LINE image media must be a public HTTPS URL: {}", media_item)
                continue
            messages.append(
                {
                    "type": "image",
                    "originalContentUrl": image_url,
                    "previewImageUrl": image_url,
                }
            )

        return messages[:5]

    def _as_public_https_url(self, value: str) -> str | None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            return None
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in SUPPORTED_IMAGE_EXTENSIONS):
            return value
        return value

    def _extract_line_metadata(self, msg: OutboundMessage) -> dict[str, Any]:
        metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
        line_metadata = metadata.get("line")
        if isinstance(line_metadata, dict):
            return line_metadata
        return {}

    def _can_use_reply_token(self, reply_token: str | None, event_timestamp: Any) -> bool:
        if not reply_token:
            return False
        if event_timestamp is None:
            return True
        try:
            ts_ms = int(event_timestamp)
        except (TypeError, ValueError):
            return True
        age_seconds = (time.time() * 1000 - ts_ms) / 1000
        return age_seconds <= REPLY_TOKEN_MAX_AGE_SECONDS

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        retries: int = 2,
    ) -> httpx.Response | None:
        for attempt in range(retries + 1):
            try:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code == 429 and attempt < retries:
                    wait_seconds = 1.0 + attempt
                    logger.warning("LINE API rate limited (429), retrying in {}s", wait_seconds)
                    await asyncio.sleep(wait_seconds)
                    continue
                return response
            except httpx.TimeoutException as e:
                logger.warning("LINE API timeout at {}: {}", url, e)
                if attempt >= retries:
                    return None
            except httpx.ConnectError as e:
                logger.warning("LINE API connection error at {}: {}", url, e)
                if attempt >= retries:
                    return None
            except httpx.RequestError as e:
                logger.warning("LINE API request error at {}: {}", url, e)
                if attempt >= retries:
                    return None
        return None

    async def send(self, msg: OutboundMessage) -> None:
        """Send LINE message, preferring reply token and falling back to push."""
        if not self.channel_access_token:
            logger.error("LINE channel_access_token not configured")
            return

        messages = self._build_messages(msg)
        if not messages:
            logger.warning("Skipping LINE send because both text and media are empty")
            return

        headers = {
            "Authorization": f"Bearer {self.channel_access_token}",
            "Content-Type": "application/json",
        }

        line_metadata = self._extract_line_metadata(msg)
        if line_metadata.get("mode") == "standby":
            logger.info("Skipping outbound LINE message because event mode is standby")
            return

        reply_token = line_metadata.get("reply_token")
        event_timestamp = line_metadata.get("event_timestamp")
        can_reply = self._can_use_reply_token(reply_token, event_timestamp)

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            if can_reply:
                reply_payload = {"replyToken": reply_token, "messages": messages}
                reply_url = f"{LINE_API_BASE}/message/reply"
                reply_resp = await self._post_with_retry(client, reply_url, headers, reply_payload)
                if reply_resp and reply_resp.status_code < 400:
                    return
                if reply_resp is not None:
                    logger.warning(
                        "LINE reply failed, fallback to push: {} {} - {}",
                        reply_resp.status_code,
                        reply_resp.reason_phrase,
                        reply_resp.text,
                    )

            push_payload = {"to": msg.chat_id, "messages": messages}
            push_url = f"{LINE_API_BASE}/message/push"
            push_resp = await self._post_with_retry(client, push_url, headers, push_payload)
            if push_resp is None:
                logger.error("LINE push request failed after retries")
                return
            if push_resp.status_code >= 400:
                logger.error(
                    "Failed to send LINE push message: {} {} - {}",
                    push_resp.status_code,
                    push_resp.reason_phrase,
                    push_resp.text,
                )
