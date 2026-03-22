"""Personal WeChat (微信) channel using HTTP long-poll API.

Uses the ilinkai.weixin.qq.com API for personal WeChat messaging.
No WebSocket, no local WeChat client needed — just HTTP requests with a
bot token obtained via QR code login.

Protocol reverse-engineered from ``@tencent-weixin/openclaw-weixin`` v1.0.2.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir, get_runtime_subdir
from nanobot.config.schema import Base
from nanobot.utils.helpers import split_message

# ---------------------------------------------------------------------------
# Protocol constants (from openclaw-weixin types.ts)
# ---------------------------------------------------------------------------

# MessageItemType
ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5

# MessageType  (1 = inbound from user, 2 = outbound from bot)
MESSAGE_TYPE_USER = 1
MESSAGE_TYPE_BOT = 2

# MessageState
MESSAGE_STATE_FINISH = 2

WEIXIN_MAX_MESSAGE_LEN = 4000
BASE_INFO: dict[str, str] = {"channel_version": "1.0.2"}

# Session-expired error code
ERRCODE_SESSION_EXPIRED = -14

# Retry constants (matching the reference plugin's monitor.ts)
MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAY_S = 30
RETRY_DELAY_S = 2

# Default long-poll timeout; overridden by server via longpolling_timeout_ms.
DEFAULT_LONG_POLL_TIMEOUT_S = 35


class WeixinConfig(Base):
    """Personal WeChat channel configuration."""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)
    base_url: str = "https://ilinkai.weixin.qq.com"
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    token: str = ""  # Manually set token, or obtained via QR login
    state_dir: str = ""  # Default: ~/.nanobot/weixin/
    poll_timeout: int = DEFAULT_LONG_POLL_TIMEOUT_S  # seconds for long-poll


class WeixinChannel(BaseChannel):
    """
    Personal WeChat channel using HTTP long-poll.

    Connects to ilinkai.weixin.qq.com API to receive and send personal
    WeChat messages. Authentication is via QR code login which produces
    a bot token.
    """

    name = "weixin"
    display_name = "WeChat"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WeixinConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WeixinConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WeixinConfig = config

        # State
        self._client: httpx.AsyncClient | None = None
        self._get_updates_buf: str = ""
        self._context_tokens: dict[str, str] = {}  # from_user_id -> context_token
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._state_dir: Path | None = None
        self._token: str = ""
        self._poll_task: asyncio.Task | None = None
        self._next_poll_timeout_s: int = DEFAULT_LONG_POLL_TIMEOUT_S

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _get_state_dir(self) -> Path:
        if self._state_dir:
            return self._state_dir
        if self.config.state_dir:
            d = Path(self.config.state_dir).expanduser()
        else:
            d = get_runtime_subdir("weixin")
        d.mkdir(parents=True, exist_ok=True)
        self._state_dir = d
        return d

    def _load_state(self) -> bool:
        """Load saved account state. Returns True if a valid token was found."""
        state_file = self._get_state_dir() / "account.json"
        if not state_file.exists():
            return False
        try:
            data = json.loads(state_file.read_text())
            self._token = data.get("token", "")
            self._get_updates_buf = data.get("get_updates_buf", "")
            base_url = data.get("base_url", "")
            if base_url:
                self.config.base_url = base_url
            return bool(self._token)
        except Exception as e:
            logger.warning("Failed to load WeChat state: {}", e)
            return False

    def _save_state(self) -> None:
        state_file = self._get_state_dir() / "account.json"
        try:
            data = {
                "token": self._token,
                "get_updates_buf": self._get_updates_buf,
                "base_url": self.config.base_url,
            }
            state_file.write_text(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.warning("Failed to save WeChat state: {}", e)

    # ------------------------------------------------------------------
    # HTTP helpers  (matches api.ts buildHeaders / apiFetch)
    # ------------------------------------------------------------------

    @staticmethod
    def _random_wechat_uin() -> str:
        """X-WECHAT-UIN: random uint32 → decimal string → base64.

        Matches the reference plugin's ``randomWechatUin()`` in api.ts.
        Generated fresh for **every** request (same as reference).
        """
        uint32 = int.from_bytes(os.urandom(4), "big")
        return base64.b64encode(str(uint32).encode()).decode()

    def _make_headers(self, *, auth: bool = True) -> dict[str, str]:
        """Build per-request headers (new UIN each call, matching reference)."""
        headers: dict[str, str] = {
            "X-WECHAT-UIN": self._random_wechat_uin(),
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
        }
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _api_get(
        self,
        endpoint: str,
        params: dict | None = None,
        *,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        assert self._client is not None
        url = f"{self.config.base_url}/{endpoint}"
        hdrs = self._make_headers(auth=auth)
        if extra_headers:
            hdrs.update(extra_headers)
        resp = await self._client.get(url, params=params, headers=hdrs)
        resp.raise_for_status()
        return resp.json()

    async def _api_post(
        self,
        endpoint: str,
        body: dict | None = None,
        *,
        auth: bool = True,
    ) -> dict:
        assert self._client is not None
        url = f"{self.config.base_url}/{endpoint}"
        payload = body or {}
        if "base_info" not in payload:
            payload["base_info"] = BASE_INFO
        resp = await self._client.post(url, json=payload, headers=self._make_headers(auth=auth))
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # QR Code Login  (matches login-qr.ts)
    # ------------------------------------------------------------------

    async def _qr_login(self) -> bool:
        """Perform QR code login flow. Returns True on success."""
        try:
            logger.info("Starting WeChat QR code login...")

            data = await self._api_get(
                "ilink/bot/get_bot_qrcode",
                params={"bot_type": "3"},
                auth=False,
            )
            qrcode_img_content = data.get("qrcode_img_content", "")
            qrcode_id = data.get("qrcode", "")

            if not qrcode_id:
                logger.error("Failed to get QR code from WeChat API: {}", data)
                return False

            scan_url = qrcode_img_content or qrcode_id
            self._print_qr_code(scan_url)

            logger.info("Waiting for QR code scan...")
            while self._running:
                try:
                    # Reference plugin sends iLink-App-ClientVersion header for
                    # QR status polling (login-qr.ts:81).
                    status_data = await self._api_get(
                        "ilink/bot/get_qrcode_status",
                        params={"qrcode": qrcode_id},
                        auth=False,
                        extra_headers={"iLink-App-ClientVersion": "1"},
                    )
                except httpx.TimeoutException:
                    continue

                status = status_data.get("status", "")
                if status == "confirmed":
                    token = status_data.get("bot_token", "")
                    bot_id = status_data.get("ilink_bot_id", "")
                    base_url = status_data.get("baseurl", "")
                    user_id = status_data.get("ilink_user_id", "")
                    if token:
                        self._token = token
                        if base_url:
                            self.config.base_url = base_url
                        self._save_state()
                        logger.info(
                            "WeChat login successful! bot_id={} user_id={}",
                            bot_id,
                            user_id,
                        )
                        return True
                    else:
                        logger.error("Login confirmed but no bot_token in response")
                        return False
                elif status == "scaned":
                    logger.info("QR code scanned, waiting for confirmation...")
                elif status == "expired":
                    logger.warning("QR code expired")
                    return False
                # status == "wait" — keep polling

                await asyncio.sleep(1)

        except Exception as e:
            logger.error("WeChat QR login failed: {}", e)

        return False

    @staticmethod
    def _print_qr_code(url: str) -> None:
        try:
            import qrcode as qr_lib

            qr = qr_lib.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            logger.info("QR code URL (install 'qrcode' for terminal display): {}", url)
            print(f"\nLogin URL: {url}\n")

    # ------------------------------------------------------------------
    # Channel lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._next_poll_timeout_s = self.config.poll_timeout
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._next_poll_timeout_s + 10, connect=30),
            follow_redirects=True,
        )

        if self.config.token:
            self._token = self.config.token
        elif not self._load_state():
            if not await self._qr_login():
                logger.error("WeChat login failed. Run 'nanobot weixin login' to authenticate.")
                self._running = False
                return

        logger.info("WeChat channel starting with long-poll...")

        consecutive_failures = 0
        while self._running:
            try:
                await self._poll_once()
                consecutive_failures = 0
            except httpx.TimeoutException:
                # Normal for long-poll, just retry
                continue
            except Exception as e:
                if not self._running:
                    break
                consecutive_failures += 1
                logger.error(
                    "WeChat poll error ({}/{}): {}",
                    consecutive_failures,
                    MAX_CONSECUTIVE_FAILURES,
                    e,
                )
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    consecutive_failures = 0
                    await asyncio.sleep(BACKOFF_DELAY_S)
                else:
                    await asyncio.sleep(RETRY_DELAY_S)

    async def stop(self) -> None:
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        if self._client:
            await self._client.aclose()
            self._client = None
        self._save_state()
        logger.info("WeChat channel stopped")

    # ------------------------------------------------------------------
    # Polling  (matches monitor.ts monitorWeixinProvider)
    # ------------------------------------------------------------------

    async def _poll_once(self) -> None:
        body: dict[str, Any] = {
            "get_updates_buf": self._get_updates_buf,
            "base_info": BASE_INFO,
        }

        # Adjust httpx timeout to match the current poll timeout
        assert self._client is not None
        self._client.timeout = httpx.Timeout(self._next_poll_timeout_s + 10, connect=30)

        data = await self._api_post("ilink/bot/getupdates", body)

        # Check for API-level errors (monitor.ts checks both ret and errcode)
        ret = data.get("ret", 0)
        errcode = data.get("errcode", 0)
        is_error = (ret is not None and ret != 0) or (errcode is not None and errcode != 0)

        if is_error:
            if errcode == ERRCODE_SESSION_EXPIRED or ret == ERRCODE_SESSION_EXPIRED:
                logger.warning(
                    "WeChat session expired (errcode {}). Pausing 60 min.",
                    errcode,
                )
                await asyncio.sleep(3600)
                return
            raise RuntimeError(
                f"getUpdates failed: ret={ret} errcode={errcode} errmsg={data.get('errmsg', '')}"
            )

        # Honour server-suggested poll timeout (monitor.ts:102-105)
        server_timeout_ms = data.get("longpolling_timeout_ms")
        if server_timeout_ms and server_timeout_ms > 0:
            self._next_poll_timeout_s = max(server_timeout_ms // 1000, 5)

        # Update cursor
        new_buf = data.get("get_updates_buf", "")
        if new_buf:
            self._get_updates_buf = new_buf
            self._save_state()

        # Process messages (WeixinMessage[] from types.ts)
        msgs: list[dict] = data.get("msgs", []) or []
        for msg in msgs:
            try:
                await self._process_message(msg)
            except Exception as e:
                logger.error("Error processing WeChat message: {}", e)

    # ------------------------------------------------------------------
    # Inbound message processing  (matches inbound.ts + process-message.ts)
    # ------------------------------------------------------------------

    async def _process_message(self, msg: dict) -> None:
        """Process a single WeixinMessage from getUpdates."""
        # Skip bot's own messages (message_type 2 = BOT)
        if msg.get("message_type") == MESSAGE_TYPE_BOT:
            return

        # Deduplication by message_id
        msg_id = str(msg.get("message_id", "") or msg.get("seq", ""))
        if not msg_id:
            msg_id = f"{msg.get('from_user_id', '')}_{msg.get('create_time_ms', '')}"
        if msg_id in self._processed_ids:
            return
        self._processed_ids[msg_id] = None
        while len(self._processed_ids) > 1000:
            self._processed_ids.popitem(last=False)

        from_user_id = msg.get("from_user_id", "") or ""
        if not from_user_id:
            return

        # Cache context_token (required for all replies — inbound.ts:23-27)
        ctx_token = msg.get("context_token", "")
        if ctx_token:
            self._context_tokens[from_user_id] = ctx_token

        # Parse item_list (WeixinMessage.item_list — types.ts:161)
        item_list: list[dict] = msg.get("item_list") or []
        content_parts: list[str] = []
        media_paths: list[str] = []

        for item in item_list:
            item_type = item.get("type", 0)

            if item_type == ITEM_TEXT:
                text = (item.get("text_item") or {}).get("text", "")
                if text:
                    # Handle quoted/ref messages (inbound.ts:86-98)
                    ref = item.get("ref_msg")
                    if ref:
                        ref_item = ref.get("message_item")
                        # If quoted message is media, just pass the text
                        if ref_item and ref_item.get("type", 0) in (
                            ITEM_IMAGE,
                            ITEM_VOICE,
                            ITEM_FILE,
                            ITEM_VIDEO,
                        ):
                            content_parts.append(text)
                        else:
                            parts: list[str] = []
                            if ref.get("title"):
                                parts.append(ref["title"])
                            if ref_item:
                                ref_text = (ref_item.get("text_item") or {}).get("text", "")
                                if ref_text:
                                    parts.append(ref_text)
                            if parts:
                                content_parts.append(f"[引用: {' | '.join(parts)}]\n{text}")
                            else:
                                content_parts.append(text)
                    else:
                        content_parts.append(text)

            elif item_type == ITEM_IMAGE:
                image_item = item.get("image_item") or {}
                file_path = await self._download_media_item(image_item, "image")
                if file_path:
                    content_parts.append(f"[image]\n[Image: source: {file_path}]")
                    media_paths.append(file_path)
                else:
                    content_parts.append("[image]")

            elif item_type == ITEM_VOICE:
                voice_item = item.get("voice_item") or {}
                # Voice-to-text provided by WeChat (inbound.ts:101-103)
                voice_text = voice_item.get("text", "")
                if voice_text:
                    content_parts.append(f"[voice] {voice_text}")
                else:
                    file_path = await self._download_media_item(voice_item, "voice")
                    if file_path:
                        transcription = await self.transcribe_audio(file_path)
                        if transcription:
                            content_parts.append(f"[voice] {transcription}")
                        else:
                            content_parts.append(f"[voice]\n[Audio: source: {file_path}]")
                        media_paths.append(file_path)
                    else:
                        content_parts.append("[voice]")

            elif item_type == ITEM_FILE:
                file_item = item.get("file_item") or {}
                file_name = file_item.get("file_name", "unknown")
                file_path = await self._download_media_item(
                    file_item,
                    "file",
                    file_name,
                )
                if file_path:
                    content_parts.append(f"[file: {file_name}]\n[File: source: {file_path}]")
                    media_paths.append(file_path)
                else:
                    content_parts.append(f"[file: {file_name}]")

            elif item_type == ITEM_VIDEO:
                video_item = item.get("video_item") or {}
                file_path = await self._download_media_item(video_item, "video")
                if file_path:
                    content_parts.append(f"[video]\n[Video: source: {file_path}]")
                    media_paths.append(file_path)
                else:
                    content_parts.append("[video]")

        content = "\n".join(content_parts)
        if not content:
            return

        logger.info(
            "WeChat inbound: from={} items={} bodyLen={}",
            from_user_id,
            ",".join(str(i.get("type", 0)) for i in item_list),
            len(content),
        )

        await self._handle_message(
            sender_id=from_user_id,
            chat_id=from_user_id,
            content=content,
            media=media_paths or None,
            metadata={"message_id": msg_id},
        )

    # ------------------------------------------------------------------
    # Media download  (matches media-download.ts + pic-decrypt.ts)
    # ------------------------------------------------------------------

    async def _download_media_item(
        self,
        typed_item: dict,
        media_type: str,
        filename: str | None = None,
    ) -> str | None:
        """Download + AES-decrypt a media item. Returns local path or None."""
        try:
            media = typed_item.get("media") or {}
            encrypt_query_param = media.get("encrypt_query_param", "")

            if not encrypt_query_param:
                return None

            # Resolve AES key (media-download.ts:43-45, pic-decrypt.ts:40-52)
            # image_item.aeskey is a raw hex string (16 bytes as 32 hex chars).
            # media.aes_key is always base64-encoded.
            # For images, prefer image_item.aeskey; for others use media.aes_key.
            raw_aeskey_hex = typed_item.get("aeskey", "")
            media_aes_key_b64 = media.get("aes_key", "")

            aes_key_b64: str = ""
            if raw_aeskey_hex:
                # Convert hex → raw bytes → base64 (matches media-download.ts:43-44)
                aes_key_b64 = base64.b64encode(bytes.fromhex(raw_aeskey_hex)).decode()
            elif media_aes_key_b64:
                aes_key_b64 = media_aes_key_b64

            # Build CDN download URL with proper URL-encoding (cdn-url.ts:7)
            cdn_url = (
                f"{self.config.cdn_base_url}/download"
                f"?encrypted_query_param={quote(encrypt_query_param)}"
            )

            assert self._client is not None
            resp = await self._client.get(cdn_url)
            resp.raise_for_status()
            data = resp.content

            if aes_key_b64 and data:
                data = _decrypt_aes_ecb(data, aes_key_b64)
            elif not aes_key_b64:
                logger.debug("No AES key for {} item, using raw bytes", media_type)

            if not data:
                return None

            media_dir = get_media_dir("weixin")
            ext = _ext_for_type(media_type)
            if not filename:
                ts = int(time.time())
                h = abs(hash(encrypt_query_param)) % 100000
                filename = f"{media_type}_{ts}_{h}{ext}"
            safe_name = os.path.basename(filename)
            file_path = media_dir / safe_name
            file_path.write_bytes(data)
            logger.debug("Downloaded WeChat {} to {}", media_type, file_path)
            return str(file_path)

        except Exception as e:
            logger.error("Error downloading WeChat media: {}", e)
            return None

    # ------------------------------------------------------------------
    # Outbound  (matches send.ts buildTextMessageReq + sendMessageWeixin)
    # ------------------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        if not self._client or not self._token:
            logger.warning("WeChat client not initialized or not authenticated")
            return

        content = msg.content.strip()
        if not content:
            return

        ctx_token = self._context_tokens.get(msg.chat_id, "")
        if not ctx_token:
            # Reference plugin refuses to send without context_token (send.ts:88-91)
            logger.warning(
                "WeChat: no context_token for chat_id={}, cannot send",
                msg.chat_id,
            )
            return

        try:
            chunks = split_message(content, WEIXIN_MAX_MESSAGE_LEN)
            for chunk in chunks:
                await self._send_text(msg.chat_id, chunk, ctx_token)
        except Exception as e:
            logger.error("Error sending WeChat message: {}", e)

    async def _send_text(
        self,
        to_user_id: str,
        text: str,
        context_token: str,
    ) -> None:
        """Send a text message matching the exact protocol from send.ts."""
        client_id = f"nanobot-{uuid.uuid4().hex[:12]}"

        item_list: list[dict] = []
        if text:
            item_list.append({"type": ITEM_TEXT, "text_item": {"text": text}})

        weixin_msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": MESSAGE_TYPE_BOT,
            "message_state": MESSAGE_STATE_FINISH,
        }
        if item_list:
            weixin_msg["item_list"] = item_list
        if context_token:
            weixin_msg["context_token"] = context_token

        body: dict[str, Any] = {
            "msg": weixin_msg,
            "base_info": BASE_INFO,
        }

        data = await self._api_post("ilink/bot/sendmessage", body)
        errcode = data.get("errcode", 0)
        if errcode and errcode != 0:
            logger.warning(
                "WeChat send error (code {}): {}",
                errcode,
                data.get("errmsg", ""),
            )


# ---------------------------------------------------------------------------
# AES-128-ECB decryption  (matches pic-decrypt.ts parseAesKey + aes-ecb.ts)
# ---------------------------------------------------------------------------


def _parse_aes_key(aes_key_b64: str) -> bytes:
    """Parse a base64-encoded AES key, handling both encodings seen in the wild.

    From ``pic-decrypt.ts parseAesKey``:

    * ``base64(raw 16 bytes)``            → images (media.aes_key)
    * ``base64(hex string of 16 bytes)``  → file / voice / video

    In the second case base64-decoding yields 32 ASCII hex chars which must
    then be parsed as hex to recover the actual 16-byte key.
    """
    decoded = base64.b64decode(aes_key_b64)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32 and re.fullmatch(rb"[0-9a-fA-F]{32}", decoded):
        # hex-encoded key: base64 → hex string → raw bytes
        return bytes.fromhex(decoded.decode("ascii"))
    raise ValueError(
        f"aes_key must decode to 16 raw bytes or 32-char hex string, got {len(decoded)} bytes"
    )


def _decrypt_aes_ecb(data: bytes, aes_key_b64: str) -> bytes:
    """Decrypt AES-128-ECB media data.

    ``aes_key_b64`` is always base64-encoded (caller converts hex keys first).
    """
    try:
        key = _parse_aes_key(aes_key_b64)
    except Exception as e:
        logger.warning("Failed to parse AES key, returning raw data: {}", e)
        return data

    try:
        from Crypto.Cipher import AES

        cipher = AES.new(key, AES.MODE_ECB)
        return cipher.decrypt(data)  # pycryptodome auto-strips PKCS7 with unpad
    except ImportError:
        pass

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cipher_obj = Cipher(algorithms.AES(key), modes.ECB())
        decryptor = cipher_obj.decryptor()
        return decryptor.update(data) + decryptor.finalize()
    except ImportError:
        logger.warning("Cannot decrypt media: install 'pycryptodome' or 'cryptography'")
        return data


def _ext_for_type(media_type: str) -> str:
    return {
        "image": ".jpg",
        "voice": ".silk",
        "video": ".mp4",
        "file": "",
    }.get(media_type, "")
