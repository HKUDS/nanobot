"""Weixin (WeChat) personal account channel via iLink Bot API.

Uses HTTP long-polling to receive messages and HTTP POST to send messages.
Media files are transferred through CDN with AES-128-ECB encryption.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import random
import re
import struct
import time
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
from nanobot.config.paths import get_data_dir, get_media_dir
from nanobot.config.schema import Base

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------
CHANNEL_VERSION = "nanobot-1.0.0"

# proto UploadMediaType
_UPLOAD_MEDIA_IMAGE = 1
_UPLOAD_MEDIA_VIDEO = 2
_UPLOAD_MEDIA_FILE = 3

# proto MessageType / MessageState
_MSG_TYPE_BOT = 2
_MSG_STATE_FINISH = 2

# proto MessageItemType
ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5

_MEDIA_ITEM_TYPES = frozenset({ITEM_IMAGE, ITEM_VIDEO, ITEM_FILE, ITEM_VOICE})
_ITEM_KEY = {
    ITEM_IMAGE: "image_item",
    ITEM_VIDEO: "video_item",
    ITEM_FILE: "file_item",
    ITEM_VOICE: "voice_item",
}

# proto TypingStatus
_TYPING_START = 1
_TYPING_CANCEL = 2

# Retry / backoff
_CDN_UPLOAD_MAX_RETRIES = 3
_MAX_CONSECUTIVE_FAILURES = 3
_BACKOFF_DELAY_S = 30
_RETRY_DELAY_S = 2
_SESSION_PAUSE_S = 3600

# Config cache
_CONFIG_CACHE_TTL_S = 24 * 3600
_CONFIG_INITIAL_RETRY_S = 2
_CONFIG_MAX_RETRY_S = 3600

# Long-poll
_DEFAULT_POLL_TIMEOUT_MS = 35_000

# Image extensions / video extensions for upload type detection
_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})
_VIDEO_EXTS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class WeixinConfig(Base):
    """Weixin iLink Bot channel configuration."""

    enabled: bool = False
    base_url: str = "https://ilinkai.weixin.qq.com"
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    token: str = ""
    account_id: str = ""
    allow_from: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AES-128-ECB helpers (pycryptodome)
# ---------------------------------------------------------------------------

def _aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad

    return AES.new(key, AES.MODE_ECB).encrypt(pad(plaintext, AES.block_size))


def _aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad

    return unpad(AES.new(key, AES.MODE_ECB).decrypt(ciphertext), AES.block_size)


def _aes_ecb_padded_size(plaintext_size: int) -> int:
    """Ciphertext size after PKCS7 padding to 16-byte boundary."""
    return math.ceil((plaintext_size + 1) / 16) * 16


def _parse_aes_key(aes_key_b64: str) -> bytes:
    """Decode a base64-encoded AES key.

    Two wire formats exist:
      1. base64(raw 16 bytes)           — images
      2. base64(hex string, 32 chars)   — file / voice / video
    """
    raw = base64.b64decode(aes_key_b64)
    if len(raw) == 16:
        return raw
    if len(raw) == 32:
        try:
            text = raw.decode("ascii")
            if all(c in "0123456789abcdefABCDEF" for c in text):
                return bytes.fromhex(text)
        except (ValueError, UnicodeDecodeError):
            pass
    raise ValueError(
        f"aes_key must decode to 16 raw bytes or 32-char hex string, got {len(raw)} bytes"
    )


# ---------------------------------------------------------------------------
# Markdown → plain text (weixin doesn't render Markdown)
# ---------------------------------------------------------------------------

_RE_CODE_BLOCK = re.compile(r"```[^\n]*\n?([\s\S]*?)```")
_RE_INLINE_CODE = re.compile(r"`([^`]+)`")
_RE_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RE_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_RE_TABLE_SEP = re.compile(r"^\|[\s:|\-]+\|$", re.MULTILINE)
_RE_TABLE_ROW = re.compile(r"^\|(.+)\|$", re.MULTILINE)


def _markdown_to_plain(text: str) -> str:
    text = _RE_CODE_BLOCK.sub(lambda m: m.group(1).strip(), text)
    text = _RE_IMAGE.sub("", text)
    text = _RE_LINK.sub(r"\1", text)
    text = _RE_TABLE_SEP.sub("", text)
    text = _RE_TABLE_ROW.sub(
        lambda m: "  ".join(cell.strip() for cell in m.group(1).split("|")), text,
    )
    text = _RE_INLINE_CODE.sub(r"\1", text)
    text = _RE_HEADING.sub("", text)
    text = _RE_BOLD.sub(r"\1", text)
    text = _RE_ITALIC.sub(r"\1", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Typing ticket cache (per-user, TTL + exponential backoff)
# ---------------------------------------------------------------------------

class _TicketCache:
    __slots__ = ("ticket", "next_fetch_at", "retry_delay_s")

    def __init__(self) -> None:
        self.ticket: str = ""
        self.next_fetch_at: float = 0.0
        self.retry_delay_s: float = _CONFIG_INITIAL_RETRY_S


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _cdn_download_url(base: str, param: str) -> str:
    return f"{base}/download?encrypted_query_param={quote(param)}"


def _cdn_upload_url(base: str, param: str, filekey: str) -> str:
    return f"{base}/upload?encrypted_query_param={quote(param)}&filekey={quote(filekey)}"


def _random_uin() -> str:
    return base64.b64encode(str(struct.unpack("I", os.urandom(4))[0]).encode()).decode()


def _client_id() -> str:
    return f"nanobot-{os.urandom(12).hex()}"


def _image_aes_key(img: dict[str, Any]) -> str:
    """Resolve image AES key: prefer hex ``aeskey`` field → fallback ``media.aes_key``."""
    hex_key = img.get("aeskey", "")
    if hex_key:
        return base64.b64encode(bytes.fromhex(hex_key)).decode()
    return img.get("media", {}).get("aes_key", "")


def _save_media_bytes(data: bytes, ext: str) -> str:
    """Write *data* to the weixin media dir, return the path."""
    media_dir = get_media_dir("weixin")
    name = f"{hashlib.md5(data).hexdigest()[:12]}{ext}"
    path = media_dir / name
    path.write_bytes(data)
    return str(path)


def _guess_extension(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:4] in (b"\x00\x00\x00\x18", b"\x00\x00\x00\x1c", b"\x00\x00\x00\x20"):
        return ".mp4"
    if data[:4] == b"RIFF":
        return ".wav"
    if data[:3] == b"ID3" or data[:2] == b"\xff\xfb":
        return ".mp3"
    if data[:4] == b"%PDF":
        return ".pdf"
    if data[:2] == b"PK":
        return ".zip"
    if data[:1] == b"\x02" or data[:9] == b"#!SILK_V3":
        return ".silk"
    return ".bin"


def _try_silk_to_wav(silk_data: bytes) -> bytes | None:
    """Best-effort SILK → WAV transcode via optional ``pilk`` package."""
    try:
        import pilk  # type: ignore[import-untyped]
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".silk", delete=False) as sf:
            sf.write(silk_data)
            silk_path = sf.name
        wav_path = silk_path.replace(".silk", ".wav")
        try:
            pilk.silk_to_wav(silk_path, wav_path, rate=24000)
            return Path(wav_path).read_bytes()
        finally:
            for p in (silk_path, wav_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass
    except ImportError:
        return None
    except Exception as e:
        logger.warning("Weixin: silk transcode failed: {}", e)
        return None


# ---------------------------------------------------------------------------
# WeixinChannel
# ---------------------------------------------------------------------------

class WeixinChannel(BaseChannel):
    """Weixin personal account channel using iLink Bot long-polling API."""

    name = "weixin"
    display_name = "Weixin"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WeixinConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WeixinConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WeixinConfig = config

        self._token: str = self.config.token
        self._account_id: str = self.config.account_id
        self._get_updates_buf: str = ""
        self._poll_timeout_ms: int = _DEFAULT_POLL_TIMEOUT_MS
        self._sync_file: Path | None = None
        self._context_tokens: dict[str, str] = {}
        self._ticket_cache: dict[str, _TicketCache] = {}
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._client: httpx.AsyncClient | None = None

    # ── Sync buffer persistence ──────────────────────────────────────

    def _init_sync(self) -> None:
        sync_dir = get_data_dir() / "weixin"
        sync_dir.mkdir(parents=True, exist_ok=True)
        self._sync_file = sync_dir / f"{self._account_id or 'default'}.sync.json"
        if self._sync_file.exists() and not self._get_updates_buf:
            try:
                self._get_updates_buf = json.loads(
                    self._sync_file.read_text()
                ).get("get_updates_buf", "")
            except Exception:
                pass

    def _save_sync(self) -> None:
        if self._sync_file:
            try:
                self._sync_file.write_text(
                    json.dumps({"get_updates_buf": self._get_updates_buf})
                )
            except Exception as e:
                logger.warning("Weixin: failed to save sync buf: {}", e)

    # ── HTTP helpers ─────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self._token}",
            "X-WECHAT-UIN": _random_uin(),
        }

    def _base(self) -> dict[str, Any]:
        return {"base_info": {"channel_version": CHANNEL_VERSION}}

    # ── iLink API ────────────────────────────────────────────────────

    async def _api_get_updates(self, buf: str, timeout_ms: int) -> dict[str, Any]:
        body = {**self._base(), "get_updates_buf": buf}
        try:
            r = await self._client.post(  # type: ignore[union-attr]
                f"{self.config.base_url}/ilink/bot/getupdates",
                headers=self._headers(), json=body, timeout=timeout_ms / 1000.0,
            )
            return r.json()
        except httpx.TimeoutException:
            return {"ret": 0, "msgs": [], "get_updates_buf": buf}

    async def _api_send_message(
        self, to: str, items: list[dict[str, Any]], ctx_token: str = "",
    ) -> dict[str, Any]:
        msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to,
            "client_id": _client_id(),
            "message_type": _MSG_TYPE_BOT,
            "message_state": _MSG_STATE_FINISH,
            "item_list": items,
        }
        if ctx_token:
            msg["context_token"] = ctx_token
        r = await self._client.post(  # type: ignore[union-attr]
            f"{self.config.base_url}/ilink/bot/sendmessage",
            headers=self._headers(), json={**self._base(), "msg": msg}, timeout=15,
        )
        return r.json()

    async def _api_get_upload_url(
        self, *, filekey: str, media_type: int, to_user_id: str,
        rawsize: int, rawfilemd5: str, filesize: int, aeskey_hex: str,
    ) -> dict[str, Any]:
        body = {
            **self._base(),
            "filekey": filekey, "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": rawsize, "rawfilemd5": rawfilemd5, "filesize": filesize,
            "no_need_thumb": True, "aeskey": aeskey_hex,
        }
        r = await self._client.post(  # type: ignore[union-attr]
            f"{self.config.base_url}/ilink/bot/getuploadurl",
            headers=self._headers(), json=body, timeout=15,
        )
        return r.json()

    async def _api_send_typing(
        self, user_id: str, ticket: str, status: int = _TYPING_START,
    ) -> None:
        body = {
            **self._base(),
            "ilink_user_id": user_id, "typing_ticket": ticket, "status": status,
        }
        await self._client.post(  # type: ignore[union-attr]
            f"{self.config.base_url}/ilink/bot/sendtyping",
            headers=self._headers(), json=body, timeout=10,
        )

    async def _api_get_config(self, user_id: str, ctx_token: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {**self._base(), "ilink_user_id": user_id}
        if ctx_token:
            body["context_token"] = ctx_token
        r = await self._client.post(  # type: ignore[union-attr]
            f"{self.config.base_url}/ilink/bot/getconfig",
            headers=self._headers(), json=body, timeout=10,
        )
        return r.json()

    # ── Typing ───────────────────────────────────────────────────────

    async def _get_typing_ticket(self, user_id: str, ctx_token: str = "") -> str:
        now = time.monotonic()
        entry = self._ticket_cache.get(user_id)
        if entry and now < entry.next_fetch_at:
            return entry.ticket

        if entry is None:
            entry = _TicketCache()
            self._ticket_cache[user_id] = entry

        try:
            resp = await self._api_get_config(user_id, ctx_token)
            if resp.get("ret", -1) == 0:
                entry.ticket = resp.get("typing_ticket", "")
                entry.next_fetch_at = now + random.random() * _CONFIG_CACHE_TTL_S
                entry.retry_delay_s = _CONFIG_INITIAL_RETRY_S
                return entry.ticket
        except Exception as e:
            logger.warning("Weixin: getConfig failed for {}: {}", user_id, e)

        entry.next_fetch_at = now + entry.retry_delay_s
        entry.retry_delay_s = min(entry.retry_delay_s * 2, _CONFIG_MAX_RETRY_S)
        return entry.ticket

    async def _typing(self, user_id: str, ticket: str, status: int = _TYPING_START) -> None:
        if not ticket:
            return
        try:
            await self._api_send_typing(user_id, ticket, status)
        except Exception:
            pass  # best-effort, never propagate

    # ── CDN download ─────────────────────────────────────────────────

    async def _download_media(
        self, eq: str, ak: str, ext: str = "",
    ) -> str | None:
        try:
            url = _cdn_download_url(self.config.cdn_base_url, eq)
            resp = await self._client.get(url, timeout=60)  # type: ignore[union-attr]
            if resp.status_code != 200:
                logger.warning("Weixin: CDN download {} — {}", resp.status_code, url[:80])
                return None
            if ak:
                data = _aes_ecb_decrypt(resp.content, _parse_aes_key(ak))
            else:
                data = resp.content
            return _save_media_bytes(data, ext or _guess_extension(data))
        except Exception as e:
            logger.error("Weixin: media download failed: {}", e)
            return None

    # ── CDN upload ───────────────────────────────────────────────────

    async def _upload_media(self, file_path: str, to_user: str) -> dict[str, Any] | None:
        try:
            p = Path(file_path)
            if not p.exists():
                return None

            plaintext = p.read_bytes()
            rawsize = len(plaintext)
            rawfilemd5 = hashlib.md5(plaintext).hexdigest()
            filesize = _aes_ecb_padded_size(rawsize)
            filekey = os.urandom(16).hex()
            aeskey = os.urandom(16)

            ext = p.suffix.lower()
            if ext in _IMAGE_EXTS:
                media_type = _UPLOAD_MEDIA_IMAGE
            elif ext in _VIDEO_EXTS:
                media_type = _UPLOAD_MEDIA_VIDEO
            else:
                media_type = _UPLOAD_MEDIA_FILE

            resp = await self._api_get_upload_url(
                filekey=filekey, media_type=media_type, to_user_id=to_user,
                rawsize=rawsize, rawfilemd5=rawfilemd5, filesize=filesize,
                aeskey_hex=aeskey.hex(),
            )
            upload_param = resp.get("upload_param", "")
            if not upload_param:
                logger.warning("Weixin: getUploadUrl returned no upload_param")
                return None

            ciphertext = _aes_ecb_encrypt(plaintext, aeskey)
            cdn_url = _cdn_upload_url(self.config.cdn_base_url, upload_param, filekey)
            download_param = await self._cdn_put(cdn_url, ciphertext)
            if not download_param:
                return None

            aeskey_b64 = base64.b64encode(aeskey.hex().encode()).decode()
            media_ref = {
                "encrypt_query_param": download_param,
                "aes_key": aeskey_b64,
                "encrypt_type": 1,
            }

            if media_type == _UPLOAD_MEDIA_IMAGE:
                return {"type": ITEM_IMAGE, "image_item": {"media": media_ref, "mid_size": filesize}}
            if media_type == _UPLOAD_MEDIA_VIDEO:
                return {"type": ITEM_VIDEO, "video_item": {"media": media_ref, "video_size": filesize}}
            return {"type": ITEM_FILE, "file_item": {"media": media_ref, "file_name": p.name, "len": str(rawsize)}}
        except Exception as e:
            logger.error("Weixin: upload failed: {}", e)
            return None

    async def _cdn_put(self, url: str, data: bytes) -> str | None:
        """Upload bytes to CDN with retry. Returns download param or None."""
        for attempt in range(1, _CDN_UPLOAD_MAX_RETRIES + 1):
            try:
                r = await self._client.post(  # type: ignore[union-attr]
                    url, content=data,
                    headers={"Content-Type": "application/octet-stream"}, timeout=120,
                )
                if 400 <= r.status_code < 500:
                    logger.error("Weixin: CDN 4xx {}", r.status_code)
                    return None
                if r.status_code != 200:
                    raise RuntimeError(f"CDN {r.status_code}")
                param = r.headers.get("x-encrypted-param", "")
                if not param:
                    raise RuntimeError("missing x-encrypted-param")
                return param
            except Exception as e:
                if attempt == _CDN_UPLOAD_MAX_RETRIES:
                    logger.error("Weixin: CDN upload failed after {} attempts: {}", attempt, e)
                    return None
                logger.warning("Weixin: CDN upload attempt {}/{} failed: {}", attempt, _CDN_UPLOAD_MAX_RETRIES, e)
        return None  # unreachable, satisfies type checker

    # ── Inbound parsing ──────────────────────────────────────────────

    def _parse_inbound(
        self, msg: dict[str, Any],
    ) -> tuple[str, str, str, list[dict[str, Any]], dict[str, Any]]:
        """Parse a WeixinMessage → (sender, chat_id, text, media_jobs, metadata)."""
        sender = msg.get("from_user_id", "")
        ctx_token = msg.get("context_token", "")
        if ctx_token and sender:
            self._context_tokens[sender] = ctx_token

        texts: list[str] = []
        media_jobs: list[dict[str, Any]] = []
        ref_media: dict[str, Any] | None = None

        for item in msg.get("item_list", []):
            itype = item.get("type", 0)

            if itype == ITEM_TEXT:
                t = item.get("text_item", {}).get("text", "") or item.get("text_item", {}).get("content", "")
                if t:
                    ref = item.get("ref_msg")
                    if ref:
                        ri = ref.get("message_item")
                        if ri and ri.get("type", 0) in _MEDIA_ITEM_TYPES:
                            ref_media = ri
                        else:
                            parts = [p for p in (ref.get("title", ""), (ri or {}).get("text_item", {}).get("text", "")) if p]
                            if parts:
                                t = f"[Quote: {' | '.join(parts)}]\n{t}"
                    texts.append(t)

            elif itype == ITEM_IMAGE:
                img = item.get("image_item", {})
                eq = img.get("media", {}).get("encrypt_query_param", "")
                if eq:
                    media_jobs.append({"type": "image", "eq": eq, "ak": _image_aes_key(img)})

            elif itype == ITEM_VOICE:
                voice = item.get("voice_item", {})
                if voice.get("text"):
                    texts.append(voice["text"])
                else:
                    m = voice.get("media", {})
                    eq, ak = m.get("encrypt_query_param", ""), m.get("aes_key", "")
                    if eq and ak:
                        media_jobs.append({"type": "voice", "eq": eq, "ak": ak})

            elif itype == ITEM_FILE:
                fi = item.get("file_item", {})
                m = fi.get("media", {})
                eq, ak = m.get("encrypt_query_param", ""), m.get("aes_key", "")
                if eq and ak:
                    media_jobs.append({"type": "file", "eq": eq, "ak": ak, "name": fi.get("file_name", "file")})

            elif itype == ITEM_VIDEO:
                m = item.get("video_item", {}).get("media", {})
                eq, ak = m.get("encrypt_query_param", ""), m.get("aes_key", "")
                if eq and ak:
                    media_jobs.append({"type": "video", "eq": eq, "ak": ak})

        # Ref-msg media fallback
        if not media_jobs and ref_media:
            rtype = ref_media.get("type", 0)
            key = _ITEM_KEY.get(rtype, "")
            if key:
                sub = ref_media.get(key, {})
                m = sub.get("media", {})
                eq = m.get("encrypt_query_param", "")
                ak = _image_aes_key(sub) if rtype == ITEM_IMAGE else m.get("aes_key", "")
                if eq:
                    job: dict[str, Any] = {"type": {ITEM_IMAGE: "image", ITEM_VIDEO: "video", ITEM_FILE: "file", ITEM_VOICE: "voice"}.get(rtype, "file"), "eq": eq, "ak": ak}
                    if rtype == ITEM_FILE:
                        job["name"] = sub.get("file_name", "file")
                    media_jobs.append(job)

        meta = {"msg_id": str(msg.get("message_id", "")), "context_token": ctx_token}
        return sender, sender, "\n".join(texts), media_jobs, meta

    async def _download_all_media(
        self, jobs: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        """Download deferred media. Returns (paths, content_lines)."""
        paths: list[str] = []
        lines: list[str] = []

        for job in jobs:
            mtype = job["type"]
            ext = {
                "image": ".jpg", "video": ".mp4", "voice": ".silk", "file": "",
            }.get(mtype, "")

            fp = await self._download_media(job["eq"], job.get("ak", ""), ext)
            if not fp:
                lines.append(f"[{mtype}: download failed]")
                continue

            paths.append(fp)
            fname = os.path.basename(fp)

            if mtype == "voice":
                wav = _try_silk_to_wav(Path(fp).read_bytes())
                if wav:
                    fp = fp.rsplit(".", 1)[0] + ".wav"
                    Path(fp).write_bytes(wav)
                    paths[-1] = fp
                tx = await self.transcribe_audio(fp)
                lines.append(f"[Voice] {tx}" if tx else f"[voice: {fname}]")
            elif mtype == "file":
                lines.append(f"[file: {job.get('name', fname)}]\n[File: source: {fp}]")
            elif mtype == "image":
                lines.append(f"[image: {fname}]\n[Image: source: {fp}]")
            elif mtype == "video":
                lines.append(f"[video: {fname}]\n[Video: source: {fp}]")

        return paths, lines

    # ── Error notice ─────────────────────────────────────────────────

    async def _notify_error(self, to: str, text: str) -> None:
        ctx = self._context_tokens.get(to, "")
        if not ctx:
            return
        try:
            await self._api_send_message(to, [{"type": ITEM_TEXT, "text_item": {"text": text}}], ctx)
        except Exception:
            pass

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self._token:
            logger.error(
                "Weixin: no token configured. "
                "Run `nanobot channels login -c weixin` to scan QR code and login."
            )
            return

        try:
            from Crypto.Cipher import AES  # noqa: F401
        except ImportError:
            logger.error(
                "Weixin: pycryptodome not installed (required for media encryption). "
                "Run: pip install nanobot-ai[weixin]"
            )
            return

        self._init_sync()
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._running = True
        failures = 0

        logger.info("Weixin channel started (account: {})", self._account_id or "default")

        while self._running:
            try:
                resp = await self._api_get_updates(self._get_updates_buf, self._poll_timeout_ms)

                suggested = resp.get("longpolling_timeout_ms")
                if isinstance(suggested, int) and suggested > 0:
                    self._poll_timeout_ms = suggested

                errcode = resp.get("errcode")
                ret = resp.get("ret")
                is_error = (ret is not None and ret != 0) or (errcode is not None and errcode != 0)

                if is_error:
                    if errcode == -14 or ret == -14:
                        logger.warning("Weixin: session expired, pausing {} min", _SESSION_PAUSE_S // 60)
                        failures = 0
                        await asyncio.sleep(_SESSION_PAUSE_S)
                        continue
                    failures += 1
                    logger.warning("Weixin: getupdates error ret={} errcode={} ({}/{})",
                                   ret, errcode, failures, _MAX_CONSECUTIVE_FAILURES)
                    delay = _BACKOFF_DELAY_S if failures >= _MAX_CONSECUTIVE_FAILURES else _RETRY_DELAY_S
                    if failures >= _MAX_CONSECUTIVE_FAILURES:
                        failures = 0
                    await asyncio.sleep(delay)
                    continue

                failures = 0
                new_buf = resp.get("get_updates_buf", "")
                if new_buf:
                    self._get_updates_buf = new_buf
                    self._save_sync()

                for raw in resp.get("msgs", []):
                    await self._process_inbound(raw)

            except asyncio.CancelledError:
                break
            except Exception as e:
                failures += 1
                logger.error("Weixin: poll error ({}/{}): {}", failures, _MAX_CONSECUTIVE_FAILURES, e)
                delay = _BACKOFF_DELAY_S if failures >= _MAX_CONSECUTIVE_FAILURES else _RETRY_DELAY_S
                if failures >= _MAX_CONSECUTIVE_FAILURES:
                    failures = 0
                await asyncio.sleep(delay)

    async def _process_inbound(self, raw: dict[str, Any]) -> None:
        try:
            mid = str(raw.get("message_id", "")) or f"{raw.get('from_user_id', '')}_{id(raw)}"
            if mid in self._seen:
                return
            self._seen[mid] = None
            while len(self._seen) > 1000:
                self._seen.popitem(last=False)

            sender, chat_id, text, media_jobs, meta = self._parse_inbound(raw)
            if not sender:
                return

            ticket = await self._get_typing_ticket(sender, raw.get("context_token", ""))
            await self._typing(sender, ticket)

            media_paths: list[str] = []
            if media_jobs:
                paths, extra = await self._download_all_media(media_jobs)
                media_paths = paths
                if extra:
                    text = "\n".join(filter(None, [text, *extra]))

            if not text and not media_paths:
                return

            await self._handle_message(
                sender_id=sender, chat_id=chat_id, content=text,
                media=media_paths or None, metadata=meta,
            )
        except Exception as e:
            logger.error("Weixin: inbound error: {}", e)

    async def send(self, msg: OutboundMessage) -> None:
        if not self._client:
            logger.warning("Weixin: send called but client not initialized")
            return

        logger.info("Weixin: send to={} text_len={} media={}", msg.chat_id, len(msg.content), msg.media)

        ctx = self._context_tokens.get(msg.chat_id, "")
        if not ctx:
            logger.warning("Weixin: no context_token for {}, send may fail", msg.chat_id)
        ticket = await self._get_typing_ticket(msg.chat_id)

        try:
            for media_path in msg.media:
                logger.debug("Weixin: uploading media {}", media_path)
                item = await self._upload_media(media_path, msg.chat_id)
                if item:
                    resp = await self._api_send_message(msg.chat_id, [item], ctx)
                    logger.debug("Weixin: media sent, response={}", resp)
                else:
                    logger.warning("Weixin: upload returned None for {}", media_path)

            if msg.content:
                plain = _markdown_to_plain(msg.content)
                if plain:
                    await self._api_send_message(
                        msg.chat_id, [{"type": ITEM_TEXT, "text_item": {"text": plain}}], ctx,
                    )
        except Exception as e:
            logger.error("Weixin: send failed: {}", e)
            err = str(e)
            if "CDN" in err or "upload" in err:
                await self._notify_error(msg.chat_id, "⚠️ Media upload failed, please try again later.")
            else:
                await self._notify_error(msg.chat_id, f"⚠️ Send failed: {err[:200]}")
        finally:
            await self._typing(msg.chat_id, ticket, _TYPING_CANCEL)

    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("Weixin channel stopped")


# ---------------------------------------------------------------------------
# QR code login (standalone, no external dependency)
# ---------------------------------------------------------------------------

_QR_LONG_POLL_TIMEOUT_S = 35
_QR_LOGIN_TIMEOUT_S = 480
_QR_MAX_REFRESH = 3


async def weixin_qr_login(
    base_url: str = "https://ilinkai.weixin.qq.com",
    bot_type: str = "3",
    timeout_s: int = _QR_LOGIN_TIMEOUT_S,
    save_to_config: bool = True,
) -> dict[str, str]:
    """Perform QR code login and return ``{token, account_id, base_url, user_id}``."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=_QR_LONG_POLL_TIMEOUT_S + 5) as client:
        qr_api = f"{base_url}/ilink/bot/get_bot_qrcode?bot_type={bot_type}"

        qrcode_str, qrcode_url = await _fetch_qr(client, qr_api)
        _display_qr(qrcode_url)

        deadline = time.monotonic() + timeout_s
        refreshes = 0

        while time.monotonic() < deadline:
            try:
                url = f"{base_url}/ilink/bot/get_qrcode_status?qrcode={quote(qrcode_str)}"
                r = await client.get(url, headers={"iLink-App-ClientVersion": "1"}, timeout=_QR_LONG_POLL_TIMEOUT_S)
                data = r.json()
            except httpx.TimeoutException:
                continue

            status = data.get("status", "")

            if status == "wait":
                continue
            if status == "scaned":
                print("\n👀 Scanned, please confirm on weixin…")
                await asyncio.sleep(1)
                continue
            if status == "confirmed":
                acct = data.get("ilink_bot_id", "")
                if not acct:
                    raise RuntimeError("Server did not return ilink_bot_id")
                result = {
                    "token": data.get("bot_token", ""),
                    "account_id": acct,
                    "base_url": data.get("baseurl", "") or base_url,
                    "user_id": data.get("ilink_user_id", ""),
                }
                if save_to_config:
                    _save_login_to_config(result)
                return result
            if status == "expired":
                refreshes += 1
                if refreshes >= _QR_MAX_REFRESH:
                    raise RuntimeError("QR code expired multiple times, please login again")
                print(f"\n⏳ QR code expired, refreshing…({refreshes}/{_QR_MAX_REFRESH})")
                qrcode_str, qrcode_url = await _fetch_qr(client, qr_api)
                _display_qr(qrcode_url)
                continue

            await asyncio.sleep(1)

        raise RuntimeError("Login timed out")


