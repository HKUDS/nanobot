"""DingTalk/DingDing channel implementation using Stream Mode."""

import asyncio
import json
import mimetypes
import os
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base
from nanobot.security.network import validate_resolved_url, validate_url_target

DINGTALK_MAX_REMOTE_MEDIA_BYTES = 20 * 1024 * 1024
DINGTALK_MAX_REMOTE_MEDIA_REDIRECTS = 3

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
            elif chatbot_msg.extensions.get("content", {}).get("recognition"):
                content = chatbot_msg.extensions["content"]["recognition"].strip()
            if not content:
                content = message.data.get("text", {}).get("content", "").strip()

            # Handle file/image messages
            file_paths = []
            if chatbot_msg.message_type == "picture" and chatbot_msg.image_content:
                download_code = chatbot_msg.image_content.download_code
                if download_code:
                    sender_uid = chatbot_msg.sender_staff_id or chatbot_msg.sender_id or "unknown"
                    fp = await self.channel._download_dingtalk_file(download_code, "image.jpg", sender_uid)
                    if fp:
                        file_paths.append(fp)
                        content = content or "[Image]"

            elif chatbot_msg.message_type == "file":
                download_code = message.data.get("content", {}).get("downloadCode") or message.data.get("downloadCode")
                fname = message.data.get("content", {}).get("fileName") or message.data.get("fileName") or "file"
                if download_code:
                    sender_uid = chatbot_msg.sender_staff_id or chatbot_msg.sender_id or "unknown"
                    fp = await self.channel._download_dingtalk_file(download_code, fname, sender_uid)
                    if fp:
                        file_paths.append(fp)
                        content = content or "[File]"

            elif chatbot_msg.message_type == "richText" and chatbot_msg.rich_text_content:
                rich_list = chatbot_msg.rich_text_content.rich_text_list or []
                for item in rich_list:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "text":
                        t = item.get("text", "").strip()
                        if t:
                            content = (content + " " + t).strip() if content else t
                    elif item.get("downloadCode"):
                        dc = item["downloadCode"]
                        fname = item.get("fileName") or "file"
                        sender_uid = chatbot_msg.sender_staff_id or chatbot_msg.sender_id or "unknown"
                        fp = await self.channel._download_dingtalk_file(dc, fname, sender_uid)
                        if fp:
                            file_paths.append(fp)
                            content = content or "[File]"

            if file_paths:
                file_list = "\n".join("- " + p for p in file_paths)
                content = content + "\n\nReceived files:\n" + file_list

            if not content:
                logger.warning(
                    "Received empty or unsupported message type: {}",
                    chatbot_msg.message_type,
                )
                return AckMessage.STATUS_OK, "OK"

            sender_id = chatbot_msg.sender_staff_id or chatbot_msg.sender_id
            sender_name = chatbot_msg.sender_nick or "Unknown"

            conversation_type = message.data.get("conversationType")
            conversation_id = (
                message.data.get("conversationId")
                or message.data.get("openConversationId")
            )

            logger.info("Received DingTalk message from {} ({}): {}", sender_name, sender_id, content)

            # Forward to Nanobot via _on_message (non-blocking).
            # Store reference to prevent GC before task completes.
            task = asyncio.create_task(
                self.channel._on_message(
                    content,
                    sender_id,
                    sender_name,
                    conversation_type,
                    conversation_id,
                )
            )
            self.channel._background_tasks.add(task)
            task.add_done_callback(self.channel._background_tasks.discard)

            return AckMessage.STATUS_OK, "OK"

        except Exception as e:
            logger.error("Error processing DingTalk message: {}", e)
            # Return OK to avoid retry loop from DingTalk server
            return AckMessage.STATUS_OK, "Error"


class DingTalkConfig(Base):
    """DingTalk channel configuration using Stream mode."""

    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    allow_from: list[str] = Field(default_factory=list)
    allow_remote_media_redirects: bool = False
    remote_media_redirect_allowed_hosts: list[str] = Field(default_factory=list)


