"""DingTalk/DingDing channel implementation using Stream Mode."""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from loguru import logger
import httpx

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import DingTalkConfig

try:
    from dingtalk_stream import (
        DingTalkStreamClient,
        Credential,
        CallbackHandler,
        CallbackMessage,
        AckMessage,
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

            # Extract image download codes (picture / richText messages)
            image_download_codes = []
            try:
                image_download_codes = chatbot_msg.get_image_list() or []
            except Exception:
                pass

            if not content and not image_download_codes:
                logger.warning(
                    "Received empty or unsupported message type: {}",
                    chatbot_msg.message_type,
                )
                return AckMessage.STATUS_OK, "OK"

            sender_id = chatbot_msg.sender_staff_id or chatbot_msg.sender_id
            sender_name = chatbot_msg.sender_nick or "Unknown"

            # Detect group vs private chat
            # conversationType: "1" = private, "2" = group
            conversation_type = message.data.get("conversationType", "1")
            conversation_id = message.data.get("conversationId", "")

            # Group chat title (name of the group)
            # Try SDK field first, fall back to raw data
            conversation_title = (
                chatbot_msg.conversation_title
                or message.data.get("conversationTitle", "")
                or ""
            )
            logger.debug(f"DingTalk raw message keys: {list(message.data.keys())}")

            logger.info(f"Received DingTalk message from {sender_name} (staff_id={sender_id}), "
                        f"type={'group' if conversation_type == '2' else 'private'}"
                        f"{f' in [{conversation_title}]' if conversation_title else ''}"
                        f": {content}")

            # For group chat, use conversationId as chat_id
            chat_id = conversation_id if conversation_type == "2" else sender_id

            # Forward to Nanobot via _on_message (non-blocking).
            # Store reference to prevent GC before task completes.
            task = asyncio.create_task(
                self.channel._on_message(
                    content, sender_id, sender_name,
                    chat_id=chat_id,
                    is_group=conversation_type == "2",
                    conversation_title=conversation_title,
                    image_download_codes=image_download_codes,
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

    Supports both private (1:1) and group chat. Conversation type is
    auto-detected from incoming messages and routed to the correct API.
    """

    name = "dingtalk"
    _DINGTALK_NO_PROXY_HOSTS = (
        "api.dingtalk.com",
        "oapi.dingtalk.com",
        "wss-open-connection-union.dingtalk.com",
    )

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
            if not self.config.use_system_proxy:
                self._ensure_no_proxy_for_dingtalk()
            self._http = httpx.AsyncClient(trust_env=self.config.use_system_proxy)

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

    def _ensure_no_proxy_for_dingtalk(self) -> None:
        """Ensure DingTalk hosts bypass env proxy for SDK WebSocket and HTTP calls."""
        raw_no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        entries = [item.strip() for item in raw_no_proxy.split(",") if item.strip()]
        for host in self._DINGTALK_NO_PROXY_HOSTS:
            if host not in entries:
                entries.append(host)
        merged = ",".join(entries)
        os.environ["NO_PROXY"] = merged
        os.environ["no_proxy"] = merged
        logger.info("DingTalk proxy disabled via config (NO_PROXY hosts injected)")

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

    async def _download_image(self, download_code: str) -> str | None:
        """Download an image from DingTalk using its download code.

        Returns the local file path on success, None on failure.
        """
        token = await self._get_access_token()
        if not token or not self._http:
            return None

        try:
            # Step 1: Convert downloadCode to a temporary download URL
            url = "https://api.dingtalk.com/v1.0/robot/messageFiles/download"
            resp = await self._http.post(
                url,
                json={"robotCode": self.config.client_id, "downloadCode": download_code},
                headers={"x-acs-dingtalk-access-token": token},
            )
            resp.raise_for_status()
            download_url = resp.json().get("downloadUrl")
            if not download_url:
                logger.error("DingTalk image download: no downloadUrl in response")
                return None

            # Step 2: Download the actual image bytes
            img_resp = await self._http.get(download_url, follow_redirects=True)
            img_resp.raise_for_status()

            # Determine extension from Content-Type
            ct = img_resp.headers.get("content-type", "")
            ext_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "image/bmp": ".bmp",
            }
            ext = ext_map.get(ct.split(";")[0].strip(), ".jpg")

            # Step 3: Save to ~/.nanobot/media/
            # Sanitise download_code for use as filename (may contain / + = etc.)
            safe_name = hashlib.md5(download_code.encode()).hexdigest()[:16]
            media_dir = Path.home() / ".nanobot" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            file_path = media_dir / f"dingtalk_{safe_name}{ext}"
            file_path.write_bytes(img_resp.content)

            logger.debug(f"Downloaded DingTalk image to {file_path}")
            return str(file_path)

        except Exception as e:
            logger.error(f"Failed to download DingTalk image: {e}")
            return None

    async def _upload_media(self, file_path: str, media_type: str = "image") -> str | None:
        """Upload a media file to DingTalk and return the mediaId.

        Uses the old OApi endpoint which returns a media_id that can be
        used with ``sampleImageMsg`` (and similar) message keys.
        """
        token = await self._get_access_token()
        if not token or not self._http:
            return None

        url = f"https://oapi.dingtalk.com/media/upload?access_token={token}&type={media_type}"

        path = Path(file_path)
        if not path.exists():
            logger.error(f"Media file not found: {file_path}")
            return None

        # Guess MIME type
        suffix = path.suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        mime = mime_map.get(suffix, "application/octet-stream")

        try:
            file_bytes = path.read_bytes()
            files = {"media": (path.name, file_bytes, mime)}
            resp = await self._http.post(url, files=files)
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.error(f"DingTalk media upload failed: {data}")
                return None
            media_id = data.get("media_id")
            logger.debug(f"Uploaded media to DingTalk, mediaId: {media_id}")
            return media_id
        except Exception as e:
            logger.error(f"Failed to upload media to DingTalk: {e}")
            return None

    @staticmethod
    def _build_preview_title(
        content: str,
        fallback: str = "Nanobot Reply",
        max_chars: int = 42,
    ) -> str:
        """Build a short preview title for DingTalk markdown messages."""
        if not content:
            return fallback

        preview = ""
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # Remove common markdown prefix markers from the first content line.
            line = line.lstrip("#>*-` ")
            line = line.replace("**", "").replace("__", "").replace("`", "")
            line = " ".join(line.split())
            if line:
                preview = line
                break

        if not preview:
            return fallback
        if len(preview) <= max_chars:
            return preview
        return f"{preview[:max_chars - 3]}..."

    @staticmethod
    def _is_http_url(value: str) -> bool:
        """Return True when the media reference is an HTTP(S) URL."""
        return urlparse(value).scheme in ("http", "https")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through DingTalk (private or group)."""
        if self._is_progress_notice(msg):
            logger.debug("Drop DingTalk progress notice for chat_id={}", msg.chat_id)
            return

        token = await self._get_access_token()
        if not token:
            return

        headers = {"x-acs-dingtalk-access-token": token}
        is_group = msg.metadata.get("is_group", False) if msg.metadata else False
        # Fallback: detect group conversation by chat_id prefix
        if not is_group and msg.chat_id and msg.chat_id.startswith("cid"):
            is_group = True

        preview_title = self._build_preview_title(msg.content)

        if is_group:
            # groupMessages/send: sends to a group conversation
            # https://open.dingtalk.com/document/orgapp/robot-send-group-chat-message
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            data = {
                "robotCode": self.config.client_id,
                "openConversationId": msg.chat_id,
                "msgKey": "sampleMarkdown",
                "msgParam": json.dumps({
                    "text": msg.content,
                    "title": preview_title,
                }, ensure_ascii=False),
            }
        else:
            # oToMessages/batchSend: sends to individual users (private chat)
            # https://open.dingtalk.com/document/orgapp/robot-batch-send-messages
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            data = {
                "robotCode": self.config.client_id,
                "userIds": [msg.chat_id],
                "msgKey": "sampleMarkdown",
                "msgParam": json.dumps({
                    "text": msg.content,
                    "title": preview_title,
                }, ensure_ascii=False),
            }

        if not self._http:
            logger.warning("DingTalk HTTP client not initialized, cannot send")
            return

        # Send text/markdown content
        try:
            resp = await self._http.post(url, json=data, headers=headers)
            if resp.status_code != 200:
                logger.error("DingTalk send failed: {}", resp.text)
            else:
                logger.debug("DingTalk message sent to {}", msg.chat_id)
        except Exception as e:
            logger.error("Error sending DingTalk message: {}", e)

        # Send images (if any)
        for media_path in (msg.media or []):
            photo_ref = media_path
            if not self._is_http_url(media_path):
                media_id = await self._upload_media(media_path)
                if not media_id:
                    logger.warning(f"Skipping image send, upload failed: {media_path}")
                    continue
                photo_ref = media_id

            if is_group:
                img_url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
                img_data = {
                    "robotCode": self.config.client_id,
                    "openConversationId": msg.chat_id,
                    "msgKey": "sampleImageMsg",
                    "msgParam": json.dumps({"photoURL": photo_ref}),
                }
            else:
                img_url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
                img_data = {
                    "robotCode": self.config.client_id,
                    "userIds": [msg.chat_id],
                    "msgKey": "sampleImageMsg",
                    "msgParam": json.dumps({"photoURL": photo_ref}),
                }

            try:
                img_resp = await self._http.post(img_url, json=img_data, headers=headers)
                if img_resp.status_code != 200:
                    logger.error(f"DingTalk image send failed: {img_resp.text}")
                else:
                    logger.debug(f"DingTalk image sent to {msg.chat_id}")
            except Exception as e:
                logger.error(f"Error sending DingTalk image: {e}")

    async def _on_message(self, content: str, sender_id: str, sender_name: str,
                          chat_id: str | None = None, is_group: bool = False,
                          conversation_title: str = "",
                          image_download_codes: list[str] | None = None) -> None:
        """Handle incoming message (called by NanobotDingTalkHandler).

        Delegates to BaseChannel._handle_message() which enforces allow_from
        permission checks before publishing to the bus.
        """
        try:
            effective_chat_id = chat_id or sender_id
            logger.info(f"DingTalk inbound: {content} from {sender_name}"
                        f"{' (group)' if is_group else ''}"
                        f"{f' in [{conversation_title}]' if conversation_title else ''}")

            # Download images and build media paths
            content_parts = []
            media_paths = []

            if content:
                content_parts.append(content)

            if image_download_codes:
                for code in image_download_codes:
                    file_path = await self._download_image(code)
                    if file_path:
                        media_paths.append(file_path)
                        content_parts.append(f"[image: {file_path}]")
                    else:
                        content_parts.append("[image: download failed]")

            effective_content = "\n".join(content_parts) if content_parts else "[empty message]"

            # For group chat, prepend sender name so the agent knows who is speaking
            if is_group:
                prefix = f"[群:{conversation_title}] " if conversation_title else ""
                effective_content = f"{prefix}{sender_name}: {effective_content}"
            await self._handle_message(
                sender_id=sender_id,
                chat_id=effective_chat_id,
                content=effective_content,
                media=media_paths,
                metadata={
                    "sender_name": sender_name,
                    "platform": "dingtalk",
                    "is_group": is_group,
                    "conversation_title": conversation_title,
                },
            )
        except Exception as e:
            logger.error("Error publishing DingTalk message: {}", e)
