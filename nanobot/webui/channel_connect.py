"""Short-lived WebUI channel connection sessions."""

from __future__ import annotations

import json
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import httpx

from nanobot.channels import feishu
from nanobot.channels._feishu_instances import DEFAULT_INSTANCE_ID, validate_instance_id
from nanobot.config.loader import load_raw_config


class ChannelConnectError(Exception):
    """User-facing channel connect failure."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(slots=True)
class FeishuConnectSession:
    id: str
    instance_id: str
    instance_name: str
    device_code: str
    qr_url: str
    domain: str
    interval: int
    expire_in: int
    created_wall: float
    deadline: float
    last_error: str | None = None


class FeishuConnectStore:
    """In-memory Feishu/Lark QR connection state.

    Sessions intentionally live only in the gateway process and expire quickly.
    The app secret is never returned to the browser; it is saved directly to
    config when Feishu/Lark completes authorization.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, FeishuConnectSession] = {}

    def start(
        self,
        *,
        domain: str = "feishu",
        instance_id: str = DEFAULT_INSTANCE_ID,
        mode: str = "replace",
    ) -> dict[str, Any]:
        domain = _normalize_domain(domain)
        instance_id = _resolve_instance_id(instance_id, mode)
        self._cleanup()
        try:
            feishu._init_registration(domain)
            begin = feishu._begin_registration(domain)
        except (RuntimeError, OSError, json.JSONDecodeError, httpx.HTTPError) as exc:
            raise ChannelConnectError(
                f"Unable to start Feishu/Lark connection: {exc}",
                status=502,
            ) from exc

        session_id = secrets.token_urlsafe(18)
        now_wall = time.time()
        now = time.monotonic()
        expire_in = int(begin["expire_in"])
        interval = max(2, int(begin["interval"]))
        session = FeishuConnectSession(
            id=session_id,
            instance_id=instance_id,
            instance_name=_default_instance_name(instance_id),
            device_code=str(begin["device_code"]),
            qr_url=str(begin["qr_url"]),
            domain=domain,
            interval=interval,
            expire_in=expire_in,
            created_wall=now_wall,
            deadline=now + expire_in,
        )
        self._sessions[session_id] = session
        return _start_payload(session)

    def poll(self, session_id: str) -> dict[str, Any]:
        self._cleanup()
        session = self._sessions.get(session_id)
        if session is None:
            return {
                "session_id": session_id,
                "status": "expired",
                "message": "This Feishu connection has expired. Start again.",
            }

        if time.monotonic() >= session.deadline:
            self._sessions.pop(session_id, None)
            return {
                "session_id": session_id,
                "status": "expired",
                "message": "This Feishu connection has expired. Start again.",
            }

        try:
            result = feishu.poll_registration_once(
                device_code=session.device_code,
                domain=session.domain,
            )
        except (RuntimeError, OSError, json.JSONDecodeError, httpx.HTTPError) as exc:
            session.last_error = str(exc)
            return _pending_payload(session)

        session.domain = str(result.get("domain") or session.domain)
        status = result.get("status")
        if status == "succeeded":
            feishu.save_registration_result(
                result,
                instance_id=session.instance_id,
                name=session.instance_name,
            )
            self._sessions.pop(session_id, None)
            return {
                "session_id": session_id,
                "instance_id": session.instance_id,
                "status": "succeeded",
                "message": "Feishu is connected.",
                "domain": session.domain,
                "app_id": result.get("app_id"),
            }

        if status == "failed":
            self._sessions.pop(session_id, None)
            return {
                "session_id": session_id,
                "instance_id": session.instance_id,
                "status": "failed",
                "message": "Authorization was cancelled or expired.",
                "domain": session.domain,
            }

        return _pending_payload(session)

    def cancel(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.pop(session_id, None)
        return {
            "session_id": session_id,
            "instance_id": session.instance_id if session else DEFAULT_INSTANCE_ID,
            "status": "cancelled",
            "message": "Feishu connection cancelled.",
        }

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [session_id for session_id, session in self._sessions.items() if now >= session.deadline]
        for session_id in expired:
            self._sessions.pop(session_id, None)


def _normalize_domain(domain: str) -> str:
    normalized = domain.strip().lower()
    return normalized if normalized in {"feishu", "lark"} else "feishu"


def _resolve_instance_id(instance_id: str, mode: str) -> str:
    if mode == "create":
        return f"assistant-{secrets.token_hex(3)}"
    try:
        return validate_instance_id(instance_id or DEFAULT_INSTANCE_ID)
    except ValueError as exc:
        raise ChannelConnectError(str(exc), status=400) from exc


def _default_instance_name(instance_id: str) -> str:
    return "nanobot" if instance_id == DEFAULT_INSTANCE_ID else f"nanobot {instance_id}"


def _start_payload(session: FeishuConnectSession) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "instance_id": session.instance_id,
        "status": "pending",
        "qr_url": session.qr_url,
        "domain": session.domain,
        "interval_ms": session.interval * 1000,
        "expires_at_ms": int((session.created_wall + session.expire_in) * 1000),
        "message": "Scan with Feishu or Lark to connect.",
    }


