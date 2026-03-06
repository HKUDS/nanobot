"""DingTalk/DingDing channel implementation using Stream Mode."""

import asyncio
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import DingTalkConfig

try:
    from dingtalk_stream import (
        AckMessage,
        CallbackHandler,
        CallbackMessage,
        Credential,
        DingTalkStreamClient,
    )
    from dingtalk_stream.chatbot import ChatbotMessage

    DINGTALK_AVAILABLE = True
except ImportError:
    DINGTALK_AVAILABLE = False
    # Fallback so class definitions don't crash at module level
    CallbackHandler = object  # type: ignore[assignment,misc]
    CallbackMessage = None  # type: ignore[assignment,misc]
    AckMessage = None  # type: ignore[assignment,misc]
    ChatbotMessage = None  # type: ignore[assignment,misc]


class NanobotDingTalkHandler(CallbackHandler):
    """
    Standard DingTalk Stream SDK Callback Handler.
    Parses incoming messages and forwards them to the Nanobot channel.
    """

    def __init__(self, channel: "DingTalkChannel"):
        super().__init__()
        self.channel = channel

    async def process(self, message: CallbackMessage):
        """Process incoming stream message."""
        try:
            # Parse using SDK's ChatbotMessage for robust handling
            chatbot_msg = ChatbotMessage.from_dict(message.data)

            # Extract text content; fall back to raw dict if SDK object is empty
            content = ""
            if chatbot_msg.text:
                content = chatbot_msg.text.content.strip()
            if not content:
                content = message.data.get("text", {}).get("content", "").strip()

            if not content:
                logger.warning(
                    "Received empty or unsupported message type: {}",
                    chatbot_msg.message_type,
                )
                return AckMessage.STATUS_OK, "OK"

            sender_id = str(chatbot_msg.sender_staff_id or chatbot_msg.sender_id or "").strip()
            sender_name = chatbot_msg.sender_nick or "Unknown"
            conversation_type = str(
                chatbot_msg.conversation_type or message.data.get("conversationType") or ""
            ).strip()
            conversation_id = str(
                chatbot_msg.conversation_id or message.data.get("conversationId") or ""
            ).strip()
            session_webhook = str(
                chatbot_msg.session_webhook or message.data.get("sessionWebhook") or ""
            ).strip()
            message_id = str(chatbot_msg.message_id or message.data.get("msgId") or "").strip()
            is_in_at_list_raw = chatbot_msg.is_in_at_list
            if is_in_at_list_raw is None:
                is_in_at_list_raw = message.data.get("isInAtList")
            is_in_at_list = self.channel._coerce_bool(is_in_at_list_raw)

            if not sender_id:
                logger.warning("Received DingTalk message without sender_id, dropping event")
                return AckMessage.STATUS_OK, "OK"

            logger.info(
                "Received DingTalk message from {} ({}) conv_type={} conv_id={}: {}",
                sender_name,
                sender_id,
                conversation_type or "unknown",
                conversation_id or "unknown",
                content,
            )

            # Forward to Nanobot via _on_message (non-blocking).
            # Store reference to prevent GC before task completes.
            task = asyncio.create_task(
                self.channel._on_message(
                    content=content,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    conversation_type=conversation_type or None,
                    conversation_id=conversation_id or None,
                    session_webhook=session_webhook or None,
                    message_id=message_id or None,
                    is_in_at_list=is_in_at_list,
                )
            )
            self.channel._background_tasks.add(task)
            task.add_done_callback(self.channel._background_tasks.discard)

            return AckMessage.STATUS_OK, "OK"

        except Exception as e:
            logger.error("Error processing DingTalk message: {}", e)
            # Return OK to avoid retry loop from DingTalk server
            return AckMessage.STATUS_OK, "Error"


