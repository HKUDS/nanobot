"""
WeCom (企业微信) channel implementation using HTTP callback.

Supports:
- Receiving messages via HTTP webhook callback
- Sending messages via WeCom API
- Message encryption/decryption (SHA1 signature + AES-256-CBC)
- Multiple message types: text, image, file, voice, video
"""

import asyncio
import base64
import hashlib
import json
import os
import struct
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loguru import logger
try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    web = None

import httpx

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WeComConfig

# WeCom API endpoints
WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


def sha1(text: str) -> str:
    """Calculate SHA1 hash."""
    return hashlib.sha1(text.encode()).hexdigest()


def compute_signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """Compute message signature for WeCom callback verification."""
    arr = sorted([token, timestamp, nonce, encrypt])
    return sha1("".join(arr))


def decode_aes_key(aes_key: str) -> bytes:
    """Decode AES key from Base64."""
    if not aes_key.endswith("="):
        aes_key += "="
    return base64.b64decode(aes_key)


def pkcs7_unpad(data: bytes) -> bytes:
    """Remove PKCS7 padding."""
    pad = data[-1]
    if pad < 1 or pad > 32:
        return data
    return data[:-pad]


def decrypt_wecom_message(aes_key: str, cipher_text: str) -> tuple[str, str]:
    """
    Decrypt WeCom callback message.

    Returns:
        (message, corp_id) - Decrypted message content and corp ID
    """
    key = decode_aes_key(aes_key)
    iv = key[:16]
    cipher_text_bytes = base64.b64decode(cipher_text)

    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(cipher_text_bytes)
    decrypted = pkcs7_unpad(decrypted)

    # Parse format: msg_len(4) + msg + corp_id
    msg_len = struct.unpack(">I", decrypted[16:20])[0]
    msg = decrypted[20:20 + msg_len].decode("utf-8")
    corp_id = decrypted[20 + msg_len:].decode("utf-8")

    return msg, corp_id


def encrypt_wecom_message(aes_key: str, corp_id: str, msg: str) -> str:
    """Encrypt message for WeCom callback response."""
    key = decode_aes_key(aes_key)
    iv = key[:16]

    # Format: random(16) + msg_len(4) + msg + corp_id
    import secrets
    random_bytes = secrets.token_bytes(16)
    msg_bytes = msg.encode("utf-8")
    corp_id_bytes = corp_id.encode("utf-8")
    msg_len = struct.pack(">I", len(msg_bytes))

    text = random_bytes + msg_len + msg_bytes + corp_id_bytes

    # PKCS7 padding
    pad_len = 32 - (len(text) % 32)
    text += bytes([pad_len] * pad_len)

    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(text)

    return base64.b64encode(encrypted).decode("utf-8")