class DingTalkChannel(BaseChannel):
    """
    DingTalk channel using Stream Mode.

    Uses WebSocket to receive events via `dingtalk-stream` SDK.
    Uses direct HTTP API to send messages (SDK is mainly for receiving).

    Supports both private (1:1) and group chats.
    Group chat_id is stored with a "group:" prefix to route replies back.
    """

    name = "dingtalk"
    display_name = "DingTalk"
    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    _AUDIO_EXTS = {".amr", ".mp3", ".wav", ".ogg", ".m4a", ".aac"}
    _VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    _ZIP_BEFORE_UPLOAD_EXTS = {".htm", ".html"}

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return DingTalkConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = DingTalkConfig.model_validate(config)
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
        if ext in self._IMAGE_EXTS:
            return "image"
        if ext in self._AUDIO_EXTS:
            return "voice"
        if ext in self._VIDEO_EXTS:
            return "video"
        return "file"

    def _guess_filename(self, media_ref: str, upload_type: str) -> str:
        name = os.path.basename(urlparse(media_ref).path)
        return name or {"image": "image.jpg", "voice": "audio.amr", "video": "video.mp4"}.get(upload_type, "file.bin")

    @staticmethod
    def _zip_bytes(filename: str, data: bytes) -> tuple[bytes, str, str]:
        stem = Path(filename).stem or "attachment"
        safe_name = filename or "attachment.bin"
        zip_name = f"{stem}.zip"
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(safe_name, data)
        return buffer.getvalue(), zip_name, "application/zip"

    def _normalize_upload_payload(
        self,
        filename: str,
        data: bytes,
        content_type: str | None,
    ) -> tuple[bytes, str, str | None]:
        ext = Path(filename).suffix.lower()
        if ext in self._ZIP_BEFORE_UPLOAD_EXTS or content_type == "text/html":
            logger.info(
                "DingTalk does not accept raw HTML attachments, zipping {} before upload",
                filename,
            )
            return self._zip_bytes(filename, data)
        return data, filename, content_type

    def _validate_remote_media_url(self, media_ref: str) -> bool:
        ok, err = validate_url_target(media_ref)
        if not ok:
            logger.warning("DingTalk remote media URL blocked ref={} reason={}", media_ref, err)
            return False
        return True

    def _redirect_host_allowed(self, current_url: str, next_url: str) -> bool:
        current_host = (urlparse(current_url).hostname or "").lower()
        next_host = (urlparse(next_url).hostname or "").lower()
        if not next_host:
            return False
        if next_host == current_host:
            return True
        allowed_hosts = {host.lower() for host in self.config.remote_media_redirect_allowed_hosts}
        return next_host in allowed_hosts

    def _next_remote_media_url(self, current_url: str, location: str | None) -> str | None:
        if not self.config.allow_remote_media_redirects:
            logger.warning("DingTalk media download redirect refused ref={}", current_url)
            return None
        if not location:
            logger.warning("DingTalk media download redirect without Location ref={}", current_url)
            return None
        next_url = urljoin(current_url, location)
        if not self._redirect_host_allowed(current_url, next_url):
            logger.warning(
                "DingTalk media download cross-host redirect refused ref={} next={}",
                current_url,
                next_url,
            )
            return None
        if not self._validate_remote_media_url(next_url):
            return None
        return next_url

    async def _fetch_remote_media_bytes(
        self,
        media_ref: str,
    ) -> tuple[bytes | None, str | None]:
        """Fetch a remote media URL with SSRF, redirect, and size checks."""
        if not self._http:
            return None, None

        if not self._validate_remote_media_url(media_ref):
            return None, None

        try:
            # Prefer streaming with a running byte cap so large responses are not
            # materialized before the limit is enforced. Test fakes may only
            # implement get(), so keep a small compatibility fallback below.
            stream = getattr(self._http, "stream", None)
            if stream is not None:
                current_url = media_ref
                for _ in range(DINGTALK_MAX_REMOTE_MEDIA_REDIRECTS + 1):
                    async with stream("GET", current_url, follow_redirects=False) as resp:
                        final_ok, final_err = validate_resolved_url(str(resp.url))
                        if not final_ok:
                            logger.warning(
                                "DingTalk remote media redirect blocked ref={} final={} reason={}",
                                media_ref,
                                resp.url,
                                final_err,
                            )
                            return None, None
                        if 300 <= resp.status_code < 400:
                            next_url = self._next_remote_media_url(
                                str(resp.url), resp.headers.get("location")
                            )
                            if not next_url:
                                return None, None
                            current_url = next_url
                            continue
                        if resp.status_code >= 400:
                            logger.warning(
                                "DingTalk media download failed status={} ref={}",
                                resp.status_code,
                                current_url,
                            )
                            return None, None
                        chunks: list[bytes] = []
                        total = 0
                        async for chunk in resp.aiter_bytes():
                            total += len(chunk)
                            if total > DINGTALK_MAX_REMOTE_MEDIA_BYTES:
                                logger.warning(
                                    "DingTalk media download too large ref={} bytes>{}",
                                    current_url,
                                    DINGTALK_MAX_REMOTE_MEDIA_BYTES,
                                )
                                return None, None
                            chunks.append(chunk)
                        return b"".join(chunks), (resp.headers.get("content-type") or "")
                logger.warning("DingTalk media download exceeded redirect limit ref={}", media_ref)
                return None, None

            current_url = media_ref
            for _ in range(DINGTALK_MAX_REMOTE_MEDIA_REDIRECTS + 1):
                resp = await self._http.get(current_url, follow_redirects=False)
                final_ok, final_err = validate_resolved_url(str(getattr(resp, "url", current_url)))
                if not final_ok:
                    logger.warning(
                        "DingTalk remote media redirect blocked ref={} final={} reason={}",
                        media_ref,
                        getattr(resp, "url", current_url),
                        final_err,
                    )
                    return None, None
                if 300 <= resp.status_code < 400:
                    next_url = self._next_remote_media_url(
                        str(getattr(resp, "url", current_url)), resp.headers.get("location")
                    )
                    if not next_url:
                        return None, None
                    current_url = next_url
                    continue
                if resp.status_code >= 400:
                    logger.warning(
                        "DingTalk media download failed status={} ref={}",
                        resp.status_code,
                        current_url,
                    )
                    return None, None
                if len(resp.content) > DINGTALK_MAX_REMOTE_MEDIA_BYTES:
                    logger.warning(
                        "DingTalk media download too large ref={} bytes>{}",
                        current_url,
                        DINGTALK_MAX_REMOTE_MEDIA_BYTES,
                    )
                    return None, None
                return resp.content, (resp.headers.get("content-type") or "")
            logger.warning("DingTalk media download exceeded redirect limit ref={}", media_ref)
            return None, None
        except httpx.TransportError as e:
            logger.error("DingTalk media download network error ref={} err={}", media_ref, e)
            raise
        except Exception as e:
            logger.error("DingTalk media download error ref={} err={}", media_ref, e)
            return None, None

    async def _read_media_bytes(
        self,
        media_ref: str,
    ) -> tuple[bytes | None, str | None, str | None]:
        if not media_ref:
            return None, None, None

        if self._is_http_url(media_ref):
            data, raw_content_type = await self._fetch_remote_media_bytes(media_ref)
            if data is None:
                return None, None, None
            content_type = (raw_content_type or "").split(";")[0].strip()
            filename = self._guess_filename(media_ref, self._guess_upload_type(media_ref))
            return data, filename, content_type or None

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
        except httpx.TransportError as e:
            logger.error("DingTalk media upload network error type={} err={}", media_type, e)
            raise
        except Exception as e:
            logger.error("DingTalk media upload error type={} err={}", media_type, e)
            return None

    async def _send_batch_message(
        self,
        token: str,
        chat_id: str,
        msg_key: str,
        msg_param: dict[str, Any],
    ) -> bool:
        if not self._http:
            logger.warning("DingTalk HTTP client not initialized, cannot send")
            return False

        headers = {"x-acs-dingtalk-access-token": token}
        if chat_id.startswith("group:"):
            # Group chat
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            payload = {
                "robotCode": self.config.client_id,
                "openConversationId": chat_id[6:],  # Remove "group:" prefix,
                "msgKey": msg_key,
                "msgParam": json.dumps(msg_param, ensure_ascii=False),
            }
        else:
            # Private chat
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            payload = {
                "robotCode": self.config.client_id,
                "userIds": [chat_id],
                "msgKey": msg_key,
                "msgParam": json.dumps(msg_param, ensure_ascii=False),
            }

        try:
            resp = await self._http.post(url, json=payload, headers=headers)
            body = resp.text
            if resp.status_code != 200:
                logger.error("DingTalk send failed msgKey={} status={} body={}", msg_key, resp.status_code, body[:500])
                return False
            try:
                result = resp.json()
            except Exception:
                result = {}
            errcode = result.get("errcode")
            if errcode not in (None, 0):
                logger.error("DingTalk send api error msgKey={} errcode={} body={}", msg_key, errcode, body[:500])
                return False
            logger.debug("DingTalk message sent to {} with msgKey={}", chat_id, msg_key)
            return True
        except httpx.TransportError as e:
            logger.error("DingTalk network error sending message msgKey={} err={}", msg_key, e)
            raise
        except Exception as e:
            logger.error("Error sending DingTalk message msgKey={} err={}", msg_key, e)
            return False

    async def _send_markdown_text(self, token: str, chat_id: str, content: str) -> bool:
        return await self._send_batch_message(
            token,
            chat_id,
            "sampleMarkdown",
            {"text": content, "title": "Nanobot Reply"},
        )

    async def _send_media_ref(self, token: str, chat_id: str, media_ref: str) -> bool:
        media_ref = (media_ref or "").strip()
        if not media_ref:
            return True

        upload_type = self._guess_upload_type(media_ref)
        if upload_type == "image" and self._is_http_url(media_ref):
            ok = await self._send_batch_message(
                token,
                chat_id,
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
        data, filename, content_type = self._normalize_upload_payload(filename, data, content_type)
        file_type = Path(filename).suffix.lower().lstrip(".")
        if not file_type:
            guessed = mimetypes.guess_extension(content_type or "")
            file_type = (guessed or ".bin").lstrip(".")
        if file_type == "jpeg":
            file_type = "jpg"

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
            # Verified in production: sampleImageMsg accepts media_id in photoURL.
            ok = await self._send_batch_message(
                token,
                chat_id,
                "sampleImageMsg",
                {"photoURL": media_id},
            )
            if ok:
                return True
            logger.warning("DingTalk image media_id send failed, falling back to file: {}", media_ref)

        return await self._send_batch_message(
            token,
            chat_id,
            "sampleFile",
            {"mediaId": media_id, "fileName": filename, "fileType": file_type},
        )

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through DingTalk."""
        token = await self._get_access_token()
        if not token:
            return

        if msg.content and msg.content.strip():
            await self._send_markdown_text(token, msg.chat_id, msg.content.strip())

        for media_ref in msg.media or []:
            ok = await self._send_media_ref(token, msg.chat_id, media_ref)
            if ok:
                continue
            logger.error("DingTalk media send failed for {}", media_ref)
            # Send visible fallback so failures are observable by the user.
            filename = self._guess_filename(media_ref, self._guess_upload_type(media_ref))
            await self._send_markdown_text(
                token,
                msg.chat_id,
                f"[Attachment send failed: {filename}]",
            )

    async def _on_message(
        self,
        content: str,
        sender_id: str,
        sender_name: str,
        conversation_type: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        """Handle incoming message (called by NanobotDingTalkHandler).

        Delegates to BaseChannel._handle_message() which enforces allow_from
        permission checks before publishing to the bus.
        """
        try:
            logger.info("DingTalk inbound: {} from {}", content, sender_name)
            is_group = conversation_type == "2" and conversation_id
            chat_id = f"group:{conversation_id}" if is_group else sender_id
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=str(content),
                metadata={
                    "sender_name": sender_name,
                    "platform": "dingtalk",
                    "conversation_type": conversation_type,
                },
            )
        except Exception as e:
            logger.error("Error publishing DingTalk message: {}", e)

    async def _download_dingtalk_file(
        self,
        download_code: str,
        filename: str,
        sender_id: str,
    ) -> str | None:
        """Download a DingTalk file to the media directory, return local path."""
        from nanobot.config.paths import get_media_dir

        try:
            token = await self._get_access_token()
            if not token or not self._http:
                logger.error("DingTalk file download: no token or http client")
                return None

            # Step 1: Exchange downloadCode for a temporary download URL
            api_url = "https://api.dingtalk.com/v1.0/robot/messageFiles/download"
            headers = {"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"}
            payload = {"downloadCode": download_code, "robotCode": self.config.client_id}
            resp = await self._http.post(api_url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error("DingTalk get download URL failed: status={}, body={}", resp.status_code, resp.text)
                return None

            result = resp.json()
            download_url = result.get("downloadUrl")
            if not download_url:
                logger.error("DingTalk download URL not found in response: {}", result)
                return None

            # Step 2: Download the file content
            file_resp = await self._http.get(download_url, follow_redirects=True)
            if file_resp.status_code != 200:
                logger.error("DingTalk file download failed: status={}", file_resp.status_code)
                return None

            # Save to media directory (accessible under workspace)
            download_dir = get_media_dir("dingtalk") / sender_id
            download_dir.mkdir(parents=True, exist_ok=True)
            file_path = download_dir / filename
            await asyncio.to_thread(file_path.write_bytes, file_resp.content)
            logger.info("DingTalk file saved: {}", file_path)
            return str(file_path)
        except Exception as e:
            logger.error("DingTalk file download error: {}", e)
            return None