class DingTalkChannel(BaseChannel):
    """
    DingTalk channel using Stream Mode.

    Uses WebSocket to receive events via `dingtalk-stream` SDK.
    Uses direct HTTP API to send messages (SDK is mainly for receiving).

    Supports both private (1:1) and group conversation replies.
    - private: OpenAPI oToMessages/batchSend (userIds)
    - group: OpenAPI groupMessages/send (openConversationId)
    - in-session reply: sessionWebhook (preferred when available)
    """

    name = "dingtalk"
    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    _AUDIO_EXTS = {".amr", ".mp3", ".wav", ".ogg", ".m4a", ".aac"}
    _VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    _TRUE_LITERALS = {"1", "true", "t", "yes", "y", "on"}
    _FALSE_LITERALS = {"0", "false", "f", "no", "n", "off", ""}

    def __init__(self, config: DingTalkConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: DingTalkConfig = config
        self._client: Any = None
        self._http: httpx.AsyncClient | None = None

        # Access Token management for sending messages
        self._access_token: str | None = None
        self._token_expiry: float = 0

        # Hold references to background tasks to prevent GC
        self._background_tasks: set[asyncio.Task] = set()

        # Runtime cache: chat_id that is known to be group conversation_id.
        self._group_chat_ids: set[str] = set()

    @classmethod
    def _coerce_bool(cls, value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            low = value.strip().lower()
            if low in cls._TRUE_LITERALS:
                return True
            if low in cls._FALSE_LITERALS:
                return False
        return None

    def _should_respond_in_group(self, is_in_at_list: bool | None) -> bool:
        # DingTalk group events are processed in mention-only mode.
        return bool(is_in_at_list)

    async def start(self) -> None:
        """Start the DingTalk bot with Stream Mode."""
        try:
            if not DINGTALK_AVAILABLE:
                logger.error(
                    "DingTalk Stream SDK not installed. Run: pip install dingtalk-stream"
                )
                return

            if not self.config.client_id or not self.config.client_secret:
                logger.error("DingTalk client_id and client_secret not configured")
                return

            self._running = True
            self._http = httpx.AsyncClient()

            logger.info(
                "Initializing DingTalk Stream Client with Client ID: {}...",
                self.config.client_id,
            )
            credential = Credential(self.config.client_id, self.config.client_secret)
            self._client = DingTalkStreamClient(credential)

            # Register standard handler
            handler = NanobotDingTalkHandler(self)
            self._client.register_callback_handler(ChatbotMessage.TOPIC, handler)

            logger.info("DingTalk bot started with Stream Mode")

            # Reconnect loop: restart stream if SDK exits or crashes
            while self._running:
                try:
                    await self._client.start()
                except Exception as e:
                    logger.warning("DingTalk stream error: {}", e)
                if self._running:
                    logger.info("Reconnecting DingTalk stream in 5 seconds...")
                    await asyncio.sleep(5)

        except Exception as e:
            logger.exception("Failed to start DingTalk channel: {}", e)

    async def stop(self) -> None:
        """Stop the DingTalk bot."""
        self._running = False
        # Close the shared HTTP client
        if self._http:
            await self._http.aclose()
            self._http = None
        # Cancel outstanding background tasks
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()

    async def _get_access_token(self) -> str | None:
        """Get or refresh Access Token."""
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        data = {
            "appKey": self.config.client_id,
            "appSecret": self.config.client_secret,
        }

        if not self._http:
            logger.warning("DingTalk HTTP client not initialized, cannot refresh token")
            return None

        try:
            resp = await self._http.post(url, json=data)
            resp.raise_for_status()
            res_data = resp.json()
            self._access_token = res_data.get("accessToken")
            # Expire 60s early to be safe
            self._token_expiry = time.time() + int(res_data.get("expireIn", 7200)) - 60
            return self._access_token
        except Exception as e:
            logger.error("Failed to get DingTalk access token: {}", e)
            return None

    @staticmethod
    def _is_http_url(value: str) -> bool:
        return urlparse(value).scheme in ("http", "https")

    def _guess_upload_type(self, media_ref: str) -> str:
        ext = Path(urlparse(media_ref).path).suffix.lower()
        if ext in self._IMAGE_EXTS: return "image"
        if ext in self._AUDIO_EXTS: return "voice"
        if ext in self._VIDEO_EXTS: return "video"
        return "file"

    def _guess_filename(self, media_ref: str, upload_type: str) -> str:
        name = os.path.basename(urlparse(media_ref).path)
        return name or {"image": "image.jpg", "voice": "audio.amr", "video": "video.mp4"}.get(upload_type, "file.bin")

    async def _read_media_bytes(
        self,
        media_ref: str,
    ) -> tuple[bytes | None, str | None, str | None]:
        if not media_ref:
            return None, None, None

        if self._is_http_url(media_ref):
            if not self._http:
                return None, None, None
            try:
                resp = await self._http.get(media_ref, follow_redirects=True)
                if resp.status_code >= 400:
                    logger.warning(
                        "DingTalk media download failed status={} ref={}",
                        resp.status_code,
                        media_ref,
                    )
                    return None, None, None
                content_type = (resp.headers.get("content-type") or "").split(";")[0].strip()
                filename = self._guess_filename(media_ref, self._guess_upload_type(media_ref))
                return resp.content, filename, content_type or None
            except Exception as e:
                logger.error("DingTalk media download error ref={} err={}", media_ref, e)
                return None, None, None

        try:
            if media_ref.startswith("file://"):
                parsed = urlparse(media_ref)
                local_path = Path(unquote(parsed.path))
            else:
                local_path = Path(os.path.expanduser(media_ref))
            if not local_path.is_file():
                logger.warning("DingTalk media file not found: {}", local_path)
                return None, None, None
            data = await asyncio.to_thread(local_path.read_bytes)
            content_type = mimetypes.guess_type(local_path.name)[0]
            return data, local_path.name, content_type
        except Exception as e:
            logger.error("DingTalk media read error ref={} err={}", media_ref, e)
            return None, None, None

    async def _upload_media(
        self,
        token: str,
        data: bytes,
        media_type: str,
        filename: str,
        content_type: str | None,
    ) -> str | None:
        if not self._http:
            return None
        url = f"https://oapi.dingtalk.com/media/upload?access_token={token}&type={media_type}"
        mime = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        files = {"media": (filename, data, mime)}

        try:
            resp = await self._http.post(url, files=files)
            text = resp.text
            result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if resp.status_code >= 400:
                logger.error("DingTalk media upload failed status={} type={} body={}", resp.status_code, media_type, text[:500])
                return None
            errcode = result.get("errcode", 0)
            if errcode != 0:
                logger.error("DingTalk media upload api error type={} errcode={} body={}", media_type, errcode, text[:500])
                return None
            sub = result.get("result") or {}
            media_id = result.get("media_id") or result.get("mediaId") or sub.get("media_id") or sub.get("mediaId")
            if not media_id:
                logger.error("DingTalk media upload missing media_id body={}", text[:500])
                return None
            return str(media_id)
        except Exception as e:
            logger.error("DingTalk media upload error type={} err={}", media_type, e)
            return None

    async def _send_batch_message(
        self,
        token: str,
        user_id: str,
        msg_key: str,
        msg_param: dict[str, Any],
    ) -> bool:
        if not self._http:
            logger.warning("DingTalk HTTP client not initialized, cannot send")
            return False

        url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
        headers = {"x-acs-dingtalk-access-token": token}
        payload = {
            "robotCode": self.config.client_id,
            "userIds": [user_id],
            "msgKey": msg_key,
            "msgParam": json.dumps(msg_param, ensure_ascii=False),
        }

        try:
            resp = await self._http.post(url, json=payload, headers=headers)
            body = resp.text
            if resp.status_code != 200:
                logger.error("DingTalk send failed msgKey={} status={} body={}", msg_key, resp.status_code, body[:500])
                return False
            try: result = resp.json()
            except Exception: result = {}
            errcode = result.get("errcode")
            if errcode not in (None, 0):
                logger.error("DingTalk send api error msgKey={} errcode={} body={}", msg_key, errcode, body[:500])
                return False
            logger.debug("DingTalk user message sent to {} with msgKey={}", user_id, msg_key)
            return True
        except Exception as e:
            logger.error("Error sending DingTalk message msgKey={} err={}", msg_key, e)
            return False

    async def _send_group_message(
        self,
        token: str,
        conversation_id: str,
        msg_key: str,
        msg_param: dict[str, Any],
    ) -> bool:
        if not self._http:
            logger.warning("DingTalk HTTP client not initialized, cannot send")
            return False

        url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
        headers = {"x-acs-dingtalk-access-token": token}
        payload = {
            "robotCode": self.config.client_id,
            "openConversationId": conversation_id,
            "msgKey": msg_key,
            "msgParam": json.dumps(msg_param, ensure_ascii=False),
        }

        try:
            resp = await self._http.post(url, json=payload, headers=headers)
            body = resp.text
            if resp.status_code != 200:
                logger.error(
                    "DingTalk group send failed msgKey={} status={} body={}",
                    msg_key,
                    resp.status_code,
                    body[:500],
                )
                return False
            try:
                result = resp.json()
            except Exception:
                result = {}
            errcode = result.get("errcode")
            if errcode not in (None, 0):
                logger.error(
                    "DingTalk group send api error msgKey={} errcode={} body={}",
                    msg_key,
                    errcode,
                    body[:500],
                )
                return False
            logger.debug(
                "DingTalk group message sent to {} with msgKey={}",
                conversation_id,
                msg_key,
            )
            return True
        except Exception as e:
            logger.error("Error sending DingTalk group message msgKey={} err={}", msg_key, e)
            return False

    async def _send_session_webhook_payload(
        self,
        session_webhook: str,
        payload: dict[str, Any],
    ) -> bool:
        if not self._http:
            logger.warning("DingTalk HTTP client not initialized, cannot send")
            return False
        if not session_webhook:
            return False
        try:
            resp = await self._http.post(
                session_webhook,
                json=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            body = resp.text
            if resp.status_code >= 400:
                logger.error(
                    "DingTalk session webhook send failed status={} body={}",
                    resp.status_code,
                    body[:500],
                )
                return False
            try:
                result = resp.json()
            except Exception:
                result = {}
            errcode = result.get("errcode", 0)
            if errcode not in (None, 0):
                logger.error(
                    "DingTalk session webhook api error errcode={} body={}",
                    errcode,
                    body[:500],
                )
                return False
            return True
        except Exception as e:
            logger.error("Error sending DingTalk session webhook message: {}", e)
            return False

    def _resolve_send_target(self, msg: OutboundMessage) -> dict[str, str]:
        metadata = msg.metadata or {}

        session_webhook = str(
            metadata.get("session_webhook") or metadata.get("sessionWebhook") or ""
        ).strip()
        if session_webhook:
            return {"mode": "webhook", "session_webhook": session_webhook}

        conversation_type = str(
            metadata.get("conversation_type") or metadata.get("conversationType") or ""
        ).strip()
        conversation_id = str(
            metadata.get("conversation_id") or metadata.get("conversationId") or ""
        ).strip()

        if not conversation_type and msg.chat_id in self._group_chat_ids:
            conversation_type = "2"
            conversation_id = str(msg.chat_id).strip()

        if conversation_type == "2":
            if not conversation_id:
                conversation_id = str(msg.chat_id).strip()
            if conversation_id:
                return {"mode": "group", "conversation_id": conversation_id}

        return {"mode": "user", "user_id": str(msg.chat_id).strip()}

    async def _send_openapi_message(
        self,
        token: str,
        target: dict[str, str],
        msg_key: str,
        msg_param: dict[str, Any],
    ) -> bool:
        if target.get("mode") == "group":
            conversation_id = target.get("conversation_id", "").strip()
            if not conversation_id:
                return False
            return await self._send_group_message(token, conversation_id, msg_key, msg_param)
        user_id = target.get("user_id", "").strip()
        if not user_id:
            return False
        return await self._send_batch_message(token, user_id, msg_key, msg_param)

    async def _send_markdown_text(
        self,
        token: str | None,
        target: dict[str, str],
        content: str,
    ) -> bool:
        if target.get("mode") == "webhook":
            session_webhook = target.get("session_webhook", "").strip()
            return await self._send_session_webhook_payload(
                session_webhook,
                {"msgtype": "text", "text": {"content": content}},
            )
        if not token:
            logger.error("DingTalk token is required for OpenAPI text send")
            return False
        return await self._send_openapi_message(
            token,
            target,
            "sampleMarkdown",
            {"text": content, "title": "Nanobot Reply"},
        )

    async def _send_media_ref(
        self,
        token: str | None,
        target: dict[str, str],
        media_ref: str,
    ) -> bool:
        media_ref = (media_ref or "").strip()
        if not media_ref:
            return True

        upload_type = self._guess_upload_type(media_ref)
        if upload_type == "image" and self._is_http_url(media_ref):
            if target.get("mode") == "webhook":
                ok = await self._send_session_webhook_payload(
                    target.get("session_webhook", "").strip(),
                    {"msgtype": "image", "image": {"picURL": media_ref}},
                )
            else:
                if not token:
                    logger.error("DingTalk token is required for OpenAPI image send")
                    return False
                ok = await self._send_openapi_message(
                    token,
                    target,
                    "sampleImageMsg",
                    {"photoURL": media_ref},
                )
            if ok:
                return True
            logger.warning("DingTalk image url send failed, trying upload fallback: {}", media_ref)

        data, filename, content_type = await self._read_media_bytes(media_ref)
        if not data:
            logger.error("DingTalk media read failed: {}", media_ref)
            return False

        filename = filename or self._guess_filename(media_ref, upload_type)
        file_type = Path(filename).suffix.lower().lstrip(".")
        if not file_type:
            guessed = mimetypes.guess_extension(content_type or "")
            file_type = (guessed or ".bin").lstrip(".")
        if file_type == "jpeg":
            file_type = "jpg"

        if not token:
            logger.error("DingTalk token is required for media upload send")
            return False

        media_id = await self._upload_media(
            token=token,
            data=data,
            media_type=upload_type,
            filename=filename,
            content_type=content_type,
        )
        if not media_id:
            return False

        if upload_type == "image":
            if target.get("mode") == "webhook":
                ok = await self._send_session_webhook_payload(
                    target.get("session_webhook", "").strip(),
                    {
                        "msgtype": "file",
                        "file": {
                            "mediaId": media_id,
                            "fileName": filename,
                            "fileType": file_type,
                        },
                    },
                )
            else:
                # Verified in production: sampleImageMsg accepts media_id in photoURL.
                ok = await self._send_openapi_message(
                    token,
                    target,
                    "sampleImageMsg",
                    {"photoURL": media_id},
                )
            if ok:
                return True
            logger.warning("DingTalk image media_id send failed, falling back to file: {}", media_ref)

        if target.get("mode") == "webhook":
            return await self._send_session_webhook_payload(
                target.get("session_webhook", "").strip(),
                {
                    "msgtype": "file",
                    "file": {"mediaId": media_id, "fileName": filename, "fileType": file_type},
                },
            )
        return await self._send_openapi_message(
            token,
            target,
            "sampleFile",
            {"mediaId": media_id, "fileName": filename, "fileType": file_type},
        )

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through DingTalk."""
        target = self._resolve_send_target(msg)
        token: str | None = None
        if target.get("mode") != "webhook":
            token = await self._get_access_token()
            if not token:
                return

        if msg.content and msg.content.strip():
            await self._send_markdown_text(token, target, msg.content.strip())

        for media_ref in msg.media or []:
            ok = await self._send_media_ref(token, target, media_ref)
            if ok:
                continue
            logger.error("DingTalk media send failed for {}", media_ref)
            # Send visible fallback so failures are observable by the user.
            filename = self._guess_filename(media_ref, self._guess_upload_type(media_ref))
            await self._send_markdown_text(
                token,
                target,
                f"[Attachment send failed: {filename}]",
            )

    async def _on_message(
        self,
        content: str,
        sender_id: str,
        sender_name: str,
        conversation_type: str | None = None,
        conversation_id: str | None = None,
        session_webhook: str | None = None,
        message_id: str | None = None,
        is_in_at_list: bool | None = None,
    ) -> None:
        """Handle incoming message (called by NanobotDingTalkHandler).

        Delegates to BaseChannel._handle_message() which enforces allow_from
        permission checks before publishing to the bus.
        """
        try:
            sender_id = str(sender_id or "").strip()
            conversation_type = str(conversation_type or "").strip()
            conversation_id = str(conversation_id or "").strip()
            session_webhook = str(session_webhook or "").strip()
            message_id = str(message_id or "").strip()

            is_group = conversation_type == "2" and bool(conversation_id)
            chat_id = conversation_id if is_group else sender_id
            if not chat_id:
                logger.warning("DingTalk inbound missing chat_id/sender_id, dropping message")
                return
            if is_group:
                self._group_chat_ids.add(chat_id)
                if not self._should_respond_in_group(is_in_at_list):
                    logger.debug(
                        "Skip DingTalk group message by mention-only policy chat_id={} at={}",
                        chat_id,
                        is_in_at_list,
                    )
                    return

            logger.info("DingTalk inbound: {} from {}", content, sender_name)
            metadata: dict[str, Any] = {
                "sender_name": sender_name,
                "platform": "dingtalk",
                "conversation_type": conversation_type or "1",
                "chat_type": "group" if is_group else "private",
            }
            if message_id:
                metadata["message_id"] = message_id
            if conversation_id:
                metadata["conversation_id"] = conversation_id
            if session_webhook:
                metadata["session_webhook"] = session_webhook
            if is_in_at_list is not None:
                metadata["is_in_at_list"] = bool(is_in_at_list)

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=str(content),
                metadata=metadata,
            )
        except Exception as e:
            logger.error("Error publishing DingTalk message: {}", e)
