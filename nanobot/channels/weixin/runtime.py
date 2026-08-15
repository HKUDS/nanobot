"""Personal WeChat (微信) channel using HTTP long-poll API.

Uses the ilinkai.weixin.qq.com API for personal WeChat messaging.
No WebSocket, no local WeChat client needed — just HTTP requests with a
bot token obtained via QR code login.

Protocol aligned with ``@tencent-weixin/openclaw-weixin`` v2.4.6.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import random
import re
import time
import uuid
from collections import OrderedDict
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import httpx
from loguru import logger
from pydantic import Field, model_validator

from nanobot import __version__
from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir, get_runtime_subdir
from nanobot.config.schema import Base

# ---------------------------------------------------------------------------
# Protocol constants (from openclaw-weixin types.ts)
# ---------------------------------------------------------------------------

# MessageItemType
ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5
ITEM_TOOL_CALL_START = 11
ITEM_TOOL_CALL_RESULT = 12

# MessageType  (1 = inbound from user, 2 = outbound from bot)
MESSAGE_TYPE_BOT = 2

# MessageState
MESSAGE_STATE_FINISH = 2

WEIXIN_MAX_MESSAGE_LEN = 1800
WEIXIN_CHANNEL_VERSION = "2.4.6"
ILINK_APP_ID = "bot"


def _build_client_version(version: str) -> int:
    """Encode semantic version as 0x00MMNNPP (major/minor/patch in one uint32)."""
    parts = version.split(".")

    def _as_int(idx: int) -> int:
        try:
            return int(parts[idx])
        except Exception:
            return 0

    major = _as_int(0)
    minor = _as_int(1)
    patch = _as_int(2)
    return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)

ILINK_APP_CLIENT_VERSION = _build_client_version(WEIXIN_CHANNEL_VERSION)
BASE_INFO: dict[str, str] = {
    "channel_version": WEIXIN_CHANNEL_VERSION,
    "bot_agent": f"nanobot/{__version__} (python)",
}

# Business error codes observed in the public iLink protocol.
ERRCODE_CONTEXT_RESTRICTED = -2
ERRCODE_INVALID_ARGUMENT = -3
ERRCODE_STALE_TOKEN = -14
WEIXIN_AUTH_EXPIRED_MESSAGE = "WeChat login expired. Scan again to reconnect."
_REPLACED_CONFIG_TOKEN_HASH_KEY = "replaced_config_token_sha256"

# iLink context_token is observed to expire server-side after ~90-160s of
# agent inactivity (openclaw/openclaw#61174). Proactively refresh before
# sending if the cached token is older than this threshold.
CONTEXT_TOKEN_MAX_AGE_S = 60


# Retry constants (matching the reference plugin's monitor.ts)
MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAY_S = 30
RETRY_DELAY_S = 2
MAX_QR_REFRESH_COUNT = 3
TYPING_STATUS_TYPING = 1
TYPING_STATUS_CANCEL = 2
TYPING_TICKET_TTL_S = 24 * 60 * 60
TYPING_KEEPALIVE_INTERVAL_S = 5
CONFIG_CACHE_INITIAL_RETRY_S = 2
CONFIG_CACHE_MAX_RETRY_S = 60 * 60

# Default long-poll timeout; overridden by server via longpolling_timeout_ms.
DEFAULT_LONG_POLL_TIMEOUT_S = 35
DEFAULT_API_TIMEOUT_S = 15
DEFAULT_CONFIG_TIMEOUT_S = 10
QR_POLL_TIMEOUT_S = 60
MAX_DEFERRED_MESSAGES_PER_CHAT = 3
_RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429}

# Media-type codes for getuploadurl  (1=image, 2=video, 3=file, 4=voice)
UPLOAD_MEDIA_IMAGE = 1
UPLOAD_MEDIA_VIDEO = 2
UPLOAD_MEDIA_FILE = 3
UPLOAD_MEDIA_VOICE = 4

# File extensions considered as images / videos for outbound media
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".ico", ".svg"}
_VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}
_VOICE_EXTS = {".mp3", ".wav", ".amr", ".silk", ".ogg", ".m4a", ".aac", ".flac"}


def _has_downloadable_media_locator(media: dict[str, Any] | None) -> bool:
    if not isinstance(media, dict):
        return False
    return bool(str(media.get("encrypt_query_param", "") or "") or str(media.get("full_url", "") or "").strip())


def sanitize_weixin_markdown(content: str) -> str:
    """Remove constructs known to render badly in the WeChat iLink client."""
    if not content:
        return content

    # Keep complete fenced and inline code regions byte-for-byte. WeChat treats
    # a bare angle bracket in normal text as markup and may hide everything
    # after it, so use full-width forms outside code.
    code_pattern = re.compile(r"(```[\s\S]*?```|`[^`\n]*`)")
    parts = code_pattern.split(content)
    for index in range(0, len(parts), 2):
        text = parts[index]
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
        text = text.replace("<", "＜").replace(">", "＞")
        text = text.replace("~~", "")
        text = re.sub(r"(?m)^#{5,6}\s+", "", text)
        parts[index] = text
    return "".join(parts)


def split_weixin_message(
    content: str,
    max_len: int = WEIXIN_MAX_MESSAGE_LEN,
) -> list[str]:
    """Split sanitized text while balancing fenced code blocks per message."""
    content = sanitize_weixin_markdown(content).strip()
    if not content:
        return []
    if max_len <= 0 or len(content) <= max_len:
        return [content]

    chunks: list[str] = []
    remaining = content
    in_fence = False
    while remaining:
        prefix = "```\n" if in_fence else ""
        suffix_budget = 4  # ``\n``` `` when the raw slice leaves a fence open.
        available = max_len - len(prefix) - suffix_budget
        if available <= 0:
            return [content]
        if len(remaining) <= available:
            raw_piece = remaining
        else:
            candidate = remaining[:available]
            cut = candidate.rfind("\n\n")
            if cut <= 0:
                cut = candidate.rfind("\n")
            if cut <= 0:
                punctuation = max(candidate.rfind(mark) for mark in "。！？；.!?; ")
                cut = punctuation + 1 if punctuation >= 0 else available
            raw_piece = remaining[:cut]
        remaining = remaining[len(raw_piece):].lstrip()
        toggles = raw_piece.count("```")
        next_in_fence = in_fence ^ bool(toggles % 2)
        rendered = prefix + raw_piece.rstrip()
        if next_in_fence:
            rendered += "\n```"
        chunks.append(rendered)
        in_fence = next_in_fence
    return chunks


class WeixinConfig(Base):
    """Personal WeChat channel configuration."""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)
    base_url: str = "https://ilinkai.weixin.qq.com"
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    route_tag: str | int | None = None
    token: str = ""  # Manually set token, or obtained via QR login
    state_dir: str = ""  # Default: ~/.nanobot/weixin/
    poll_timeout: int = DEFAULT_LONG_POLL_TIMEOUT_S  # seconds for long-poll
    # Extra progress messages consume the same undocumented iLink send quota as
    # final replies. Keep them off unless an operator explicitly opts in.
    send_progress: bool = False
    send_tool_hints: bool = False
    reply_progress_messages: bool = False
    reply_progress_max_messages: int = Field(default=2, ge=0, le=4)
    context_message_budget: int = Field(default=8, ge=1, le=10)
    # Default on: WeChat iLink has no native incremental delivery (send_delta is
    # buffered and the final answer is still sent in one shot), so streaming has
    # zero user-facing effect here — it only switches the LLM call to the
    # streaming API. That avoids upstream Anthropic relays that drop tool_use
    # id/name/input on the non-streaming Messages path (a common third-party
    # relay bug). Set to false only if a relay's streaming/SSE path is broken.
    streaming: bool = True
    # Optional user-visible block streaming. Disabled by default because every
    # block is a separate iLink message and consumes the context send budget.
    block_streaming: bool = False
    block_streaming_min_chars: int = Field(default=1200, ge=200, le=1800)
    block_streaming_max_messages: int = Field(default=3, ge=1, le=4)

    @model_validator(mode="after")
    def _enable_tool_event_transport(self) -> WeixinConfig:
        if self.reply_progress_messages:
            self.send_progress = True
            self.send_tool_hints = True
        return self


class WeixinAPIError(RuntimeError):
    """A parsed WeChat API failure with an explicit retry contract."""

    def __init__(
        self,
        endpoint: str,
        *,
        ret: int = 0,
        errcode: int = 0,
        errmsg: str = "",
        retryable: bool = False,
    ) -> None:
        self.endpoint = endpoint
        self.ret = ret
        self.errcode = errcode
        self.errmsg = errmsg
        self.retryable = retryable
        code = errcode or ret
        super().__init__(
            f"WeChat {endpoint} failed (code={code}, ret={ret}, errcode={errcode}): "
            f"{errmsg or 'no error message'}"
        )


class WeixinQuotaError(WeixinAPIError):
    """The current context token cannot send more messages right now."""


class WeixinAuthError(WeixinAPIError):
    """The persisted bot token is stale and interactive login is required."""


@dataclass(slots=True)
class _DeliveryState:
    completed_parts: set[str] = field(default_factory=set)
    media_aes_keys: dict[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _SendOptions:
    client_id: str
    run_id: str = ""
    file_key: str | None = None
    aes_key_raw: bytes | None = None
    reserve_budget: int = 0


_SEND_OPTIONS: ContextVar[_SendOptions | None] = ContextVar(
    "weixin_send_options",
    default=None,
)


class WeixinChannel(BaseChannel):
    """
    Personal WeChat channel using HTTP long-poll.

    Connects to ilinkai.weixin.qq.com API to receive and send personal
    WeChat messages. Authentication is via QR code login which produces
    a bot token.
    """

    name = "weixin"
    display_name = "WeChat"
    send_progress = False
    send_tool_hints = False

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
        self._replaced_config_token_hash: str = ""
        self._poll_task: asyncio.Task[None] | None = None
        self._next_poll_timeout_s: int = DEFAULT_LONG_POLL_TIMEOUT_S
        self._auth_required = False
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        self._typing_tickets: dict[str, dict[str, Any]] = {}
        self._context_token_at: dict[str, float] = {}
        self._pending_tool_hints: dict[str, list[str]] = {}
        # Buffers streamed content deltas per chat. WeChat iLink has no native
        # incremental delivery, so when streaming is enabled we accumulate the
        # deltas and flush the full reply in one shot at _stream_end.
        self._stream_buffers: dict[str, list[str]] = {}
        self._stream_sent_counts: dict[str, int] = {}
        self._stream_live_disabled: set[str] = set()
        self._delivery_states: OrderedDict[str, _DeliveryState] = OrderedDict()
        self._deferred_outbound: dict[str, OrderedDict[str, OutboundMessage]] = {}
        self._context_send_counts: dict[str, int] = {}
        self._reply_run_ids: dict[str, str] = {}
        self._reply_progress_counts: dict[str, int] = {}

    def progress_transport_defaults(self) -> tuple[bool, bool]:
        return self.config.send_progress, self.config.send_tool_hints

    def should_retry_send_error(self, error: Exception) -> bool:
        if isinstance(error, WeixinAPIError):
            return error.retryable
        if isinstance(error, httpx.HTTPStatusError):
            return self._is_retryable_http_status(error.response.status_code)
        return True

    def start_error_message(self, error: Exception) -> str | None:
        if isinstance(error, WeixinAuthError):
            return WEIXIN_AUTH_EXPIRED_MESSAGE
        return None

    @staticmethod
    def _new_http_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
        """Create a direct-route client shared by login, connect, and polling."""
        return httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
        )

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

    @staticmethod
    def _token_fingerprint(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest() if token else ""

    def _load_state(self, *, required_replaced_config_token: str | None = None) -> bool:
        """Load saved account state. Returns True if a valid token was found."""
        state_file = self._get_state_dir() / "account.json"
        if not state_file.exists():
            return False
        try:
            data = cast(dict[str, Any], json.loads(state_file.read_text()))
            replaced_config_token_hash = data.get(_REPLACED_CONFIG_TOKEN_HASH_KEY, "")
            if not isinstance(replaced_config_token_hash, str):
                replaced_config_token_hash = ""
            if required_replaced_config_token is not None and (
                replaced_config_token_hash
                != self._token_fingerprint(required_replaced_config_token)
            ):
                return False
            self._token = data.get("token", "")
            self._replaced_config_token_hash = replaced_config_token_hash
            self._get_updates_buf = data.get("get_updates_buf", "")
            context_tokens = data.get("context_tokens", {})
            if isinstance(context_tokens, dict):
                self._context_tokens = {
                    str(user_id): str(token)
                    for user_id, token in cast(dict[object, object], context_tokens).items()
                    if str(user_id).strip() and str(token).strip()
                }
            else:
                self._context_tokens = {}
            typing_tickets = data.get("typing_tickets", {})
            if isinstance(typing_tickets, dict):
                self._typing_tickets = {
                    str(user_id): cast(dict[str, Any], ticket)
                    for user_id, ticket in cast(dict[object, object], typing_tickets).items()
                    if str(user_id).strip() and isinstance(ticket, dict)
                }
            else:
                self._typing_tickets = {}
            base_url = data.get("base_url", "")
            if base_url:
                self.config.base_url = base_url
            return bool(self._token)
        except Exception:
            self.logger.error("Failed to load Weixin account state", exc_info=True)
            return False

    def _save_state(self, *, force: bool = False) -> None:
        state_file = self._get_state_dir() / "account.json"
        with suppress(Exception):
            if not force and state_file.exists():
                persisted: object = None
                try:
                    persisted = json.loads(state_file.read_text())
                except Exception:
                    persisted = None
                persisted_token = ""
                persisted_replaced_config_token_hash = ""
                if isinstance(persisted, dict):
                    persisted_mapping = cast(dict[str, object], persisted)
                    persisted_token = str(persisted_mapping.get("token", "") or "")
                    persisted_hash = persisted_mapping.get(
                        _REPLACED_CONFIG_TOKEN_HASH_KEY,
                        "",
                    )
                    if isinstance(persisted_hash, str):
                        persisted_replaced_config_token_hash = persisted_hash
                persisted_replaces_config_token = bool(self.config.token) and (
                    persisted_replaced_config_token_hash
                    == self._token_fingerprint(self.config.token)
                )
                configured_token_is_authoritative: bool = bool(self.config.token) and (
                    self._token == self.config.token
                    and not persisted_replaces_config_token
                )
                if (
                    persisted_token
                    and persisted_token != self._token
                    and not configured_token_is_authoritative
                ):
                    # A concurrent QR login may have committed a newer token.
                    # Never let an older runtime snapshot overwrite it.
                    return
            data = {
                "token": self._token,
                "get_updates_buf": self._get_updates_buf,
                "context_tokens": self._context_tokens,
                "typing_tickets": self._typing_tickets,
                "base_url": self.config.base_url,
            }
            if self._replaced_config_token_hash:
                data[_REPLACED_CONFIG_TOKEN_HASH_KEY] = self._replaced_config_token_hash
            state_file.write_text(json.dumps(data, ensure_ascii=False))

    def _commit_account(self, *, token: str, base_url: str) -> None:
        self._token = token
        self._auth_required = False
        # A successful QR scan replaces only the configured token it was started
        # against. A later manual token edit must become authoritative again.
        self._replaced_config_token_hash = (
            self._token_fingerprint(self.config.token)
            if self.config.token and self.config.token != token
            else ""
        )
        if base_url:
            self.config.base_url = base_url
        self._save_state(force=True)
        self._persist_connect_credentials(token=token, base_url=base_url)

    def _persist_connect_credentials(self, *, token: str, base_url: str) -> None:
        """Write the QR-login token and base_url back to config.json.

        The connect flow saves account state to ``account.json`` (via
        ``_save_state``), but the WebUI's post-connect ``enable`` step calls
        ``set_channel_config_enabled`` which reads config.json. Without
        persisting the token here, that step would overwrite it with the
        default empty value, losing the freshly obtained credential.
        """
        from nanobot.config.loader import get_config_path, load_config, save_config

        try:
            full_config = load_config()
            section = getattr(full_config.channels, "weixin", None)
            if section is not None and hasattr(section, "model_dump"):
                values = section.model_dump(mode="json", by_alias=True)
            elif isinstance(section, dict):
                values = dict(cast(dict[str, Any], section))
            else:
                values = {}
            values["token"] = token
            if base_url:
                values["baseUrl"] = base_url
            setattr(full_config.channels, "weixin", values)
            save_config(full_config, get_config_path())
        except Exception:
            self.logger.exception("Failed to persist WeChat credentials to config.json")

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
            "iLink-App-Id": ILINK_APP_ID,
            "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
        }
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self.config.route_tag is not None and str(self.config.route_tag).strip():
            headers["SKRouteTag"] = str(self.config.route_tag).strip()
        return headers

    @staticmethod
    def _network_error_category(err: Exception) -> str:
        if isinstance(err, httpx.TimeoutException):
            return "timeout"
        message = str(err).lower()
        if any(value in message for value in ("name or service", "nodename", "getaddrinfo", "dns")):
            return "dns"
        if any(value in message for value in ("ssl", "tls", "certificate")):
            return "tls"
        if isinstance(err, httpx.TransportError):
            return "tcp"
        return "unknown"

    @staticmethod
    def _is_retryable_http_status(status_code: int) -> bool:
        return status_code in _RETRYABLE_HTTP_STATUS_CODES or status_code >= 500

    @staticmethod
    def _response_int(data: dict[str, Any], key: str) -> int:
        value = data.get(key, 0)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        try:
            return int(str(value or "0"))
        except ValueError:
            return 0

    @classmethod
    def _raise_for_api_error(cls, endpoint: str, data: dict[str, Any]) -> None:
        ret = cls._response_int(data, "ret")
        errcode = cls._response_int(data, "errcode")
        if ret == 0 and errcode == 0:
            return
        errmsg = str(data.get("errmsg", "") or "")
        if ERRCODE_CONTEXT_RESTRICTED in {ret, errcode}:
            raise WeixinQuotaError(
                endpoint,
                ret=ret,
                errcode=errcode,
                errmsg=errmsg or "context token expired, quota exhausted, or sending restricted",
            )
        if ERRCODE_STALE_TOKEN in {ret, errcode}:
            raise WeixinAuthError(
                endpoint,
                ret=ret,
                errcode=errcode,
                errmsg=errmsg or "bot token is stale; scan a new QR code",
            )
        raise WeixinAPIError(
            endpoint,
            ret=ret,
            errcode=errcode,
            errmsg=errmsg,
        )

    def _request_timeout(self, endpoint: str) -> float:
        if endpoint.endswith("getupdates"):
            return self._next_poll_timeout_s + 10
        if endpoint.endswith(("getconfig", "sendtyping", "notifystart", "notifystop")):
            return DEFAULT_CONFIG_TIMEOUT_S
        if endpoint.endswith("get_qrcode_status"):
            return QR_POLL_TIMEOUT_S
        return DEFAULT_API_TIMEOUT_S

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        endpoint: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        assert self._client is not None
        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=body,
                headers=headers,
                timeout=self._request_timeout(endpoint),
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self.logger.warning(
                "WeChat request failed endpoint={} category={} error={}",
                endpoint,
                self._network_error_category(exc),
                type(exc).__name__,
            )
            raise
        except httpx.HTTPStatusError as exc:
            self.logger.warning(
                "WeChat request failed endpoint={} category=http status={}",
                endpoint,
                exc.response.status_code,
            )
            raise
        except (json.JSONDecodeError, ValueError) as exc:
            raise WeixinAPIError(
                endpoint,
                errmsg="server returned invalid JSON",
                retryable=True,
            ) from exc
        if not isinstance(data, dict):
            raise WeixinAPIError(
                endpoint,
                errmsg="server returned a non-object JSON payload",
                retryable=True,
            )
        return cast(dict[str, Any], data)

    @staticmethod
    def _is_retryable_media_download_error(err: Exception) -> bool:
        if isinstance(err, httpx.TimeoutException | httpx.TransportError):
            return True
        if isinstance(err, httpx.HTTPStatusError):
            status_code = (
                err.response.status_code
                if cast(object, err.response) is not None
                else 0
            )
            return WeixinChannel._is_retryable_http_status(status_code)
        return False

    async def _api_get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        assert self._client is not None
        url = f"{self.config.base_url}/{endpoint}"
        hdrs = self._make_headers(auth=auth)
        if extra_headers:
            hdrs.update(extra_headers)
        return await self._request_json(
            "GET", url, endpoint=endpoint, params=params, headers=hdrs,
        )

    async def _api_get_with_base(
        self,
        *,
        base_url: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET helper that allows overriding base_url for QR redirect polling."""
        assert self._client is not None
        url = f"{base_url.rstrip('/')}/{endpoint}"
        hdrs = self._make_headers(auth=auth)
        if extra_headers:
            hdrs.update(extra_headers)
        return await self._request_json(
            "GET", url, endpoint=endpoint, params=params, headers=hdrs,
        )

    async def _api_post(
        self,
        endpoint: str,
        body: dict[str, Any] | None = None,
        *,
        auth: bool = True,
        include_base_info: bool = True,
    ) -> dict[str, Any]:
        assert self._client is not None
        url = f"{self.config.base_url}/{endpoint}"
        payload = dict(body or {})
        if include_base_info and "base_info" not in payload:
            payload["base_info"] = BASE_INFO
        return await self._request_json(
            "POST",
            url,
            endpoint=endpoint,
            body=payload,
            headers=self._make_headers(auth=auth),
        )

    # ------------------------------------------------------------------
    # QR Code Login  (matches login-qr.ts)
    # ------------------------------------------------------------------

    def _local_token_list(self) -> list[str]:
        """Return known local bot tokens, newest first, without exposing them."""
        candidates = [self._token, self.config.token]
        state_file = self._get_state_dir() / "account.json"
        if state_file.exists():
            with suppress(Exception):
                persisted = json.loads(state_file.read_text())
                if isinstance(persisted, dict):
                    persisted_data = cast(dict[str, Any], persisted)
                    candidates.append(str(persisted_data.get("token", "") or ""))
        tokens: list[str] = []
        for candidate in candidates:
            token = str(candidate or "").strip()
            if token and token not in tokens:
                tokens.append(token)
            if len(tokens) >= 10:
                break
        return tokens

    async def _fetch_qr_code(self, *, force: bool = False) -> tuple[str, str]:
        """Fetch a QR code without existing credentials when forced."""
        local_tokens = [] if force else self._local_token_list()
        data = await self._api_post(
            "ilink/bot/get_bot_qrcode?bot_type=3",
            {"local_token_list": local_tokens},
            auth=False,
            include_base_info=False,
        )
        if local_tokens and ERRCODE_INVALID_ARGUMENT in {
            self._response_int(data, "ret"),
            self._response_int(data, "errcode"),
        }:
            self.logger.info(
                "WeChat rejected saved login credentials; retrying QR login without them"
            )
            data = await self._api_post(
                "ilink/bot/get_bot_qrcode?bot_type=3",
                {"local_token_list": []},
                auth=False,
                include_base_info=False,
            )
        self._raise_for_api_error("get_bot_qrcode", data)
        qrcode_img_content = cast(str, data.get("qrcode_img_content", ""))
        qrcode_id = cast(str, data.get("qrcode", ""))
        if not qrcode_id:
            raise RuntimeError(f"Failed to get QR code from WeChat API: {data}")
        return qrcode_id, (qrcode_img_content or qrcode_id)

    async def _qr_login(self, *, force: bool = False) -> bool:
        """Perform QR login; forced flows accept only newly confirmed credentials."""
        try:
            refresh_count = 0
            qrcode_id, scan_url = await self._fetch_qr_code(force=force)
            self._print_qr_code(scan_url)
            current_poll_base_url = self.config.base_url
            verify_code = ""

            while self._running:
                try:
                    status_data = await self._api_get_with_base(
                        base_url=current_poll_base_url,
                        endpoint="ilink/bot/get_qrcode_status",
                        params={
                            "qrcode": qrcode_id,
                            **({"verify_code": verify_code} if verify_code else {}),
                        },
                        auth=False,
                    )
                except Exception as e:
                    if self._is_retryable_qr_poll_error(e):
                        await asyncio.sleep(1)
                        continue
                    raise

                if not isinstance(cast(object, status_data), dict):
                    await asyncio.sleep(1)
                    continue

                status = status_data.get("status", "")
                if status == "confirmed":
                    token = status_data.get("bot_token", "")
                    bot_id = status_data.get("ilink_bot_id", "")
                    base_url = status_data.get("baseurl", "")
                    user_id = status_data.get("ilink_user_id", "")
                    if token:
                        self._commit_account(token=token, base_url=base_url)
                        self.logger.info(
                            "login successful! bot_id={} user_id={}",
                            bot_id,
                            user_id,
                        )
                        return True
                    else:
                        self.logger.error("Login confirmed but no bot_token in response")
                        return False
                elif status == "scaned_but_redirect":
                    redirect_host = str(status_data.get("redirect_host", "") or "").strip()
                    if redirect_host:
                        if redirect_host.startswith("http://") or redirect_host.startswith("https://"):
                            redirected_base = redirect_host
                        else:
                            redirected_base = f"https://{redirect_host}"
                        if redirected_base != current_poll_base_url:
                            current_poll_base_url = redirected_base
                elif status == "need_verifycode":
                    prompt = (
                        "The previous code did not match. Enter the number shown in WeChat: "
                        if verify_code
                        else "Enter the number shown in WeChat to continue: "
                    )
                    verify_code = (await asyncio.to_thread(input, prompt)).strip()
                    continue
                elif status == "verify_code_blocked":
                    verify_code = ""
                    refresh_count += 1
                    if refresh_count > MAX_QR_REFRESH_COUNT:
                        self.logger.warning("WeChat verification failed too many times")
                        return False
                    qrcode_id, scan_url = await self._fetch_qr_code(force=force)
                    current_poll_base_url = self.config.base_url
                    self._print_qr_code(scan_url)
                    continue
                elif status == "binded_redirect":
                    if force:
                        self.logger.error(
                            "Forced WeChat login returned an existing binding without new credentials"
                        )
                        return False
                    if self._token or self._load_state():
                        self.logger.info("WeChat account is already connected")
                        return True
                    self.logger.error(
                        "WeChat reports an existing binding but no local credentials were found"
                    )
                    return False
                elif status == "expired":
                    refresh_count += 1
                    if refresh_count > MAX_QR_REFRESH_COUNT:
                        self.logger.warning(
                            "QR code expired too many times ({}/{}), giving up.",
                            refresh_count - 1,
                            MAX_QR_REFRESH_COUNT,
                        )
                        return False
                    qrcode_id, scan_url = await self._fetch_qr_code(force=force)
                    current_poll_base_url = self.config.base_url
                    verify_code = ""
                    self._print_qr_code(scan_url)
                    continue
                # status == "wait" — keep polling

                await asyncio.sleep(1)

        except Exception:
            self.logger.exception("QR login failed")

        return False

    @staticmethod
    def _is_retryable_qr_poll_error(err: Exception) -> bool:
        if isinstance(err, httpx.TimeoutException | httpx.TransportError):
            return True
        if isinstance(err, httpx.HTTPStatusError):
            status_code = (
                err.response.status_code
                if cast(object, err.response) is not None
                else 0
            )
            if WeixinChannel._is_retryable_http_status(status_code):
                return True
        return False

    @property
    def connect_base_url(self) -> str:
        """Base URL currently selected for the interactive connection flow."""
        return self.config.base_url

    def connect_reset_pending_credentials(self) -> None:
        """Clear only in-memory credentials while a replacement QR login is pending."""
        self._token = ""
        self._get_updates_buf = ""

    def connect_load_state(self) -> bool:
        """Load an existing account for the interactive connection flow."""
        return self._load_state()

    def connect_open_client(self) -> None:
        """Open the short-lived HTTP client used by WebUI QR login."""
        self._client = self._new_http_client(httpx.Timeout(60, connect=30))
        self._running = True

    async def connect_fetch_qr_code(self, *, force: bool = False) -> tuple[str, str]:
        return await self._fetch_qr_code(force=force)

    async def connect_poll_qr_code(
        self,
        *,
        base_url: str,
        qrcode_id: str,
        verify_code: str = "",
    ) -> dict[str, Any]:
        return await self._api_get_with_base(
            base_url=base_url,
            endpoint="ilink/bot/get_qrcode_status",
            params={
                "qrcode": qrcode_id,
                **({"verify_code": verify_code} if verify_code else {}),
            },
            auth=False,
        )

    def connect_poll_error_is_retryable(self, err: Exception) -> bool:
        return self._is_retryable_qr_poll_error(err)

    def connect_commit_account(self, *, token: str, base_url: str) -> None:
        self._commit_account(token=token, base_url=base_url)

    async def connect_close_client(self) -> None:
        self._running = False
        if self._client is not None:
            with suppress(Exception):
                await self._client.aclose()
            self._client = None

    @staticmethod
    def _print_qr_code(url: str) -> None:
        try:
            import qrcode as qr_lib  # pyright: ignore[reportMissingModuleSource]

            qr = qr_lib.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            print(f"\nLogin URL: {url}\n")

    # ------------------------------------------------------------------
    # Channel lifecycle
    # ------------------------------------------------------------------

    async def login(self, force: bool = False) -> bool:
        """Perform QR code login and save token. Returns True on success."""
        if force:
            self._token = ""
            self._get_updates_buf = ""
        if self._token or (not force and self._load_state()):
            return True

        # Initialize HTTP client for the login flow
        self._client = self._new_http_client(httpx.Timeout(60, connect=30))
        self._running = True  # Enable polling loop in _qr_login()
        try:
            return await self._qr_login(force=force)
        finally:
            self._running = False
            if self._client:
                await self._client.aclose()
                self._client = None

    async def start(self) -> None:
        self._running = True
        self._next_poll_timeout_s = self.config.poll_timeout
        self._client = self._new_http_client(
            httpx.Timeout(self._next_poll_timeout_s + 10, connect=30)
        )

        if self.config.token:
            if not self._load_state(required_replaced_config_token=self.config.token):
                self._token = self.config.token
                self._replaced_config_token_hash = ""
        elif not self._load_state():
            if not await self._qr_login():
                self.logger.error("login failed. Run 'nanobot channels login weixin' to authenticate.")
                self._running = False
                return

        await self._notify_lifecycle("start")
        self.logger.info("channel starting with long-poll...")

        consecutive_failures = 0
        while self._running:
            try:
                self._poll_task = asyncio.create_task(self._poll_once())
                await self._poll_task
                consecutive_failures = 0
            except asyncio.CancelledError:
                if not self._running:
                    break
                raise
            except httpx.TimeoutException:
                # Normal for long-poll, just retry
                continue
            except WeixinAuthError:
                self._running = False
                raise
            except Exception:
                if not self._running:
                    break
                self.logger.exception("WeChat poll loop error")
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    consecutive_failures = 0
                    await asyncio.sleep(BACKOFF_DELAY_S)
                else:
                    await asyncio.sleep(RETRY_DELAY_S)
            finally:
                self._poll_task = None

    async def stop(self) -> None:
        self._running = False
        self._pending_tool_hints.clear()
        self._stream_buffers.clear()
        self._stream_sent_counts.clear()
        self._stream_live_disabled.clear()
        self._reply_run_ids.clear()
        self._reply_progress_counts.clear()
        poll_task = self._poll_task
        if poll_task and not poll_task.done():
            poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await poll_task
        self._poll_task = None
        for chat_id in list(self._typing_tasks):
            await self._stop_typing(chat_id, clear_remote=False)
        if self._client:
            await self._notify_lifecycle("stop")
            await self._client.aclose()
            self._client = None
        self._save_state()

    async def _notify_lifecycle(self, action: str) -> None:
        """Best-effort upstream online-state reconciliation."""
        if not self._client or not self._token:
            return
        endpoint = f"ilink/bot/msg/notify{action}"
        try:
            data = await self._api_post(endpoint, {})
            self._raise_for_api_error(f"notify{action}", data)
        except Exception as exc:
            self.logger.warning("WeChat notify{} failed (ignored): {}", action, exc)

    # ------------------------------------------------------------------
    # Polling  (matches monitor.ts monitorWeixinProvider)
    # ------------------------------------------------------------------

    def _assert_session_active(self) -> None:
        if self._auth_required:
            raise WeixinAuthError(
                "sendmessage",
                errcode=ERRCODE_STALE_TOKEN,
                errmsg="bot token is stale; run 'nanobot channels login weixin --force'",
            )

    def _reload_replacement_token(self) -> bool:
        """Reload credentials only when QR login persisted a newer token."""
        previous_token = self._token
        loaded = (
            self._load_state(required_replaced_config_token=self.config.token)
            if self.config.token
            else self._load_state()
        )
        if not loaded or self._token == previous_token:
            self._token = previous_token
            return False
        self._auth_required = False
        self.logger.info("Loaded replacement WeChat credentials after stale-token response")
        return True

    async def _poll_once(self) -> None:
        body: dict[str, Any] = {
            "get_updates_buf": self._get_updates_buf,
            "base_info": BASE_INFO,
        }

        data = await self._api_post("ilink/bot/getupdates", body)
        try:
            self._raise_for_api_error("getupdates", data)
        except WeixinAuthError:
            if self._reload_replacement_token():
                await self._notify_lifecycle("start")
                return
            self._auth_required = True
            raise WeixinAuthError(
                "getupdates",
                errcode=ERRCODE_STALE_TOKEN,
                errmsg=(
                    "bot token is stale and no replacement credentials were found; "
                    "run 'nanobot channels login weixin --force'"
                ),
            ) from None

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
        msgs = cast(list[dict[str, Any]], data.get("msgs", []) or [])
        for msg in msgs:
            try:
                await self._process_message(msg)
            except Exception:
                self.logger.exception("Failed to process WeChat message")

    # ------------------------------------------------------------------
    # Inbound message processing  (matches inbound.ts + process-message.ts)
    # ------------------------------------------------------------------

    async def _process_message(self, msg: dict[str, Any]) -> None:
        """Process a single WeixinMessage from getUpdates."""
        # Skip bot's own messages (message_type 2 = BOT)
        if msg.get("message_type") == MESSAGE_TYPE_BOT:
            return

        msg_id = str(msg.get("message_id", "") or msg.get("seq", ""))
        if not msg_id:
            msg_id = f"{msg.get('from_user_id', '')}_{msg.get('create_time_ms', '')}"

        from_user_id = msg.get("from_user_id", "") or ""
        if not from_user_id:
            return

        # Deduplication by message_id
        if msg_id in self._processed_ids:
            return
        self._processed_ids[msg_id] = None
        while len(self._processed_ids) > 1000:
            self._processed_ids.popitem(last=False)

        ctx_token = msg.get("context_token", "")
        if not self.is_allowed(from_user_id):
            if from_user_id.endswith("@chatroom"):
                await self._handle_message(
                    sender_id=from_user_id,
                    chat_id=from_user_id,
                    content="",
                    metadata={"message_id": msg_id},
                    is_dm=False,
                )
                return

            if not ctx_token:
                self.logger.warning(
                    "Access denied for sender {}; cannot send WeChat pairing code without context_token",
                    from_user_id,
                )
                return

            had_ctx_token = from_user_id in self._context_tokens
            previous_ctx_token = self._context_tokens.get(from_user_id, "")
            had_ctx_token_at = from_user_id in self._context_token_at
            previous_ctx_token_at = self._context_token_at.get(from_user_id, 0.0)
            self._context_tokens[from_user_id] = ctx_token
            self._context_token_at[from_user_id] = time.time()
            try:
                await self._handle_message(
                    sender_id=from_user_id,
                    chat_id=from_user_id,
                    content="",
                    metadata={"message_id": msg_id},
                    is_dm=True,
                )
            finally:
                if had_ctx_token:
                    self._context_tokens[from_user_id] = previous_ctx_token
                else:
                    self._context_tokens.pop(from_user_id, None)
                if had_ctx_token_at:
                    self._context_token_at[from_user_id] = previous_ctx_token_at
                else:
                    self._context_token_at.pop(from_user_id, None)
            return

        # Cache context_token (required for all replies — inbound.ts:23-27)
        if ctx_token:
            previous_token = self._context_tokens.get(from_user_id, "")
            self._context_tokens[from_user_id] = ctx_token
            self._context_token_at[from_user_id] = time.time()
            if ctx_token != previous_token:
                self._context_send_counts[ctx_token] = 0
            self._save_state()
            await self._retry_deferred_messages(from_user_id)

        # Parse item_list (WeixinMessage.item_list — types.ts:161)
        item_list = cast(list[dict[str, Any]], msg.get("item_list") or [])
        content_parts: list[str] = []
        media_paths: list[str] = []
        has_top_level_downloadable_media = False

        for item in item_list:
            item_type = item.get("type", 0)

            if item_type == ITEM_TEXT:
                text_item = cast(dict[str, Any], item.get("text_item") or {})
                text = cast(str, text_item.get("text", ""))
                if text:
                    # Handle quoted/ref messages (inbound.ts:86-98)
                    ref = cast(dict[str, Any] | None, item.get("ref_msg"))
                    if ref:
                        ref_item = cast(
                            dict[str, Any] | None,
                            ref.get("message_item"),
                        )
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
                                parts.append(cast(str, ref["title"]))
                            if ref_item:
                                ref_text_item = cast(
                                    dict[str, Any],
                                    ref_item.get("text_item") or {},
                                )
                                ref_text = cast(str, ref_text_item.get("text", ""))
                                if ref_text:
                                    parts.append(ref_text)
                            if parts:
                                content_parts.append(f"[引用: {' | '.join(parts)}]\n{text}")
                            else:
                                content_parts.append(text)
                    else:
                        content_parts.append(text)

            elif item_type == ITEM_IMAGE:
                image_item = cast(dict[str, Any], item.get("image_item") or {})
                if _has_downloadable_media_locator(image_item.get("media")):
                    has_top_level_downloadable_media = True
                file_path = await self._download_media_item(image_item, "image")
                if file_path:
                    content_parts.append(f"[image]\n[Image: source: {file_path}]")
                    media_paths.append(file_path)
                else:
                    content_parts.append("[image]")

            elif item_type == ITEM_VOICE:
                voice_item = cast(dict[str, Any], item.get("voice_item") or {})
                # Voice-to-text provided by WeChat (inbound.ts:101-103)
                voice_text = cast(str, voice_item.get("text", ""))
                if voice_text:
                    content_parts.append(f"[voice] {voice_text}")
                else:
                    if _has_downloadable_media_locator(voice_item.get("media")):
                        has_top_level_downloadable_media = True
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
                file_item = cast(dict[str, Any], item.get("file_item") or {})
                if _has_downloadable_media_locator(file_item.get("media")):
                    has_top_level_downloadable_media = True
                file_name = cast(str, file_item.get("file_name", "unknown"))
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
                video_item = cast(dict[str, Any], item.get("video_item") or {})
                if _has_downloadable_media_locator(video_item.get("media")):
                    has_top_level_downloadable_media = True
                file_path = await self._download_media_item(video_item, "video")
                if file_path:
                    content_parts.append(f"[video]\n[Video: source: {file_path}]")
                    media_paths.append(file_path)
                else:
                    content_parts.append("[video]")

        # Fallback: when no top-level media was downloaded, try quoted/referenced media.
        # This aligns with the reference plugin behavior that checks ref_msg.message_item
        # when main item_list has no downloadable media.
        if not media_paths and not has_top_level_downloadable_media:
            ref_media_item: dict[str, Any] | None = None
            for item in item_list:
                if item.get("type", 0) != ITEM_TEXT:
                    continue
                ref = cast(dict[str, Any], item.get("ref_msg") or {})
                candidate = cast(dict[str, Any], ref.get("message_item") or {})
                if candidate.get("type", 0) in (ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO):
                    ref_media_item = candidate
                    break

            if ref_media_item:
                ref_type = ref_media_item.get("type", 0)
                if ref_type == ITEM_IMAGE:
                    image_item = cast(
                        dict[str, Any],
                        ref_media_item.get("image_item") or {},
                    )
                    file_path = await self._download_media_item(image_item, "image")
                    if file_path:
                        content_parts.append(f"[image]\n[Image: source: {file_path}]")
                        media_paths.append(file_path)
                elif ref_type == ITEM_VOICE:
                    voice_item = cast(
                        dict[str, Any],
                        ref_media_item.get("voice_item") or {},
                    )
                    file_path = await self._download_media_item(voice_item, "voice")
                    if file_path:
                        transcription = await self.transcribe_audio(file_path)
                        if transcription:
                            content_parts.append(f"[voice] {transcription}")
                        else:
                            content_parts.append(f"[voice]\n[Audio: source: {file_path}]")
                        media_paths.append(file_path)
                elif ref_type == ITEM_FILE:
                    file_item = cast(
                        dict[str, Any],
                        ref_media_item.get("file_item") or {},
                    )
                    file_name = cast(str, file_item.get("file_name", "unknown"))
                    file_path = await self._download_media_item(file_item, "file", file_name)
                    if file_path:
                        content_parts.append(f"[file: {file_name}]\n[File: source: {file_path}]")
                        media_paths.append(file_path)
                elif ref_type == ITEM_VIDEO:
                    video_item = cast(
                        dict[str, Any],
                        ref_media_item.get("video_item") or {},
                    )
                    file_path = await self._download_media_item(video_item, "video")
                    if file_path:
                        content_parts.append(f"[video]\n[Video: source: {file_path}]")
                        media_paths.append(file_path)

        content = "\n".join(content_parts)
        if not content:
            return

        self.logger.info(
            "inbound: from={} items={} bodyLen={}",
            from_user_id,
            ",".join(str(i.get("type", 0)) for i in item_list),
            len(content),
        )

        await self._start_typing(from_user_id, ctx_token)

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
        typed_item: dict[str, Any],
        media_type: str,
        filename: str | None = None,
    ) -> str | None:
        """Download + AES-decrypt a media item. Returns local path or None."""
        try:
            media = cast(dict[str, Any], typed_item.get("media") or {})
            encrypt_query_param = str(media.get("encrypt_query_param", "") or "")
            full_url = str(media.get("full_url", "") or "").strip()

            if not encrypt_query_param and not full_url:
                return None

            # Resolve AES key (media-download.ts:43-45, pic-decrypt.ts:40-52)
            # image_item.aeskey is a raw hex string (16 bytes as 32 hex chars).
            # media.aes_key is always base64-encoded.
            # For images, prefer image_item.aeskey; for others use media.aes_key.
            raw_aeskey_hex = cast(str, typed_item.get("aeskey", ""))
            media_aes_key_b64 = cast(str, media.get("aes_key", ""))

            aes_key_b64: str = ""
            if raw_aeskey_hex:
                # Convert hex → raw bytes → base64 (matches media-download.ts:43-44)
                aes_key_b64 = base64.b64encode(bytes.fromhex(raw_aeskey_hex)).decode()
            elif media_aes_key_b64:
                aes_key_b64 = media_aes_key_b64

            # Reference protocol behavior: VOICE/FILE/VIDEO require aes_key;
            # only IMAGE may be downloaded as plain bytes when key is missing.
            if media_type != "image" and not aes_key_b64:
                return None

            assert self._client is not None
            fallback_url = ""
            if encrypt_query_param:
                fallback_url = (
                    f"{self.config.cdn_base_url}/download"
                    f"?encrypted_query_param={quote(encrypt_query_param)}"
                )

            download_candidates: list[tuple[str, str]] = []
            if full_url:
                download_candidates.append(("full_url", full_url))
            if fallback_url and (not full_url or fallback_url != full_url):
                download_candidates.append(("encrypt_query_param", fallback_url))

            data = b""
            for idx, (download_source, cdn_url) in enumerate(download_candidates):
                try:
                    resp = await self._client.get(cdn_url)
                    resp.raise_for_status()
                    data = resp.content
                    break
                except Exception as e:
                    has_more_candidates = idx + 1 < len(download_candidates)
                    should_fallback = (
                        download_source == "full_url"
                        and has_more_candidates
                        and self._is_retryable_media_download_error(e)
                    )
                    if should_fallback:
                        self.logger.warning(
                            "media download failed via full_url, falling back to encrypt_query_param: type={} err={}",
                            media_type,
                            e,
                        )
                        continue
                    raise

            if aes_key_b64 and data:
                data = _decrypt_aes_ecb(data, aes_key_b64)

            if not data:
                return None

            media_dir = get_media_dir("weixin")
            ext = _ext_for_type(media_type)
            if not filename:
                ts = int(time.time())
                hash_seed = encrypt_query_param or full_url
                h = abs(hash(hash_seed)) % 100000
                filename = f"{media_type}_{ts}_{h}{ext}"
            safe_name = os.path.basename(filename)
            file_path = media_dir / safe_name
            file_path.write_bytes(data)
            return str(file_path)

        except Exception:
            self.logger.exception("Error downloading media")
            return None

    # ------------------------------------------------------------------
    # Outbound  (matches send.ts buildTextMessageReq + sendMessageWeixin)
    # ------------------------------------------------------------------

    @staticmethod
    def _delivery_id(msg: OutboundMessage) -> str:
        existing = msg.metadata.get("_weixin_delivery_id")
        if isinstance(existing, str) and existing:
            return existing
        delivery_id = uuid.uuid4().hex
        msg.metadata["_weixin_delivery_id"] = delivery_id
        return delivery_id

    def _delivery_state(self, delivery_id: str) -> _DeliveryState:
        state = self._delivery_states.get(delivery_id)
        if state is None:
            state = _DeliveryState()
            self._delivery_states[delivery_id] = state
            while len(self._delivery_states) > 256:
                self._delivery_states.popitem(last=False)
        else:
            self._delivery_states.move_to_end(delivery_id)
        return state

    @staticmethod
    def _part_client_id(delivery_id: str, part: str) -> str:
        digest = hashlib.sha256(f"{delivery_id}:{part}".encode()).hexdigest()[:20]
        return f"nanobot-{digest}"

    async def _send_text_part(
        self,
        to_user_id: str,
        text: str,
        context_token: str,
        *,
        client_id: str,
        run_id: str = "",
        reserve_budget: int = 0,
    ) -> None:
        token = _SEND_OPTIONS.set(
            _SendOptions(
                client_id=client_id,
                run_id=run_id,
                reserve_budget=reserve_budget,
            )
        )
        try:
            await self._send_text(to_user_id, text, context_token)
        finally:
            _SEND_OPTIONS.reset(token)

    async def _send_media_part(
        self,
        to_user_id: str,
        media_path: str,
        context_token: str,
        *,
        client_id: str,
        file_key: str,
        aes_key_raw: bytes,
        run_id: str = "",
    ) -> None:
        token = _SEND_OPTIONS.set(
            _SendOptions(
                client_id=client_id,
                run_id=run_id,
                file_key=file_key,
                aes_key_raw=aes_key_raw,
            )
        )
        try:
            await self._send_media_file(to_user_id, media_path, context_token)
        finally:
            _SEND_OPTIONS.reset(token)

    def _ensure_context_budget(self, context_token: str, *, reserve: int = 0) -> None:
        used = self._context_send_counts.get(context_token, 0)
        if used + 1 + reserve <= self.config.context_message_budget:
            return
        raise WeixinQuotaError(
            "sendmessage",
            ret=ERRCODE_CONTEXT_RESTRICTED,
            errmsg=(
                "local safety budget exhausted for this context token; "
                "wait for the user to send another message"
            ),
        )

    def _record_context_send(self, context_token: str) -> None:
        if context_token:
            self._context_send_counts[context_token] = (
                self._context_send_counts.get(context_token, 0) + 1
            )

    def _defer_outbound(self, msg: OutboundMessage) -> None:
        delivery_id = self._delivery_id(msg)
        pending = self._deferred_outbound.setdefault(msg.chat_id, OrderedDict())
        pending[delivery_id] = msg
        pending.move_to_end(delivery_id)
        while len(pending) > MAX_DEFERRED_MESSAGES_PER_CHAT:
            dropped_id, _ = pending.popitem(last=False)
            self._delivery_states.pop(dropped_id, None)
            self.logger.warning(
                "Dropped oldest deferred WeChat delivery for {} after queue reached {} items",
                msg.chat_id,
                MAX_DEFERRED_MESSAGES_PER_CHAT,
            )

    async def _retry_deferred_messages(self, chat_id: str) -> None:
        pending = self._deferred_outbound.get(chat_id)
        if not pending:
            return
        self.logger.info(
            "Retrying {} deferred WeChat delivery item(s) after a fresh inbound message",
            len(pending),
        )
        for delivery_id, msg in list(pending.items()):
            try:
                await self.send(msg)
            except WeixinQuotaError:
                break
            except Exception:
                self.logger.exception(
                    "Deferred WeChat delivery {} failed and will not be retried automatically",
                    delivery_id,
                )
                pending.pop(delivery_id, None)
                self._delivery_states.pop(delivery_id, None)
            else:
                pending.pop(delivery_id, None)
                stream_buffer_key = msg.metadata.get("_weixin_stream_buffer_key")
                if isinstance(stream_buffer_key, str):
                    self._clear_stream_state(stream_buffer_key, chat_id=chat_id)
        if not pending:
            self._deferred_outbound.pop(chat_id, None)

    async def _get_typing_ticket(self, user_id: str, context_token: str = "") -> str:
        """Get typing ticket with per-user refresh + failure backoff cache."""
        now = time.time()
        entry = self._typing_tickets.get(user_id)
        if entry and now < float(entry.get("next_fetch_at", 0)):
            return str(entry.get("ticket", "") or "")

        body: dict[str, Any] = {
            "ilink_user_id": user_id,
            "context_token": context_token or None,
            "base_info": BASE_INFO,
        }
        data = await self._api_post("ilink/bot/getconfig", body)
        if self._response_int(data, "ret") == 0 and self._response_int(data, "errcode") == 0:
            ticket = str(data.get("typing_ticket", "") or "")
            self._typing_tickets[user_id] = {
                "ticket": ticket,
                "ever_succeeded": True,
                "next_fetch_at": now + (random.random() * TYPING_TICKET_TTL_S),
                "retry_delay_s": CONFIG_CACHE_INITIAL_RETRY_S,
            }
            return ticket

        prev_delay = float(entry.get("retry_delay_s", CONFIG_CACHE_INITIAL_RETRY_S)) if entry else CONFIG_CACHE_INITIAL_RETRY_S
        next_delay = min(prev_delay * 2, CONFIG_CACHE_MAX_RETRY_S)
        if entry:
            entry["next_fetch_at"] = now + next_delay
            entry["retry_delay_s"] = next_delay
            return str(entry.get("ticket", "") or "")

        self._typing_tickets[user_id] = {
            "ticket": "",
            "ever_succeeded": False,
            "next_fetch_at": now + CONFIG_CACHE_INITIAL_RETRY_S,
            "retry_delay_s": CONFIG_CACHE_INITIAL_RETRY_S,
        }
        return ""

    async def _refresh_context_token_if_stale(
        self, chat_id: str, context_token: str
    ) -> str:
        """Return a fresh context_token if the cached one is too old.

        iLink context_token expires server-side after a short idle period
        (empirically ~90s). Proactively refreshing before sending prevents
        silent message loss on long agent turns or cron pushes.
        """
        if not context_token:
            return context_token

        now = time.time()
        cached_at = self._context_token_at.get(chat_id, 0)
        age = now - cached_at

        if age < CONTEXT_TOKEN_MAX_AGE_S:
            return context_token

        self.logger.debug(
            "WeChat context_token for {} is {:.0f}s old; refreshing via getconfig",
            chat_id,
            age,
        )

        body: dict[str, Any] = {
            "ilink_user_id": chat_id,
            "context_token": context_token,
            "base_info": BASE_INFO,
        }
        try:
            data = await self._api_post("ilink/bot/getconfig", body)
        except Exception as e:
            self.logger.warning("WeChat getconfig failed for {}: {}", chat_id, e)
            return context_token

        if self._response_int(data, "ret") != 0 or self._response_int(data, "errcode") != 0:
            self.logger.warning(
                "WeChat getconfig returned ret={} errcode={} for {}: {}",
                data.get("ret"),
                data.get("errcode"),
                chat_id,
                data.get("errmsg", ""),
            )
            return context_token

        new_token = str(data.get("context_token", "") or "")
        if new_token and new_token != context_token:
            self.logger.info(
                "WeChat context_token refreshed for {} (age {:.0f}s -> fresh)",
                chat_id,
                age,
            )
            self._context_tokens[chat_id] = new_token
            self._context_token_at[chat_id] = now
            self._save_state()
            return new_token

        return context_token

    async def _flush_tool_hints(self, chat_id: str) -> None:
        """Send any buffered tool hints for *chat_id* as a single message.

        Tool hints are coalesced to reduce message count and avoid hitting the
        WeChat iLink rate limit (~7 msgs / 5 min).  Failures are logged but
        not raised so that the main message send is never blocked.
        """
        hints = self._pending_tool_hints.pop(chat_id, None)
        if not hints:
            return

        self.logger.info(
            "Flushing {} buffered tool hint(s) for {}",
            len(hints),
            chat_id,
        )

        ctx_token = self._context_tokens.get(chat_id, "")
        ctx_token = await self._refresh_context_token_if_stale(chat_id, ctx_token)
        if not ctx_token:
            self.logger.warning(
                "Dropped {} buffered tool hint(s) for {}: no context_token",
                len(hints),
                chat_id,
            )
            return

        try:
            await self._send_text(chat_id, "\n\n".join(hints), ctx_token)
        except Exception:
            self.logger.exception(
                "Failed to flush buffered tool hints for {}", chat_id
            )

    async def _send_typing(self, user_id: str, typing_ticket: str, status: int) -> None:
        """Best-effort sendtyping wrapper."""
        if not typing_ticket:
            return
        body: dict[str, Any] = {
            "ilink_user_id": user_id,
            "typing_ticket": typing_ticket,
            "status": status,
            "base_info": BASE_INFO,
        }
        data = await self._api_post("ilink/bot/sendtyping", body)
        self._raise_for_api_error("sendtyping", data)

    async def _typing_keepalive_loop(self, user_id: str, typing_ticket: str, stop_event: asyncio.Event) -> None:
        try:
            while not stop_event.is_set():
                await asyncio.sleep(TYPING_KEEPALIVE_INTERVAL_S)
                if stop_event.is_set():
                    break
                with suppress(Exception):
                    await self._send_typing(user_id, typing_ticket, TYPING_STATUS_TYPING)
        finally:
            pass

    async def _send_structured_progress(
        self,
        msg: OutboundMessage,
        event: ProgressEvent,
        context_token: str,
        delivery_id: str,
        state: _DeliveryState,
    ) -> None:
        if not self.config.reply_progress_messages or not event.tool_events:
            return
        run_id = self._reply_run_ids.setdefault(msg.chat_id, uuid.uuid4().hex)
        sent = self._reply_progress_counts.get(msg.chat_id, 0)
        for tool_event in event.tool_events:
            if sent >= self.config.reply_progress_max_messages:
                break
            phase = str(tool_event.get("phase", "") or "")
            if phase not in {"start", "end", "error"}:
                continue
            call_id = str(tool_event.get("call_id", "") or "")
            tool_name = str(tool_event.get("name", "") or "tool")
            part = f"progress:{phase}:{call_id or tool_name}"
            if part in state.completed_parts:
                continue
            if phase == "start":
                item: dict[str, Any] = {
                    "type": ITEM_TOOL_CALL_START,
                    "create_time_ms": int(time.time() * 1000),
                    "is_completed": False,
                    "tool_call_start_item": {
                        "tool_name": tool_name,
                        "tool_call_id": call_id or None,
                    },
                }
            else:
                item = {
                    "type": ITEM_TOOL_CALL_RESULT,
                    "create_time_ms": int(time.time() * 1000),
                    "is_completed": True,
                    "tool_call_result_item": {
                        "tool_name": tool_name,
                        "tool_call_id": call_id or None,
                        "status": "completed" if phase == "end" else "failed",
                    },
                }
            await self._send_message_item(
                msg.chat_id,
                item,
                context_token,
                client_id=self._part_client_id(delivery_id, part),
                run_id=run_id,
                reserve_budget=1,
            )
            state.completed_parts.add(part)
            sent += 1
        self._reply_progress_counts[msg.chat_id] = sent

    async def _send_message_item(
        self,
        to_user_id: str,
        item: dict[str, Any],
        context_token: str,
        *,
        client_id: str,
        run_id: str = "",
        reserve_budget: int = 0,
    ) -> None:
        self._ensure_context_budget(context_token, reserve=reserve_budget)
        weixin_msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": MESSAGE_TYPE_BOT,
            "message_state": MESSAGE_STATE_FINISH,
            "item_list": [item],
            "context_token": context_token,
        }
        if run_id:
            weixin_msg["run_id"] = run_id
        data = await self._api_post("ilink/bot/sendmessage", {"msg": weixin_msg})
        self._raise_for_api_error("sendmessage", data)
        self._record_context_send(context_token)

    async def send(self, msg: OutboundMessage) -> None:
        if not self._client or not self._token:
            raise RuntimeError("WeChat client not initialized or not authenticated")
        self._assert_session_active()

        delivery_id = self._delivery_id(msg)
        delivery_state = self._delivery_state(delivery_id)
        event = getattr(msg, "event", None)
        progress_event = event if isinstance(event, ProgressEvent) else None
        is_progress = progress_event is not None

        if progress_event and progress_event.tool_events and self.config.reply_progress_messages:
            ctx_token = self._context_tokens.get(msg.chat_id, "")
            if not ctx_token:
                self.logger.warning(
                    "Dropped structured WeChat progress for {}: no context_token",
                    msg.chat_id,
                )
                self._delivery_states.pop(delivery_id, None)
                return
            try:
                await self._send_structured_progress(
                    msg,
                    progress_event,
                    ctx_token,
                    delivery_id,
                    delivery_state,
                )
            except Exception:
                raise
            else:
                self._delivery_states.pop(delivery_id, None)
            return

        # Buffer tool hints to coalesce consecutive ones and avoid burning
        # WeChat iLink's undocumented per-context message quota.
        if progress_event and progress_event.tool_hint:
            if not self.send_tool_hints:
                self._delivery_states.pop(delivery_id, None)
                return
            self._pending_tool_hints.setdefault(msg.chat_id, []).append(msg.content)
            self.logger.debug(
                "Buffered tool hint for {} (count={})",
                msg.chat_id,
                len(self._pending_tool_hints[msg.chat_id]),
            )
            self._delivery_states.pop(delivery_id, None)
            return

        # Reasoning deltas are invisible in WeChat (there is no reasoning
        # UI).  Skip them entirely — do not send and do not flush buffer.
        if progress_event and (progress_event.reasoning_delta or progress_event.reasoning):
            self.logger.debug(
                "Dropped invisible reasoning delta for {}", msg.chat_id
            )
            self._delivery_states.pop(delivery_id, None)
            return

        content = msg.content.strip()

        # Empty progress messages (e.g. after_iteration tool_events) must
        # NOT act as separators — they have no visible content.
        if is_progress and not content and not (msg.media or []):
            self.logger.debug(
                "Skipped empty progress message for {} (no visible content)",
                msg.chat_id,
            )
            self._delivery_states.pop(delivery_id, None)
            return

        typing_ticket = ""
        typing_keepalive_stop = asyncio.Event()
        typing_keepalive_task: asyncio.Task[None] | None = None
        completed = False

        try:
            # Flush buffered legacy hints before visible content. Structured
            # progress messages bypass this text path entirely.
            await self._flush_tool_hints(msg.chat_id)

            if not is_progress:
                await self._stop_typing(msg.chat_id, clear_remote=True)

            ctx_token = self._context_tokens.get(msg.chat_id, "")
            ctx_token = await self._refresh_context_token_if_stale(msg.chat_id, ctx_token)
            if not ctx_token:
                raise WeixinQuotaError(
                    "sendmessage",
                    ret=ERRCODE_CONTEXT_RESTRICTED,
                    errmsg=f"context_token missing for chat_id={msg.chat_id}",
                )

            with suppress(Exception):
                typing_ticket = await self._get_typing_ticket(msg.chat_id, ctx_token)

            if typing_ticket:
                with suppress(Exception):
                    await self._send_typing(msg.chat_id, typing_ticket, TYPING_STATUS_TYPING)
                typing_keepalive_task = asyncio.create_task(
                    self._typing_keepalive_loop(
                        msg.chat_id,
                        typing_ticket,
                        typing_keepalive_stop,
                    )
                )

            run_id = self._reply_run_ids.get(msg.chat_id, "")
            # --- Send media files first (following Telegram channel pattern) ---
            for media_index, media_path in enumerate(msg.media or []):
                media_part = f"media:{media_index}"
                if media_part in delivery_state.completed_parts:
                    continue
                try:
                    aes_key_raw = delivery_state.media_aes_keys.setdefault(
                        media_part,
                        os.urandom(16),
                    )
                    await self._send_media_part(
                        msg.chat_id,
                        media_path,
                        ctx_token,
                        client_id=self._part_client_id(delivery_id, media_part),
                        file_key=hashlib.sha256(
                            f"{delivery_id}:{media_part}:file".encode()
                        ).hexdigest()[:32],
                        aes_key_raw=aes_key_raw,
                        run_id=run_id,
                    )
                    delivery_state.completed_parts.add(media_part)
                except (httpx.TimeoutException, httpx.TransportError):
                    # Network/transport errors: do NOT fall back to text —
                    # the text send would also likely fail, and the outer
                    # except will re-raise so ChannelManager retries properly.
                    self.logger.opt(exception=True).warning(
                        "Network error sending media {}",
                        media_path,
                    )
                    raise
                except httpx.HTTPStatusError as http_err:
                    status_code = (
                        http_err.response.status_code
                        if cast(object, http_err.response) is not None
                        else 0
                    )
                    if self._is_retryable_http_status(status_code):
                        # Server-side / retryable HTTP error — same as network.
                        self.logger.exception(
                            "Server error ({} {}) sending media {}",
                            status_code,
                            http_err.response.reason_phrase
                            if cast(object, http_err.response) is not None
                            else "",
                            media_path,
                        )
                        raise
                    # 4xx client errors are NOT retryable — fall back to text.
                    filename = Path(media_path).name
                    self.logger.exception("Failed to send media {}", media_path)
                    fallback_part = f"{media_part}:fallback"
                    await self._send_text_part(
                        msg.chat_id,
                        f"[Failed to send: {filename}]",
                        ctx_token,
                        client_id=self._part_client_id(delivery_id, fallback_part),
                        run_id=run_id,
                    )
                    delivery_state.completed_parts.add(media_part)
                except WeixinQuotaError:
                    raise
                except WeixinAuthError:
                    self._auth_required = True
                    raise
                except WeixinAPIError:
                    filename = Path(media_path).name
                    self.logger.exception("WeChat rejected media {}", media_path)
                    fallback_part = f"{media_part}:fallback"
                    await self._send_text_part(
                        msg.chat_id,
                        f"[Failed to send: {filename}]",
                        ctx_token,
                        client_id=self._part_client_id(delivery_id, fallback_part),
                        run_id=run_id,
                    )
                    delivery_state.completed_parts.add(media_part)
                except Exception:
                    # Non-network errors (format, file-not-found, etc.):
                    # notify the user via text fallback.
                    filename = Path(media_path).name
                    self.logger.exception("Failed to send media {}", media_path)
                    fallback_part = f"{media_part}:fallback"
                    await self._send_text_part(
                        msg.chat_id,
                        f"[Failed to send: {filename}]",
                        ctx_token,
                        client_id=self._part_client_id(delivery_id, fallback_part),
                        run_id=run_id,
                    )
                    delivery_state.completed_parts.add(media_part)

            # --- Send text content ---
            for chunk_index, chunk in enumerate(split_weixin_message(content)):
                text_part = f"text:{chunk_index}"
                if text_part in delivery_state.completed_parts:
                    continue
                await self._send_text_part(
                    msg.chat_id,
                    chunk,
                    ctx_token,
                    client_id=self._part_client_id(delivery_id, text_part),
                    run_id=run_id,
                )
                delivery_state.completed_parts.add(text_part)
            completed = True
        except WeixinQuotaError:
            if not is_progress:
                self._defer_outbound(msg)
                self.logger.warning(
                    "Deferred WeChat reply for {} until a fresh inbound context is available",
                    msg.chat_id,
                )
            raise
        except WeixinAuthError:
            self._auth_required = True
            raise
        except Exception:
            self.logger.exception("Error sending message")
            raise
        finally:
            if typing_keepalive_task:
                typing_keepalive_stop.set()
                typing_keepalive_task.cancel()
                with suppress(asyncio.CancelledError):
                    await typing_keepalive_task

            if typing_ticket and not is_progress:
                with suppress(Exception):
                    await self._send_typing(msg.chat_id, typing_ticket, TYPING_STATUS_CANCEL)
            if completed:
                self._delivery_states.pop(delivery_id, None)
                if not is_progress:
                    self._reply_run_ids.pop(msg.chat_id, None)
                    self._reply_progress_counts.pop(msg.chat_id, None)

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
        stream_end: bool = False,
        resuming: bool = False,
        merge_next: bool = False,
    ) -> None:
        """Deliver a streamed reply to WeChat.

        WeChat iLink has no native incremental delivery, and the manager
        bypasses :meth:`send` for the ``_streamed`` final answer. So we
        accumulate content deltas and flush the full reply as a single message
        at stream end. Reasoning deltas are invisible in WeChat and are dropped.
        """
        meta = metadata or {}
        if meta.get("_reasoning_delta") or meta.get("_reasoning"):
            return
        is_end = stream_end or bool(meta.get("_stream_end"))
        buffer_key = stream_id or chat_id
        if is_end and merge_next:
            if delta:
                self._stream_buffers.setdefault(buffer_key, []).append(delta)
            return
        # Accumulate intermediate deltas. The stream_end message's own content
        # (present when the manager coalesces deltas into the end message) is
        # folded into `full` below instead of appended here, so a send retry
        # recomputes the same `full` from an unchanged buffer rather than
        # double-counting that delta.
        if delta and not is_end:
            previous_parts = list(self._stream_buffers.get(buffer_key, []))
            self._stream_buffers.setdefault(buffer_key, []).append(delta)
            try:
                await self._flush_stream_block(chat_id, buffer_key)
            except Exception:
                self._stream_buffers[buffer_key] = previous_parts
                raise
        if not is_end:
            return
        full = ("".join(self._stream_buffers.get(buffer_key, [])) + (delta or "")).strip()
        if full:
            # Send before clearing the buffer: if the send raises, the buffer is
            # left intact so ChannelManager._send_with_retry can re-deliver the
            # same stream_end message instead of silently losing the reply.
            await self.send(
                OutboundMessage(
                    channel=self.name,
                    chat_id=chat_id,
                    content=full,
                    metadata={
                        "_weixin_delivery_id": f"stream-{buffer_key}",
                        "_weixin_stream_buffer_key": buffer_key,
                    },
                )
            )
        else:
            await self._flush_tool_hints(chat_id)
        self._clear_stream_state(buffer_key, chat_id=chat_id)

    def _clear_stream_state(self, buffer_key: str, *, chat_id: str = "") -> None:
        self._stream_buffers.pop(buffer_key, None)
        self._stream_sent_counts.pop(buffer_key, None)
        self._stream_live_disabled.discard(buffer_key)
        if chat_id:
            self._reply_run_ids.pop(chat_id, None)
            self._reply_progress_counts.pop(chat_id, None)

    async def _flush_stream_block(self, chat_id: str, buffer_key: str) -> None:
        """Optionally send one bounded live block while reserving the final slot."""
        if not self.config.block_streaming or buffer_key in self._stream_live_disabled:
            return
        sent = self._stream_sent_counts.get(buffer_key, 0)
        if sent >= self.config.block_streaming_max_messages - 1:
            return
        buffered = "".join(self._stream_buffers.get(buffer_key, []))
        if len(buffered) < self.config.block_streaming_min_chars:
            return
        context_token = self._context_tokens.get(chat_id, "")
        context_token = await self._refresh_context_token_if_stale(chat_id, context_token)
        if not context_token:
            return
        chunks = split_weixin_message(
            buffered,
            self.config.block_streaming_min_chars,
        )
        if not chunks:
            return
        block = chunks[0]
        remainder = "\n".join(chunks[1:])
        delivery_id = f"stream-{buffer_key}"
        run_id = self._reply_run_ids.setdefault(chat_id, uuid.uuid4().hex)
        try:
            await self._send_text_part(
                chat_id,
                block,
                context_token,
                client_id=self._part_client_id(delivery_id, f"block:{sent}"),
                run_id=run_id,
                reserve_budget=1,
            )
        except WeixinQuotaError:
            self._stream_live_disabled.add(buffer_key)
            self.logger.warning(
                "Disabled live WeChat blocks for {} after context quota rejection",
                chat_id,
            )
            return
        self._stream_buffers[buffer_key] = [remainder] if remainder else []
        self._stream_sent_counts[buffer_key] = sent + 1

    async def _start_typing(self, chat_id: str, context_token: str = "") -> None:
        """Start typing indicator immediately when a message is received."""
        if not self._client or not self._token or not chat_id:
            return
        await self._stop_typing(chat_id, clear_remote=False)
        try:
            ticket = await self._get_typing_ticket(chat_id, context_token)
            if not ticket:
                return
            await self._send_typing(chat_id, ticket, TYPING_STATUS_TYPING)
        except Exception as e:
            self.logger.debug("typing indicator start failed for {}: {}", chat_id, e)
            return

        stop_event = asyncio.Event()

        async def keepalive() -> None:
            try:
                while not stop_event.is_set():
                    await asyncio.sleep(TYPING_KEEPALIVE_INTERVAL_S)
                    if stop_event.is_set():
                        break
                    with suppress(Exception):
                        await self._send_typing(chat_id, ticket, TYPING_STATUS_TYPING)
            finally:
                pass

        task = asyncio.create_task(keepalive())
        task._typing_stop_event = stop_event  # type: ignore[attr-defined]
        self._typing_tasks[chat_id] = task

    async def _stop_typing(self, chat_id: str, *, clear_remote: bool) -> None:
        """Stop typing indicator for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            stop_event = getattr(task, "_typing_stop_event", None)
            if stop_event:
                stop_event.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if not clear_remote:
            return
        entry = self._typing_tickets.get(chat_id)
        ticket = str(entry.get("ticket", "") or "") if isinstance(entry, dict) else ""
        if not ticket:
            return
        try:
            await self._send_typing(chat_id, ticket, TYPING_STATUS_CANCEL)
        except Exception as e:
            self.logger.debug("typing clear failed for {}: {}", chat_id, e)

    async def _send_text(
        self,
        to_user_id: str,
        text: str,
        context_token: str,
        *,
        client_id: str | None = None,
        run_id: str = "",
    ) -> None:
        """Send a text message matching the exact protocol from send.ts."""
        options = _SEND_OPTIONS.get()
        self._ensure_context_budget(
            context_token,
            reserve=options.reserve_budget if options else 0,
        )
        client_id = client_id or (options.client_id if options else None)
        client_id = client_id or f"nanobot-{uuid.uuid4().hex[:12]}"
        run_id = run_id or (options.run_id if options else "")

        item_list: list[dict[str, Any]] = []
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
        if run_id:
            weixin_msg["run_id"] = run_id

        body: dict[str, Any] = {
            "msg": weixin_msg,
            "base_info": BASE_INFO,
        }

        data = await self._api_post("ilink/bot/sendmessage", body)
        self._raise_for_api_error("sendmessage", data)
        self._record_context_send(context_token)

    async def _send_media_file(
        self,
        to_user_id: str,
        media_path: str,
        context_token: str,
        *,
        client_id: str | None = None,
        file_key: str | None = None,
        aes_key_raw: bytes | None = None,
        run_id: str = "",
    ) -> None:
        """Upload a local file to WeChat CDN and send it as a media message.

        Follows the exact protocol from ``@tencent-weixin/openclaw-weixin`` v1.0.3:
        1. Generate a random 16-byte AES key (client-side).
        2. Call ``getuploadurl`` with file metadata + hex-encoded AES key.
        3. AES-128-ECB encrypt the file and POST to CDN (``{cdnBaseUrl}/upload``).
        4. Read ``x-encrypted-param`` header from CDN response as the download param.
        5. Send a ``sendmessage`` with the appropriate media item referencing the upload.
        """
        p = Path(media_path)
        if not p.is_file():
            raise FileNotFoundError(f"Media file not found: {media_path}")
        self._ensure_context_budget(context_token)

        raw_data = p.read_bytes()
        raw_size = len(raw_data)
        raw_md5 = hashlib.md5(raw_data).hexdigest()

        # Determine upload media type from extension
        ext = p.suffix.lower()
        if ext in _IMAGE_EXTS:
            upload_type = UPLOAD_MEDIA_IMAGE
            item_type = ITEM_IMAGE
            item_key = "image_item"
        elif ext in _VIDEO_EXTS:
            upload_type = UPLOAD_MEDIA_VIDEO
            item_type = ITEM_VIDEO
            item_key = "video_item"
        elif ext in _VOICE_EXTS:
            upload_type = UPLOAD_MEDIA_VOICE
            item_type = ITEM_VOICE
            item_key = "voice_item"
        else:
            upload_type = UPLOAD_MEDIA_FILE
            item_type = ITEM_FILE
            item_key = "file_item"

        # Generate client-side AES-128 key (16 random bytes)
        options = _SEND_OPTIONS.get()
        aes_key_raw = aes_key_raw or (options.aes_key_raw if options else None)
        aes_key_raw = aes_key_raw or os.urandom(16)
        aes_key_hex = aes_key_raw.hex()

        # Compute encrypted size: PKCS7 padding to 16-byte boundary
        # Matches aesEcbPaddedSize: Math.ceil((size + 1) / 16) * 16
        padded_size = ((raw_size + 1 + 15) // 16) * 16

        # Step 1: Get upload URL from server (prefer upload_full_url, fallback to upload_param)
        file_key = file_key or (options.file_key if options else None)
        file_key = file_key or os.urandom(16).hex()
        upload_body: dict[str, Any] = {
            "filekey": file_key,
            "media_type": upload_type,
            "to_user_id": to_user_id,
            "rawsize": raw_size,
            "rawfilemd5": raw_md5,
            "filesize": padded_size,
            "no_need_thumb": True,
            "aeskey": aes_key_hex,
        }

        assert self._client is not None
        upload_resp = await self._api_post("ilink/bot/getuploadurl", upload_body)
        self._raise_for_api_error("getuploadurl", upload_resp)

        upload_full_url = str(upload_resp.get("upload_full_url", "") or "").strip()
        upload_param = str(upload_resp.get("upload_param", "") or "")
        if not upload_full_url and not upload_param:
            raise RuntimeError(
                "getuploadurl returned no upload URL "
                f"(need upload_full_url or upload_param): {upload_resp}"
            )

        # Step 2: AES-128-ECB encrypt and POST to CDN
        aes_key_b64 = base64.b64encode(aes_key_raw).decode()
        encrypted_data = _encrypt_aes_ecb(raw_data, aes_key_b64)

        if upload_full_url:
            cdn_upload_url = upload_full_url
        else:
            cdn_upload_url = (
                f"{self.config.cdn_base_url}/upload"
                f"?encrypted_query_param={quote(upload_param)}"
                f"&filekey={quote(file_key)}"
            )

        cdn_resp = await self._client.post(
            cdn_upload_url,
            content=encrypted_data,
            headers={"Content-Type": "application/octet-stream"},
        )
        cdn_resp.raise_for_status()

        # The download encrypted_query_param comes from CDN response header
        download_param = cdn_resp.headers.get("x-encrypted-param", "")
        if not download_param:
            raise RuntimeError(
                "CDN upload response missing x-encrypted-param header; "
                f"status={cdn_resp.status_code} headers={dict(cdn_resp.headers)}"
            )

        # Step 3: Send message with the media item
        # aes_key for CDNMedia is the hex key encoded as base64
        # (matches: Buffer.from(uploaded.aeskey).toString("base64"))
        cdn_aes_key_b64 = base64.b64encode(aes_key_hex.encode()).decode()

        media_item: dict[str, Any] = {
            "media": {
                "encrypt_query_param": download_param,
                "aes_key": cdn_aes_key_b64,
                "encrypt_type": 1,
            },
        }

        if item_type == ITEM_IMAGE:
            media_item["mid_size"] = padded_size
        elif item_type == ITEM_VIDEO:
            media_item["video_size"] = padded_size
        elif item_type == ITEM_FILE:
            media_item["file_name"] = p.name
            media_item["len"] = str(raw_size)

        # Send each media item as its own message (matching reference plugin)
        client_id = client_id or (options.client_id if options else None)
        client_id = client_id or f"nanobot-{uuid.uuid4().hex[:12]}"
        run_id = run_id or (options.run_id if options else "")
        item_list: list[dict[str, Any]] = [
            {"type": item_type, item_key: media_item}
        ]

        weixin_msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": MESSAGE_TYPE_BOT,
            "message_state": MESSAGE_STATE_FINISH,
            "item_list": item_list,
        }
        if context_token:
            weixin_msg["context_token"] = context_token
        if run_id:
            weixin_msg["run_id"] = run_id

        body: dict[str, Any] = {
            "msg": weixin_msg,
            "base_info": BASE_INFO,
        }

        self._ensure_context_budget(context_token)
        data = await self._api_post("ilink/bot/sendmessage", body)
        self._raise_for_api_error("sendmessage", data)
        self._record_context_send(context_token)


# ---------------------------------------------------------------------------
# AES-128-ECB encryption / decryption  (matches pic-decrypt.ts / aes-ecb.ts)
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


def _encrypt_aes_ecb(data: bytes, aes_key_b64: str) -> bytes:
    """Encrypt data with AES-128-ECB and PKCS7 padding for CDN upload."""
    try:
        key = _parse_aes_key(aes_key_b64)
    except Exception as e:
        logger.warning("Failed to parse AES key for encryption, sending raw: {}", e)
        return data

    # PKCS7 padding
    pad_len = 16 - len(data) % 16
    padded = data + bytes([pad_len] * pad_len)

    with suppress(ImportError):
        from Crypto.Cipher import AES

        aes_module = cast(Any, AES)
        cipher = aes_module.new(key, aes_module.MODE_ECB)
        return cipher.encrypt(padded)

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cipher_obj = Cipher(algorithms.AES(key), modes.ECB())
        encryptor = cipher_obj.encryptor()
        return encryptor.update(padded) + encryptor.finalize()
    except ImportError:
        logger.warning(
            "Cannot encrypt media. Run `nanobot plugins enable weixin` "
            "to install WeChat support."
        )
        return data


def _decrypt_aes_ecb(data: bytes, aes_key_b64: str) -> bytes:
    """Decrypt AES-128-ECB media data.

    ``aes_key_b64`` is always base64-encoded (caller converts hex keys first).
    """
    try:
        key = _parse_aes_key(aes_key_b64)
    except Exception as e:
        logger.warning("Failed to parse AES key, returning raw data: {}", e)
        return data

    decrypted: bytes | None = None

    with suppress(ImportError):
        from Crypto.Cipher import AES

        aes_module = cast(Any, AES)
        cipher = aes_module.new(key, aes_module.MODE_ECB)
        decrypted = cipher.decrypt(data)

    if decrypted is None:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

            cipher_obj = Cipher(algorithms.AES(key), modes.ECB())
            decryptor = cipher_obj.decryptor()
            decrypted = decryptor.update(data) + decryptor.finalize()
        except ImportError:
            logger.warning(
                "Cannot decrypt media. Run `nanobot plugins enable weixin` "
                "to install WeChat support."
            )
            return data

    return _pkcs7_unpad_safe(decrypted)


def _pkcs7_unpad_safe(data: bytes, block_size: int = 16) -> bytes:
    """Safely remove PKCS7 padding when valid; otherwise return original bytes."""
    if not data:
        return data
    if len(data) % block_size != 0:
        return data
    pad_len = data[-1]
    if pad_len < 1 or pad_len > block_size:
        return data
    if data[-pad_len:] != bytes([pad_len]) * pad_len:
        return data
    return data[:-pad_len]


def _ext_for_type(media_type: str) -> str:
    return {
        "image": ".jpg",
        "voice": ".silk",
        "video": ".mp4",
        "file": "",
    }.get(media_type, "")