class WeComChannel(BaseChannel):
    """
    WeCom (企业微信) channel using HTTP webhook callback.

    Requirements:
    - WeCom internal app (自建应用)
    - corp_id, corp_secret, agent_id
    - Callback URL, Token, EncodingAESKey configured in WeCom admin console
    - HTTP server accessible from WeCom (public IP or tunnel)
    """

    name = "wecom"

    def __init__(self, config: WeComConfig, bus: MessageBus):
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp is required for WeCom channel. Install: pip install aiohttp")

        super().__init__(config, bus)
        self.config: WeComConfig = config

        # WeCom API client
        self._http_client: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._token_expires_at: float = 0
        self._token_lock = asyncio.Lock()

        # Webhook server
        self._app: Any = None
        self._runner: Any = None
        self._site: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # Deduplication cache
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()

        # Media upload API cache
        self._media_upload_api: str | None = None

    async def start(self) -> None:
        """Start WeCom channel with HTTP/HTTPS webhook server."""
        if not self.config.corp_id or not self.config.corp_secret:
            logger.error("WeCom corp_id and corp_secret not configured")
            return

        if not self.config.agent_id:
            logger.error("WeCom agent_id not configured")
            return

        self._running = True
        self._loop = asyncio.get_running_loop()

        # Create HTTP client for WeCom API calls
        self._http_client = httpx.AsyncClient(
            base_url=WECOM_API_BASE,
            timeout=30.0,
        )

        # Determine media upload API
        self._media_upload_api = f"media/upload?access_token=%s&type=%s"

        # Setup webhook server
        self._app = web.Application()
        self._app.router.add_get(self.config.webhook_path, self._handle_webhook_get)
        self._app.router.add_post(self.config.webhook_path, self._handle_webhook_post)

        # Start HTTP server
        runner = web.AppRunner(self._app)
        await runner.setup()
        self._runner = runner

        # Get port from config or use default
        port = getattr(self.config, 'webhook_port', 18790)

        # Check if SSL is enabled
        ssl_cert = getattr(self.config, 'ssl_cert', '')
        ssl_key = getattr(self.config, 'ssl_key', '')

        if ssl_cert and ssl_key:
            # HTTPS server with SSL
            import ssl
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(ssl_cert, ssl_key)

            site = web.TCPSite(runner, "0.0.0.0", port, ssl_context=ssl_context)
            await site.start()
            self._site = site

            logger.info("WeCom webhook server started with HTTPS on port {}", port)
            logger.info("Webhook URL: https://your-domain:{}{}", port, self.config.webhook_path)
        else:
            # HTTP server (without SSL)
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            self._site = site

            logger.warning("WeCom webhook running in HTTP mode (without SSL)")
            logger.warning("Enterprise WeChat requires HTTPS for callback URL!")
            logger.warning("Consider using a reverse proxy (nginx/caddy) or configuring SSL certificates")
            logger.info("WeCom webhook server started on port {}", port)
            logger.info("Webhook URL: http://your-domain:{}{}", port, self.config.webhook_path)

        # Keep running
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop WeCom channel."""
        self._running = False

        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        if self._http_client:
            await self._http_client.aclose()

        logger.info("WeCom channel stopped")

    async def _get_access_token(self) -> str:
        """Get WeCom access token with caching."""
        if self._access_token and self._token_expires_at > asyncio.get_event_loop().time() + 300:
            return self._access_token

        async with self._token_lock:
            # Double check
            if self._access_token and self._token_expires_at > asyncio.get_event_loop().time() + 300:
                return self._access_token

            try:
                resp = await self._http_client.get(
                    f"gettoken?corpid={self.config.corp_id}&corpsecret={self.config.corp_secret}"
                )
                data = resp.json()

                if data.get("errcode") != 0:
                    logger.error("Failed to get WeCom access token: {}", data)
                    raise Exception(f"WeCom API error: {data}")

                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 7200)
                self._token_expires_at = asyncio.get_event_loop().time() + expires_in - 300  # 5min buffer

                logger.info("WeCom access token refreshed")
                return self._access_token

            except Exception as e:
                logger.error("Error getting WeCom access token: {}", e)
                raise

    async def _handle_webhook_get(self, request: web.Request) -> web.Response:
        """
        Handle WeCom webhook verification (GET request).

        WeCom sends GET request with msg_signature, timestamp, nonce, echostr
        to verify the callback URL.
        """
        try:
            signature = request.query.get("msg_signature", "")
            timestamp = request.query.get("timestamp", "")
            nonce = request.query.get("nonce", "")
            echostr = request.query.get("echostr", "")

            if not all([signature, timestamp, nonce, echostr]):
                return web.Response(status=400, text="Missing required parameters")

            # Verify signature
            expected_sig = compute_signature(
                self.config.callback_token,
                timestamp,
                nonce,
                echostr
            )

            if signature != expected_sig:
                logger.warning("Invalid WeCom webhook signature")
                return web.Response(status=403, text="Invalid signature")

            # Decrypt echostr for verification
            msg, corp_id = decrypt_wecom_message(self.config.callback_aes_key, echostr)

            if corp_id != self.config.corp_id:
                logger.warning("WeCom corp_id mismatch: {} != {}", corp_id, self.config.corp_id)
                return web.Response(status=403, text="Corp ID mismatch")

            # Return decrypted echostr to complete verification
            return web.Response(text=msg)

        except Exception as e:
            logger.error("Error in WeCom webhook GET: {}", e)
            return web.Response(status=500, text="Internal server error")

    async def _handle_webhook_post(self, request: web.Request) -> web.Response:
        """
        Handle WeCom callback message (POST request).

        Message flow:
        1. Verify signature
        2. Decrypt message
        3. Process message asynchronously
        4. Return success immediately
        """
        try:
            body = await request.text()

            # Parse XML
            import xml.etree.ElementTree as ET
            root = ET.fromstring(body)

            msg_signature = root.findtext("MsgSignature")
            timestamp = root.findtext("TimeStamp")
            nonce = root.findtext("Nonce")
            encrypt = root.findtext("Encrypt")

            if not all([msg_signature, timestamp, nonce, encrypt]):
                return web.Response(status=400, text="Missing required fields")

            # Verify signature
            expected_sig = compute_signature(
                self.config.callback_token,
                timestamp,
                nonce,
                encrypt
            )

            if msg_signature != expected_sig:
                logger.warning("Invalid WeCom message signature")
                return web.Response(status=403, text="Invalid signature")

            # Decrypt message
            decrypted_msg, corp_id = decrypt_wecom_message(
                self.config.callback_aes_key,
                encrypt
            )

            if corp_id != self.config.corp_id:
                logger.warning("WeCom corp_id mismatch")
                return web.Response(status=403, text="Corp ID mismatch")

            # Parse message XML
            msg_root = ET.fromstring(decrypted_msg)
            msg_type = msg_root.findtext("MsgType")
            msg_id = msg_root.findtext("MsgId") or msg_root.findtext("AgentId") or ""

            # Deduplication check
            if msg_id in self._processed_message_ids:
                logger.debug("Duplicate message {} ignored", msg_id)
                return web.Response(text="success")

            self._processed_message_ids[msg_id] = None
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            # Process message asynchronously
            asyncio.create_task(self._process_message(msg_root))

            # Return success immediately (WeCom requires response within 5 seconds)
            return web.Response(text="success")

        except Exception as e:
            logger.error("Error in WeCom webhook POST: {}", e)
            return web.Response(status=500, text="Internal server error")

    async def _process_message(self, msg_root) -> None:
        """Process incoming WeCom message."""
        try:
            msg_type = msg_root.findtext("MsgType")
            to_user = msg_root.findtext("ToUserName")
            from_user = msg_root.findtext("FromUserName")
            create_time = msg_root.findtext("CreateTime")

            content_parts = []
            media_paths = []

            # Parse content based on message type
            if msg_type == "text":
                content = msg_root.findtext("Content") or ""
                content_parts.append(content)

            elif msg_type == "image":
                media_id = msg_root.findtext("MediaId")
                if media_id:
                    file_path = await self._download_media(media_id, "image")
                    if file_path:
                        media_paths.append(file_path)
                        content_parts.append(f"[image: {os.path.basename(file_path)}]")
                    else:
                        content_parts.append("[image: download failed]")

            elif msg_type == "voice":
                media_id = msg_root.findtext("MediaId")
                # WeCom may provide Recognition field for voice-to-text
                recognition = msg_root.findtext("Recognition")
                if recognition:
                    content_parts.append(recognition)
                elif media_id:
                    # Download and process voice (could integrate STT here)
                    file_path = await self._download_media(media_id, "voice")
                    if file_path:
                        media_paths.append(file_path)
                        content_parts.append(f"[voice: {os.path.basename(file_path)}]")
                    else:
                        content_parts.append("[voice: download failed]")

            elif msg_type == "video":
                media_id = msg_root.findtext("MediaId")
                if media_id:
                    file_path = await self._download_media(media_id, "video")
                    if file_path:
                        media_paths.append(file_path)
                        content_parts.append(f"[video: {os.path.basename(file_path)}]")
                    else:
                        content_parts.append("[video: download failed]")

            elif msg_type == "file":
                media_id = msg_root.findtext("MediaId")
                file_name = msg_root.findtext("FileName") or "unknown"
                if media_id:
                    file_path = await self._download_media(media_id, "file")
                    if file_path:
                        media_paths.append(file_path)
                        content_parts.append(f"[file: {file_name}]")
                    else:
                        content_parts.append(f"[file: {file_name} - download failed]")

            elif msg_type == "event":
                event = msg_root.findtext("Event")
                if event == "subscribe":
                    content_parts.append("[用户订阅了应用]")
                elif event == "unsubscribe":
                    content_parts.append("[用户取消订阅]")
                elif event == "enter_agent":
                    content_parts.append("[用户进入应用]")
                else:
                    content_parts.append(f"[event: {event}]")

            else:
                content_parts.append(f"[{msg_type} message]")

            content = "\n".join(content_parts) if content_parts else ""

            if not content and not media_paths:
                return

            # Forward to message bus
            await self._handle_message(
                sender_id=from_user,
                chat_id=from_user,  # WeCom uses user_id as chat_id for direct messages
                content=content,
                media=media_paths,
                metadata={
                    "msg_type": msg_type,
                    "to_user": to_user,
                    "create_time": create_time,
                }
            )

        except Exception as e:
            logger.error("Error processing WeCom message: {}", e)

    async def _download_media(self, media_id: str, media_type: str = "file") -> str | None:
        """Download media from WeCom and save to local disk."""
        try:
            access_token = await self._get_access_token()

            url = f"media/get?access_token={access_token}&media_id={media_id}"

            resp = await self._http_client.get(url)
            if resp.status_code != 200:
                logger.error("Failed to download media: HTTP {}", resp.status_code)
                return None

            # Determine file extension
            ext_map = {
                "image": ".jpg",
                "voice": ".amr",
                "video": ".mp4",
                "file": "",
            }
            ext = ext_map.get(media_type, "")

            # Get content type if available
            content_type = resp.headers.get("content-type", "")
            if "jpeg" in content_type or "jpg" in content_type:
                ext = ".jpg"
            elif "png" in content_type:
                ext = ".png"
            elif "gif" in content_type:
                ext = ".gif"

            # Save to temp file
            media_dir = Path.home() / ".nanobot" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)

            file_path = media_dir / f"{media_id[:16]}{ext}"
            file_path.write_bytes(resp.content)

            logger.debug("Downloaded {} to {}", media_type, file_path)
            return str(file_path)

        except Exception as e:
            logger.error("Error downloading WeCom media: {}", e)
            return None

    async def send(self, msg: OutboundMessage) -> None:
        """Send message through WeCom."""
        if not self._http_client:
            logger.warning("WeCom HTTP client not initialized")
            return

        try:
            access_token = await self._get_access_token()

            # Send media files first
            for file_path in msg.media:
                if not os.path.isfile(file_path):
                    logger.warning("Media file not found: {}", file_path)
                    continue

                await self._send_file(
                    access_token,
                    msg.chat_id,
                    file_path
                )

            # Send text content
            if msg.content and msg.content.strip():
                await self._send_text(
                    access_token,
                    msg.chat_id,
                    msg.content
                )

        except Exception as e:
            logger.error("Error sending WeCom message: {}", e)

    async def _send_text(self, access_token: str, user_id: str, content: str) -> bool:
        """Send text message."""
        try:
            # Split long messages (WeCom limit is 2048 bytes)
            max_bytes = 2048
            messages = []

            current_msg = ""
            for line in content.split("\n"):
                test_msg = current_msg + "\n" + line if current_msg else line
                if len(test_msg.encode("utf-8")) <= max_bytes:
                    current_msg = test_msg
                else:
                    if current_msg:
                        messages.append(current_msg)
                    current_msg = line

                    # If single line is too long, split it
                    while len(current_msg.encode("utf-8")) > max_bytes:
                        # Find safe split point
                        split_pos = max_bytes
                        while split_pos > 0 and ord(current_msg[split_pos - 1]) > 127:
                            split_pos -= 1

                        messages.append(current_msg[:split_pos])
                        current_msg = current_msg[split_pos:]

            if current_msg:
                messages.append(current_msg)

            # Send each message
            for msg in messages:
                data = {
                    "touser": user_id,
                    "msgtype": "text",
                    "agentid": self.config.agent_id,
                    "text": {"content": msg}
                }

                resp = await self._http_client.post(
                    f"message/send?access_token={access_token}",
                    json=data
                )

                result = resp.json()
                if result.get("errcode") != 0:
                    logger.error("Failed to send WeCom text message: {}", result)
                    return False

            return True

        except Exception as e:
            logger.error("Error sending WeCom text: {}", e)
            return False

    async def _send_file(self, access_token: str, user_id: str, file_path: str) -> bool:
        """Send file/image message."""
        try:
            ext = os.path.splitext(file_path)[1].lower()

            # Determine media type
            if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}:
                media_type = "image"
            elif ext in {".amr", ".silk", ".mp3", ".wav"}:
                media_type = "voice"
            elif ext in {".mp4", ".avi", ".mov", ".mkv"}:
                media_type = "video"
            else:
                media_type = "file"

            # Upload media
            with open(file_path, "rb") as f:
                files = {"media": (os.path.basename(file_path), f, "application/octet-stream")}
                upload_resp = await self._http_client.post(
                    f"media/upload?access_token={access_token}&type={media_type}",
                    files=files
                )

            upload_data = upload_resp.json()
            if upload_data.get("errcode") != 0:
                logger.error("Failed to upload WeCom media: {}", upload_data)
                return False

            media_id = upload_data.get("media_id")
            if not media_id:
                logger.error("No media_id in upload response")
                return False

            # Send message
            msg_type_map = {
                "image": "image",
                "voice": "voice",
                "video": "video",
                "file": "file",
            }

            data = {
                "touser": user_id,
                "msgtype": msg_type_map[media_type],
                "agentid": self.config.agent_id,
                msg_type_map[media_type]: {"media_id": media_id}
            }

            if media_type == "video":
                # Video requires title and description
                data[media_type]["title"] = os.path.basename(file_path)
                data[media_type]["description"] = "Video from nanobot"

            resp = await self._http_client.post(
                f"message/send?access_token={access_token}",
                json=data
            )

            result = resp.json()
            if result.get("errcode") != 0:
                logger.error("Failed to send WeCom {} message: {}", media_type, result)
                return False

            return True

        except Exception as e:
            logger.error("Error sending WeCom file: {}", e)
            return False