def _pending_payload(session: FeishuConnectSession) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "instance_id": session.instance_id,
        "status": "pending",
        "domain": session.domain,
        "interval_ms": session.interval * 1000,
        "expires_at_ms": int((session.created_wall + session.expire_in) * 1000),
        "message": "Waiting for authorization.",
    }


@dataclass(slots=True)
class WeixinConnectSession:
    id: str
    qrcode_id: str
    qr_url: str
    channel: Any
    current_poll_base_url: str
    refresh_count: int
    created_wall: float
    deadline: float
    last_error: str | None = None


class WeixinConnectStore:
    """In-memory WeChat QR login sessions for the WebUI.

    WeChat login writes local account state only after scan confirmation.  A
    cancelled or expired browser flow leaves any existing account state intact.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, WeixinConnectSession] = {}

    async def start(self, *, force: bool = False) -> dict[str, Any]:
        await self._cleanup()

        channel = self._build_channel()
        if force:
            # Start a fresh login flow without touching the currently working
            # account.  A confirmed scan replaces it via _save_state;
            # cancellation or expiry must leave the old account usable.
            channel._token = ""
            channel._get_updates_buf = ""
        elif channel._load_state():
            return {
                "session_id": "",
                "status": "succeeded",
                "message": "WeChat is already connected.",
                "interval_ms": 2000,
            }

        channel._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=30),
            follow_redirects=True,
        )
        channel._running = True
        try:
            qrcode_id, qr_url = await channel._fetch_qr_code()
        except Exception as exc:
            await self._close_channel(channel)
            raise ChannelConnectError(f"Unable to start WeChat QR login: {exc}", status=502) from exc

        session_id = secrets.token_urlsafe(18)
        now_wall = time.time()
        self._sessions[session_id] = WeixinConnectSession(
            id=session_id,
            qrcode_id=qrcode_id,
            qr_url=qr_url,
            channel=channel,
            current_poll_base_url=channel.config.base_url,
            refresh_count=0,
            created_wall=now_wall,
            deadline=time.monotonic() + 600,
        )
        return self._start_payload(self._sessions[session_id])

    async def poll(self, session_id: str) -> dict[str, Any]:
        await self._cleanup()
        session = self._sessions.get(session_id)
        if session is None:
            return {
                "session_id": session_id,
                "status": "expired",
                "message": "This WeChat login has expired. Start again.",
            }

        try:
            status_data = await session.channel._api_get_with_base(
                base_url=session.current_poll_base_url,
                endpoint="ilink/bot/get_qrcode_status",
                params={"qrcode": session.qrcode_id},
                auth=False,
            )
        except Exception as exc:
            if session.channel._is_retryable_qr_poll_error(exc):
                session.last_error = str(exc)
                return self._pending_payload(session)
            self._sessions.pop(session_id, None)
            await self._close_channel(session.channel)
            return {
                "session_id": session_id,
                "status": "failed",
                "message": f"WeChat QR login failed: {exc}",
            }

        if not isinstance(status_data, dict):
            return self._pending_payload(session)

        status = status_data.get("status", "")
        if status == "confirmed":
            token = str(status_data.get("bot_token", "") or "")
            if not token:
                self._sessions.pop(session_id, None)
                await self._close_channel(session.channel)
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "message": "WeChat confirmed the scan but returned no token.",
                }
            base_url = str(status_data.get("baseurl", "") or "")
            session.channel._token = token
            if base_url:
                session.channel.config.base_url = base_url
            session.channel._save_state()
            self._sessions.pop(session_id, None)
            await self._close_channel(session.channel)
            return {
                "session_id": session_id,
                "status": "succeeded",
                "message": "WeChat is connected.",
                "account": str(status_data.get("ilink_user_id", "") or ""),
            }

        if status == "scaned_but_redirect":
            redirect_host = str(status_data.get("redirect_host", "") or "").strip()
            if redirect_host:
                redirected_base = (
                    redirect_host
                    if redirect_host.startswith(("http://", "https://"))
                    else f"https://{redirect_host}"
                )
                session.current_poll_base_url = redirected_base
            return self._pending_payload(session)

        if status == "expired":
            from nanobot.channels.weixin import MAX_QR_REFRESH_COUNT

            session.refresh_count += 1
            if session.refresh_count > MAX_QR_REFRESH_COUNT:
                self._sessions.pop(session_id, None)
                await self._close_channel(session.channel)
                return {
                    "session_id": session_id,
                    "status": "expired",
                    "message": "This WeChat QR code expired. Start again.",
                }
            try:
                session.qrcode_id, session.qr_url = await session.channel._fetch_qr_code()
            except Exception as exc:
                self._sessions.pop(session_id, None)
                await self._close_channel(session.channel)
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "message": f"Could not refresh WeChat QR code: {exc}",
                }
            session.current_poll_base_url = session.channel.config.base_url
            return self._pending_payload(session)

        return self._pending_payload(session)

    async def cancel(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await self._close_channel(session.channel)
        return {
            "session_id": session_id,
            "status": "cancelled",
            "message": "WeChat login cancelled.",
        }

    async def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now >= session.deadline
        ]
        for session_id in expired:
            session = self._sessions.pop(session_id, None)
            if session is not None:
                await self._close_channel(session.channel)

    @staticmethod
    def _build_channel() -> Any:
        from nanobot.bus.queue import MessageBus
        from nanobot.channels.weixin import WeixinChannel

        section = getattr(load_raw_config().channels, "weixin", None)
        if hasattr(section, "model_dump"):
            config = section.model_dump(mode="json", by_alias=True)
        elif isinstance(section, dict):
            config = dict(section)
        else:
            config = {}
        return WeixinChannel(config, MessageBus())

    @staticmethod
    async def _close_channel(channel: Any) -> None:
        channel._running = False
        client = getattr(channel, "_client", None)
        if client is not None:
            with suppress(Exception):
                await client.aclose()
            channel._client = None

    @staticmethod
    def _start_payload(session: WeixinConnectSession) -> dict[str, Any]:
        return {
            "session_id": session.id,
            "status": "pending",
            "qr_url": session.qr_url,
            "interval_ms": 2000,
            "expires_at_ms": int((session.created_wall + 600) * 1000),
            "message": "Scan with WeChat to connect.",
        }

    @staticmethod
    def _pending_payload(session: WeixinConnectSession) -> dict[str, Any]:
        return {
            "session_id": session.id,
            "status": "pending",
            "qr_url": session.qr_url,
            "interval_ms": 2000,
            "expires_at_ms": int((session.created_wall + 600) * 1000),
            "message": "Waiting for WeChat scan.",
        }