async def _fetch_qr(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    r = await client.get(url)
    r.raise_for_status()
    d = r.json()
    code = d.get("qrcode", "")
    if not code:
        raise RuntimeError(f"Failed to get QR code: {d}")
    return code, d.get("qrcode_img_content", "")


def _display_qr(url: str) -> None:
    import sys

    print("\n📱 Scan the QR code below with weixin to login:\n")
    try:
        import qrcode as qrc  # type: ignore[import-untyped]
        qr = qrc.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        # print_ascii uses half-block chars (▀▄█), halving the height
        qr.print_ascii(out=sys.stdout, invert=True)
        print()
    except ImportError:
        print("(Tip: pip install qrcode to display QR code in terminal)\n")
    print(f"Link: {url}\n")


def _save_login_to_config(result: dict[str, str]) -> None:
    try:
        from nanobot.config.loader import get_config_path, load_config, save_config

        config = load_config()
        path = get_config_path()

        section = getattr(config.channels, "weixin", None)
        data: dict[str, Any] = (
            section if isinstance(section, dict)
            else section.model_dump(by_alias=True) if hasattr(section, "model_dump")
            else {}
        ) or {}

        data.update(enabled=True, token=result["token"], accountId=result["account_id"])
        if result.get("base_url"):
            data["baseUrl"] = result["base_url"]
        uid = result.get("user_id", "")
        af = data.get("allowFrom", [])
        if uid and uid not in af:
            af.append(uid)
            data["allowFrom"] = af

        setattr(config.channels, "weixin", data)
        save_config(config, path)

        print(f"\n✅ Config saved to {path}")
        print(f"   Account: {result['account_id']}")
        if uid:
            print(f"   User: {uid} (added to allowFrom)")
    except Exception as e:
        print(f"\n⚠️  Failed to save config: {e}")
        print(f"   Please manually add token={result['token'][:30]}… accountId={result['account_id']}")


def run_weixin_qr_login_sync(base_url: str = "https://ilinkai.weixin.qq.com") -> None:
    """Synchronous CLI entry point."""
    try:
        asyncio.run(weixin_qr_login(base_url=base_url))
        print("\n🎉 Login complete! Run `nanobot gateway` to start the service.")
    except RuntimeError as e:
        print(f"\n❌ Login failed: {e}")
    except KeyboardInterrupt:
        print("\n\nCancelled.")
