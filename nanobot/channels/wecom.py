"""Enterprise WeChat (WeCom) Smart Robot channel using WebSocket.

This module implements the WeCom Smart Robot (AI Bot) channel using WebSocket
long connection, following the official @wecom/aibot-node-sdk pattern.

Official SDK: https://github.com/chengyongru/wecom_aibot_sdk
WebSocket URL: wss://openws.work.weixin.qq.com

Configuration requires only 2 items:
- bot_id: Your WeCom bot ID
- secret: Your WeCom bot secret

Example config:
    channels:
      wecom:
        enabled: true
        bot_id: "wb1234567890abcdef"
        secret: "your_secret_key_here"
        allow_from: []  # Empty = allow all users

Features:
- Text and Markdown messages
- Image, voice, file messages (with download/upload)
- Template card messages
- Streaming replies
- Event callbacks (enter_chat, card_click)
- Auto-reconnect with backoff
- Message deduplication
- AES file decryption
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union

import aiohttp
import websockets
from Crypto.Cipher import AES
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import WeComConfig


class WsCmd(str, Enum):
    """WebSocket command types from official SDK."""

    SUBSCRIBE = "aibot_subscribe"
    CALLBACK = "aibot_msg_callback"
    EVENT_CALLBACK = "aibot_event_callback"
    RESPOND_MSG = "aibot_respond_msg"
    HEARTBEAT = "ping"
    REPLY = "reply"
    REPLY_STREAM = "reply_stream"
    REPLY_WELCOME = "reply_welcome"
    REPLY_TEMPLATE_CARD = "reply_template_card"
    UPDATE_TEMPLATE_CARD = "update_template_card"
    SEND_MESSAGE = "send_message"


class MsgType(str, Enum):
    """Message types from official SDK."""

    TEXT = "text"
    IMAGE = "image"
    MIXED = "mixed"
    VOICE = "voice"
    FILE = "file"


class EventType(str, Enum):
    """Event types from official SDK."""

    ENTER_CHAT = "enter_chat"
    CARD_CLICK = "card_click"


@dataclass
class MessageContent:
    """Parsed message content."""

    text: str = ""
    media_paths: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AESCipher:
    """AES decryption for WeCom files."""

    @staticmethod
    def decrypt(encrypted_data: bytes, aes_key: str) -> bytes:
        """
        Decrypt file using AES-256-CBC.

        Args:
            encrypted_data: Encrypted file data
            aes_key: Base64-encoded AES key

        Returns:
            Decrypted file data
        """
        try:
            # Decode base64 key
            key = base64.b64decode(aes_key)

            # Extract IV from first 16 bytes
            iv = encrypted_data[:16]
            ciphertext = encrypted_data[16:]

            # Create cipher and decrypt
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(ciphertext)

            # Remove PKCS7 padding
            padding = decrypted[-1]
            if padding > 16:
                raise ValueError(f"Invalid padding: {padding}")

            return decrypted[:-padding]

        except Exception as e:
            logger.error("AES decryption failed: {}", e)
            raise


class WeComApiClient:
    """HTTP API client for file operations."""

    def __init__(self, bot_id: str, secret: str):
        self.bot_id = bot_id
        self.secret = secret
        self._session: Optional[aiohttp.ClientSession] = None
        self._access_token: Optional[str] = None
        self._token_expires: float = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_access_token(self) -> str:
        """Get access token (cached)."""
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        # Get access token from WeCom API
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        params = {
            "corpid": self.bot_id,  # Note: bot_id is actually corpid for Smart Robot
            "corpsecret": self.secret,
        }

        session = await self._get_session()
        async with session.get(url, params=params) as response:
            data = await response.json()
            if data.get("errcode") == 0:
                self._access_token = data["access_token"]
                self._token_expires = time.time() + 7200  # 2 hours
                return self._access_token
            else:
                raise Exception(f"Failed to get access token: {data}")

    async def download_file(self, url: str, aes_key: str) -> tuple[bytes, Optional[str]]:
        """
        Download and decrypt file.

        Args:
            url: File URL
            aes_key: AES key for decryption (Base64 encoded)

        Returns:
            Tuple of (decrypted buffer, filename)
        """
        session = await self._get_session()

        async with session.get(url) as response:
            response.raise_for_status()
            encrypted_data = await response.read()

            # Extract filename from Content-Disposition header
            content_disposition = response.headers.get("Content-Disposition", "")
            filename = None
            if content_disposition:
                import re
                match = re.search(r'filename[^;=\n]*=((["\']).*?\2|[^;\n]*)', content_disposition)
                if match:
                    filename = match.group(1).strip('"\'')

        # Decrypt file
        decrypted_data = AESCipher.decrypt(encrypted_data, aes_key)

        return decrypted_data, filename

    async def upload_media(self, file_path: str, media_type: str = "image") -> str:
        """
        Upload media file to WeCom.

        Args:
            file_path: Local file path
            media_type: Media type (image, voice, file)

        Returns:
            media_id for sending messages
        """
        access_token = await self._get_access_token()

        url = "https://qyapi.weixin.qq.com/cgi-bin/media/upload"
        params = {
            "access_token": access_token,
            "type": media_type,
        }

        session = await self._get_session()
        with open(file_path, "rb") as f:
            files = {"media": (os.path.basename(file_path), f)}
            async with session.post(url, params=params, data=files) as response:
                data = await response.json()
                if data.get("errcode") == 0:
                    media_id = data["media_id"]
                    return media_id
                else:
                    raise Exception(f"Failed to upload media: {data}")


class WeComWebSocketClient:
    """WeCom WebSocket client following official SDK pattern."""

    DEFAULT_WS_URL = "wss://openws.work.weixin.qq.com"

    def __init__(
        self,
        bot_id: str,
        secret: str,
        ws_url: Optional[str] = None,
        heartbeat_interval: int = 30,
        max_reconnect_attempts: int = 5,
    ):
        self.bot_id = bot_id
        self.secret = secret
        self.ws_url = ws_url or self.DEFAULT_WS_URL
        self.heartbeat_interval = heartbeat_interval
        self.max_reconnect_attempts = max_reconnect_attempts

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._authenticated = False
        self._running = False
        self._pending_acks = 0
        self._pending_reply_req_ids: set[str] = set()  # Track pending reply ACKs (official SDK pattern)
        self._reconnect_attempts = 0
        self._processed_msg_ids: OrderedDict[str, None] = OrderedDict()

        # HTTP API client for file operations
        self._api_client = WeComApiClient(bot_id, secret)

        # Callbacks
        self.on_authenticated: Optional[Callable] = None
        self.on_message: Optional[Callable] = None
        self.on_event: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None

    async def connect(self) -> None:
        """Establish WebSocket connection with auto-reconnect."""
        self._running = True

        while self._running:
            try:
                logger.info("Connecting to WeCom WebSocket: {}", self.ws_url)
                self._ws = await websockets.connect(
                    self.ws_url,
                    ping_interval=None,
                    ping_timeout=None,
                )
                self._connected = True
                self._reconnect_attempts = 0
                logger.info("WeCom WebSocket connected")

                # Start background tasks
                receive_task = asyncio.create_task(self._receive_loop())
                heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                # Small delay to ensure receive loop is running
                await asyncio.sleep(0.1)

                # Send authentication
                await self._authenticate()

                # Wait for authentication
                timeout = 10.0
                start_time = time.time()
                while not self._authenticated and self._running:
                    await asyncio.sleep(0.1)
                    if time.time() - start_time > timeout:
                        logger.error("Authentication timeout")
                        if self.on_error:
                            await self.on_error("Auth timeout")
                        break

                if not self._authenticated:
                    await self._ws.close()
                    self._connected = False
                    continue

                logger.info("WeCom WebSocket connected and authenticated")

                # Wait for background tasks
                await asyncio.gather(receive_task, heartbeat_task, return_exceptions=True)

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning("WebSocket connection closed: {}", e)
                self._connected = False
                await self._handle_reconnect()

            except Exception as e:
                logger.error("Connection error: {}", e)
                self._connected = False
                if self.on_error:
                    await self.on_error(f"Connection error: {e}")
                await self._handle_reconnect()

    async def disconnect(self) -> None:
        """Disconnect WebSocket."""
        self._running = False
        self._connected = False
        self._authenticated = False

        if self._ws:
            await self._ws.close()
            self._ws = None

        await self._api_client.close()

        logger.info("WeCom WebSocket disconnected")

        if self.on_disconnected:
            await self.on_disconnected()

    async def _handle_reconnect(self) -> None:
        """Handle reconnection with backoff."""
        if not self._running:
            return

        self._reconnect_attempts += 1
        if self._reconnect_attempts >= self.max_reconnect_attempts:
            logger.error("Max reconnect attempts reached")
            if self.on_error:
                await self.on_error("Max reconnect attempts reached")
            return

        # Exponential backoff: 1s, 2s, 4s, 8s, 16s
        backoff = min(2 ** self._reconnect_attempts, 30)
        logger.info("Reconnecting in {}s (attempt {}/{})", backoff, self._reconnect_attempts, self.max_reconnect_attempts)
        await asyncio.sleep(backoff)

    async def _authenticate(self) -> None:
        """Send authentication frame."""
        try:
            timestamp = int(time.time() * 1000)
            req_id = f"aibot_subscribe_{timestamp}"

            auth_frame = {
                "cmd": WsCmd.SUBSCRIBE,
                "headers": {"req_id": req_id},
                "body": {
                    "bot_id": self.bot_id,
                    "secret": self.secret,
                },
            }

            await self._send_raw(auth_frame)

        except Exception as e:
            logger.error("Authentication error: {}", e)
            if self.on_error:
                await self.on_error(f"Auth error: {e}")

    async def _send_raw(self, frame: dict[str, Any]) -> None:
        """Send raw WebSocket frame."""
        if self._ws and self._connected:
            await self._ws.send(json.dumps(frame))

    async def _heartbeat_loop(self) -> None:
        """Heartbeat loop following official SDK pattern."""
        while self._running and self._connected:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                if not self._connected or not self._ws:
                    break

                # Check for missing ACKs
                if self._pending_acks > 3:
                    logger.warning("Too many missing ACKs, reconnecting...")
                    await self._ws.close()
                    self._connected = False
                    break

                # Send heartbeat
                timestamp = int(time.time() * 1000)
                heartbeat_frame = {
                    "cmd": WsCmd.HEARTBEAT,
                    "headers": {"req_id": f"hb_{timestamp}"},
                }

                await self._send_raw(heartbeat_frame)
                self._pending_acks += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: {}", e)

    async def _receive_loop(self) -> None:
        """Receive loop for incoming messages."""
        while self._running and self._connected:
            try:
                if not self._ws:
                    break

                # Wait for message with timeout
                try:
                    message = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue

                # Parse message
                data = json.loads(message)

                # Handle ACK
                if data.get("cmd") == "ack":
                    self._pending_acks = max(0, self._pending_acks - 1)
                    continue

                # Handle auth response
                req_id = data.get("headers", {}).get("req_id", "")
                if req_id.startswith("aibot_subscribe"):
                    if data.get("errcode") == 0:
                        self._authenticated = True
                        logger.info("Authentication successful")
                        if self.on_authenticated:
                            await self.on_authenticated()
                    else:
                        errmsg = data.get("errmsg", "Unknown error")
                        logger.error("Authentication failed: {}", errmsg)
                        if self.on_error:
                            await self.on_error(f"Auth failed: {errmsg}")
                    continue

                # Handle heartbeat response
                if req_id.startswith("hb_"):
                    if data.get("errcode") == 0:
                        self._pending_acks = max(0, self._pending_acks - 1)
                    continue

                # Handle message callback
                cmd = data.get("cmd", "")
                if cmd == WsCmd.CALLBACK:
                    body = data.get("body", {})
                    headers = data.get("headers", {})
                    await self._handle_message_callback(body, headers)
                    continue

                # Handle event callback
                if cmd == WsCmd.EVENT_CALLBACK:
                    body = data.get("body", {})
                    headers = data.get("headers", {})
                    await self._handle_event_callback(body, headers)
                    continue

                # Handle reply ACK (no cmd field, errcode present)
                # Official SDK pattern: check pendingAcks first
                req_id = data.get("headers", {}).get("req_id", "")
                if req_id and "errcode" in data:
                    # This is a reply ACK, auth response, or heartbeat response
                    if req_id in self._pending_reply_req_ids:
                        # Reply message ACK
                        self._pending_reply_req_ids.remove(req_id)
                        if data.get("errcode") != 0:
                            logger.warning("Reply ACK error: {} - {}", data.get("errcode"), data.get("errmsg"))
                        continue
                    elif req_id.startswith("aibot_subscribe"):
                        # Auth response (already handled above, but keep for safety)
                        continue
                    elif req_id.startswith("hb_"):
                        # Heartbeat response (already handled above, but keep for safety)
                        continue

                # Unknown message - log at debug level to avoid noise
                pass

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning("WebSocket connection closed: {}", e)
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Receive error: {}", e)
                if self.on_error:
                    await self.on_error(f"Receive error: {e}")

    async def _handle_message_callback(self, message: dict[str, Any], frame_headers: dict[str, Any]) -> None:
        """Handle message callback."""
        try:
            # Deduplication
            msg_id = message.get("msgid", "")
            if msg_id in self._processed_msg_ids:
                return
            self._processed_msg_ids[msg_id] = None

            # Trim cache
            while len(self._processed_msg_ids) > 1000:
                self._processed_msg_ids.popitem(last=False)

            # Parse message - from_userid can be in 'from' object or at top level
            from_info = message.get("from", {})
            from_user = from_info.get("userid", "") if isinstance(from_info, dict) else message.get("from_userid", "")
            
            if not from_user:
                logger.warning("No from_userid in message: {}", message)
                return

            chat_id = message.get("chatid", "")
            msg_type = message.get("msgtype", "")

            # Parse content
            content = await self._parse_message_content(message)

            if self.on_message:
                # Generate stream_id for reply (official SDK pattern)
                stream_id = self._generate_stream_id(msg_id)
                
                await self.on_message({
                    "msgid": msg_id,
                    "from_userid": from_user,
                    "chatid": chat_id,
                    "msgtype": msg_type,
                    "content": content.text,
                    "media": content.media_paths,
                    "metadata": {
                        **content.metadata,
                        "frame_headers": frame_headers,  # Save frame headers for reply (contains req_id)
                        "stream_id": stream_id,  # For stream reply
                    },
                })

        except Exception as e:
            logger.error("Error handling message callback: {}", e)

    def _generate_stream_id(self, msg_id: str) -> str:
        """Generate stream_id for reply (official SDK pattern)."""
        # Official SDK uses: `stream_${timestamp}_${random}`
        import random
        timestamp = int(time.time() * 1000)
        random_suffix = random.randint(1000, 9999)
        return f"stream_{timestamp}_{random_suffix}"

    async def _handle_event_callback(self, event: dict[str, Any]) -> None:
        """Handle event callback."""
        try:
            event_type = event.get("event", {}).get("event_type", "")
            if self.on_event:
                await self.on_event(event)
        except Exception as e:
            logger.error("Error handling event callback: {}", e)

    async def _parse_message_content(self, message: dict[str, Any]) -> MessageContent:
        """Parse message content based on message type."""
        content = MessageContent()
        msg_type = message.get("msgtype", "")

        if msg_type == MsgType.TEXT:
            # Official SDK format: text.content
            text_content = message.get("text", {})
            if isinstance(text_content, dict):
                content.text = text_content.get("content", "")
            else:
                content.text = message.get("content", "")

        elif msg_type == MsgType.IMAGE:
            content.text = "[image]"
            image_data = message.get("image", {})
            if image_data:
                url = image_data.get("url", "")
                aes_key = image_data.get("aeskey", "")
                if url and aes_key:
                    try:
                        file_path = await self._download_and_save_media("image", url, aes_key)
                        if file_path:
                            content.media_paths.append(file_path)
                    except Exception as e:
                        logger.error("Failed to download image: {}", e)
                        content.text = "[image: download failed]"

        elif msg_type == MsgType.VOICE:
            # Voice is already transcribed to text
            voice_data = message.get("voice", {})
            if isinstance(voice_data, dict):
                content.text = voice_data.get("content", "")
            else:
                content.text = message.get("content", "")
            content.metadata["voice"] = True

        elif msg_type == MsgType.FILE:
            content.text = "[file]"
            file_data = message.get("file", {})
            if file_data:
                file_name = file_data.get("name", "unknown")
                content.text = f"[file: {file_name}]"
                url = file_data.get("url", "")
                aes_key = file_data.get("aeskey", "")
                if url and aes_key:
                    try:
                        file_path = await self._download_and_save_media("file", url, aes_key, file_name)
                        if file_path:
                            content.media_paths.append(file_path)
                    except Exception as e:
                        logger.error("Failed to download file: {}", e)
                        content.text = f"[file: {file_name} - download failed]"

        elif msg_type == MsgType.MIXED:
            mixed_data = message.get("mixed", {})
            items = mixed_data.get("item", [])
            texts = []
            for item in items:
                item_type = item.get("type", "")
                if item_type == "text":
                    text = item.get("text", {}).get("content", "")
                    if text:
                        texts.append(text)
                elif item_type == "image":
                    url = item.get("image", {}).get("url", "")
                    aes_key = item.get("image", {}).get("aeskey", "")
                    if url and aes_key:
                        try:
                            file_path = await self._download_and_save_media("image", url, aes_key)
                            if file_path:
                                content.media_paths.append(file_path)
                        except Exception as e:
                            logger.error("Failed to download mixed image: {}", e)
            content.text = "\n".join(texts) if texts else "[mixed message]"

        else:
            content.text = f"[{msg_type}]"

        content.metadata["msg_type"] = msg_type
        return content

    async def _download_and_save_media(
        self,
        media_type: str,
        url: str,
        aes_key: str,
        filename: Optional[str] = None,
    ) -> Optional[str]:
        """Download and save media file."""
        try:
            media_dir = get_media_dir("wecom")
            media_dir.mkdir(parents=True, exist_ok=True)

            # Download and decrypt
            data, downloaded_filename = await self._api_client.download_file(url, aes_key)
            if not filename:
                filename = downloaded_filename or f"{int(time.time())}.{media_type}"

            # Save file
            file_path = media_dir / filename
            file_path.write_bytes(data)

            return str(file_path)

        except Exception as e:
            logger.error("Failed to download {}: {}", media_type, e)
            return None

    async def send_message(self, chatid: str, content: str, msg_type: str = "text") -> None:
        """Send message through WeCom."""
        if not self._connected or not self._authenticated:
            logger.warning("Cannot send message: not connected or authenticated")
            return

        timestamp = int(time.time() * 1000)

        # Build message body based on type
        if msg_type == "markdown":
            msg_body = {
                "msgtype": "markdown",
                "markdown": {"content": content},
            }
        elif msg_type == "image":
            msg_body = {
                "msgtype": "image",
                "image": {"media_id": content},  # content is media_id
            }
        elif msg_type == "file":
            msg_body = {
                "msgtype": "file",
                "file": {"media_id": content},  # content is media_id
            }
        else:  # text
            msg_body = {
                "msgtype": "text",
                "text": {"content": content},
            }

        send_frame = {
            "cmd": WsCmd.SEND_MESSAGE,
            "headers": {"req_id": f"send_{timestamp}"},
            "body": {
                "chatid": chatid,
                **msg_body,
            },
        }

        await self._send_raw(send_frame)

    async def send_media(self, chatid: str, file_path: str, media_type: str = "image") -> None:
        """Upload and send media file."""
        try:
            media_id = await self._api_client.upload_media(file_path, media_type)
            await self.send_message(chatid, media_id, media_type)
        except Exception as e:
            logger.error("Failed to send media: {}", e)

    async def reply(self, frame_headers: dict, body: dict) -> None:
        """
        Reply to a message using aibot_respond_msg command (official SDK pattern).
        
        Following @wecom/aibot-node-sdk:
        - 透传 frame_headers (contains req_id)
        - Use cmd: "aibot_respond_msg"
        - Body contains msgtype and message content
        
        Args:
            frame_headers: Headers from received message frame (contains req_id)
            body: Message body (e.g., {"msgtype": "text", "text": {"content": "hello"}})
        """
        if not self._connected or not self._authenticated:
            logger.warning("Cannot reply: not connected or authenticated")
            return

        # Extract req_id from frame headers
        req_id = frame_headers.get("req_id", "")
        if not req_id:
            logger.error("No req_id in frame headers, cannot reply")
            return

        # Build reply frame following official SDK format
        # { cmd: "aibot_respond_msg", headers: { req_id }, body: { msgtype, ... } }
        reply_frame = {
            "cmd": WsCmd.RESPOND_MSG,
            "headers": {"req_id": req_id},
            "body": body,
        }

        # Track this req_id for ACK handling (official SDK pattern)
        self._pending_reply_req_ids.add(req_id)

        await self._send_raw(reply_frame)

    async def reply_stream(
        self,
        frame_headers: dict,
        stream_id: str,
        content: str,
        finish: bool = False,
    ) -> None:
        """Send streaming reply (typewriter effect)."""
        if not self._connected or not self._authenticated:
            return

        stream_frame = {
            "cmd": WsCmd.RESPOND_MSG,
            "headers": frame_headers,
            "body": {
                "msgtype": "stream",
                "stream": {
                    "id": stream_id,
                    "content": content,
                    "finish": finish,
                },
            },
        }

        await self._send_raw(stream_frame)

    async def reply_template_card(self, frame_headers: dict, template_card: dict) -> None:
        """Reply with template card."""
        if not self._connected or not self._authenticated:
            return

        card_frame = {
            "cmd": WsCmd.REPLY_TEMPLATE_CARD,
            "headers": frame_headers,
            "body": {
                "msgtype": "template_card",
                "template_card": template_card,
            },
        }

        await self._send_raw(card_frame)

    async def reply_welcome(self, frame_headers: dict, content: str) -> None:
        """Send welcome message (must be within 5s of enter_chat event)."""
        if not self._connected or not self._authenticated:
            return

        welcome_frame = {
            "cmd": WsCmd.REPLY_WELCOME,
            "headers": frame_headers,
            "body": {
                "msgtype": "text",
                "text": {"content": content},
            },
        }

        await self._send_raw(welcome_frame)


class WeComChannel(BaseChannel):
    """WeCom Smart Robot channel implementation."""

    name = "wecom"

    def __init__(self, config: WeComConfig, message_bus: MessageBus):
        super().__init__(config, message_bus)
        self.bot_id = config.bot_id
        self.secret = config.secret
        self.ws_url = getattr(config, "ws_url", None)
        self._client: Optional[WeComWebSocketClient] = None

    async def start(self) -> None:
        """Start the WeCom channel."""
        logger.info("WeCom Smart Robot channel starting...")
        logger.info("Bot ID: {}", self.bot_id[:8] + "..." if len(self.bot_id) > 8 else self.bot_id)

        self._client = WeComWebSocketClient(
            bot_id=self.bot_id,
            secret=self.secret,
            ws_url=self.ws_url,
            heartbeat_interval=30,
            max_reconnect_attempts=5,
        )

        self._client.on_authenticated = self._on_authenticated
        self._client.on_message = self._on_message
        self._client.on_event = self._on_event
        self._client.on_error = self._on_error
        self._client.on_disconnected = self._on_disconnected

        # Start connection in background
        asyncio.create_task(self._client.connect())

    async def stop(self) -> None:
        """Stop the WeCom channel."""
        logger.info("WeCom channel stopping...")
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def _on_authenticated(self) -> None:
        """Called when authentication succeeds."""
        logger.info("WeCom channel authenticated and ready")

    async def _on_message(self, message: dict[str, Any]) -> None:
        """Handle incoming message."""
        try:
            # Message is already flattened by _handle_message_callback
            # from_userid is at top level
            from_user = message.get("from_userid", "")
            chat_id = message.get("chatid", "")
            
            if not from_user:
                logger.warning("No from_userid in message: {}", message)
                return

            if not self.is_allowed(from_user):
                logger.warning("Access denied for user: {}", from_user)
                return

            # Build media list
            media = message.get("media", [])

            # For single chat, chatid is empty, use from_userid as chat_id for reply
            if not chat_id:
                chat_id = from_user

            # Get frame_headers and stream_id from metadata (official SDK pattern)
            metadata = message.get("metadata", {})
            frame_headers = metadata.get("frame_headers", {})
            stream_id = metadata.get("stream_id", "")

            await self._handle_message(
                sender_id=from_user,
                chat_id=chat_id,
                content=message.get("content", ""),
                media=media,
                metadata={
                    **metadata,
                    "frame_headers": frame_headers,
                    "stream_id": stream_id,
                },
            )
        except Exception as e:
            logger.error("Error handling inbound message: {}", e)

    async def _on_event(self, event: dict[str, Any]) -> None:
        """Handle event callback."""
        try:
            event_type = event.get("event", {}).get("event_type", "")

            if event_type == "enter_chat":
                # User entered chat - can send welcome message within 5s
                logger.info("User entered chat: {}", event.get("from_userid", ""))

            elif event_type == "card_click":
                # User clicked card button
                logger.info("Card clicked by user")

        except Exception as e:
            logger.error("Error handling event: {}", e)

    async def _on_error(self, error: str) -> None:
        """Handle errors."""
        logger.error("WeCom error: {}", error)

    async def _on_disconnected(self) -> None:
        """Handle disconnection."""
        logger.warning("WeCom channel disconnected")

    async def send(self, message: OutboundMessage) -> None:
        """Send outbound message."""
        if not self._client:
            logger.warning("WeCom client not initialized")
            return

        try:
            # Check if we have frame_headers and stream_id (for reply to incoming message via WebSocket)
            frame_headers = message.metadata.get("frame_headers", {})
            stream_id = message.metadata.get("stream_id", "")
            
            if frame_headers and stream_id:
                # Use WebSocket replyStream (official SDK pattern for text replies)
                await self._send_via_reply_stream(frame_headers, stream_id, message)
            else:
                # Use WebSocket send_message (for proactive messages)
                target_chat_id = message.chat_id
                if not target_chat_id:
                    logger.warning("No chat_id in outbound message, cannot send")
                    return

                # Send media files first
                for file_path in message.media:
                    if os.path.isfile(file_path):
                        ext = os.path.splitext(file_path)[1].lower()
                        if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
                            await self._client.send_media(target_chat_id, file_path, "image")
                        else:
                            await self._client.send_media(target_chat_id, file_path, "file")

                # Send text/markdown content
                if message.content and message.content.strip():
                    msg_type = "markdown" if message.metadata.get("markdown") else "text"
                    await self._client.send_message(
                        chatid=target_chat_id,
                        content=message.content,
                        msg_type=msg_type,
                    )

                logger.info("Outbound message sent to {}: {}", target_chat_id, message.content[:50] if message.content else "")

        except Exception as e:
            logger.error("Error sending message: {}", e)

    async def _send_via_reply_stream(self, frame_headers: dict, stream_id: str, message: OutboundMessage) -> None:
        """Send message via WebSocket replyStream (official SDK pattern for text replies)."""
        try:
            # Official SDK format: { cmd: "aibot_respond_msg", headers: { req_id }, body: { msgtype: "stream", stream: {...} } }
            # For single-shot reply, use finish=true
            req_id = frame_headers.get("req_id", "")
            if not req_id:
                logger.error("No req_id in frame headers, cannot reply")
                return

            # Build stream reply body (official SDK pattern)
            stream_body = {
                "msgtype": "stream",
                "stream": {
                    "id": stream_id,
                    "finish": True,  # Single-shot reply
                    "content": message.content,
                },
            }

            # Send via WebSocket using aibot_respond_msg command
            await self._client.reply(frame_headers, stream_body)
            logger.info("Reply sent via WebSocket replyStream: {}", message.content[:50] if message.content else "")

        except Exception as e:
            logger.error("Error sending via WebSocket replyStream: {}", e)

