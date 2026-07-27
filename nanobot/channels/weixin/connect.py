"""WeChat-owned interactive connection flow."""

from __future__ import annotations

import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import httpx

from nanobot.channels.connect import ChannelConnectError, QueryParams, query_first
from nanobot.config.loader import load_config


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
    """In-memory WeChat QR login sessions for the WebUI."""

    def __init__(self) -> None:
        self._sessions: dict[str, WeixinConnectSession] = {}

    async def handle(self, action: str, query: QueryParams) -> dict[str, Any]:
        """Handle one generic settings connection action."""
        if action == "start":
            force = (query_first(query, "force") or "").strip().lower() in {
                "1",
                "true",
                "yes",
            }
            return await self.start(force=force)

        session_id = (query_first(query, "session_id") or "").strip()
        if not session_id:
            raise ChannelConnectError("missing WeChat connect session")
        if action == "poll":
            return await self.poll(session_id)
        if action == "cancel":
            return await self.cancel(session_id)
        raise ChannelConnectError(f"unsupported WeChat connect action: {action}", status=404)

    async def start(self, *, force: bool = False) -> dict[str, Any]:
        await self._cleanup()

        channel = self._build_channel()
        if force:
            # Preserve the working account until a replacement scan succeeds.
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
            raise ChannelConnectError(
                f"Unable to start WeChat QR login: {exc}",
                status=502,
            ) from exc

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
            if self._sessions.get(session_id) is not session:
                return {
                    "session_id": session_id,
                    "status": "cancelled",
                    "message": "WeChat login cancelled.",
                }
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
                session.current_poll_base_url = (
                    redirect_host
                    if redirect_host.startswith(("http://", "https://"))
                    else f"https://{redirect_host}"
                )
            return self._pending_payload(session)

        if status == "expired":
            from nanobot.channels.weixin.runtime import MAX_QR_REFRESH_COUNT

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
        from nanobot.channels.weixin.runtime import WeixinChannel

        section = getattr(load_config().channels, "weixin", None)
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


__all__ = ["WeixinConnectStore"]
