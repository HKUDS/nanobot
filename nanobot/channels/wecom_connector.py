"""SillyMD server connector for the WeChat Work channel.

Provides WebSocket message reception and HTTP API calls to the SillyMD bridge
server.  Extracted and simplified from sillymd-openclaw-wechat-plugin's
``server_connector.py``.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Callable

from loguru import logger

try:
    import websockets
    import websockets.exceptions

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    websockets = None  # type: ignore[assignment]

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    aiohttp = None  # type: ignore[assignment]


class SillyMDConnector:
    """WebSocket + HTTP connector to SillyMD bridge server."""

    def __init__(self, api_key: str, base_url: str = "https://websocket.sillymd.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

        ws_protocol = "wss" if base_url.startswith("https") else "ws"
        self.ws_url = f"{ws_protocol}://{base_url.split('://')[1]}/ws"

        self.tenant_id: str | None = None
        self.device_id: str | None = None
        self.corp_id: str = ""

        # WebSocket state
        self._ws: Any = None
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10

        # HTTP state
        self._http_session: aiohttp.ClientSession | None = None

        # Message handlers
        self._handlers: list[Callable] = []

    # ── HTTP helpers ────────────────────────────────────────────────────

    async def _get_http(self) -> aiohttp.ClientSession:
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp is required: pip install aiohttp")
        if self._http_session is None or self._http_session.closed:
            headers = {"X-API-Key": self.api_key}
            timeout = aiohttp.ClientTimeout(total=30)
            self._http_session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self._http_session

    async def fetch_tenant_info(self) -> dict | None:
        """Fetch tenant info (incl. WeChat config) from SillyMD backend."""
        try:
            session = await self._get_http()
            async with session.get(f"{self.base_url}/api/v1/tenants/me") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    wechat = {
                        "token": data.get("wechat_token"),
                        "encoding_aes_key": data.get("wechat_aes_key"),
                        "corp_id": data.get("wechat_corp_id"),
                        "corp_secret": data.get("wechat_corp_secret"),
                    }
                    if data.get("id"):
                        self.tenant_id = str(data["id"])
                    return {"id": data.get("id"), "name": data.get("name"), "wechat": wechat}
                else:
                    text = await resp.text()
                    logger.error("Fetch tenant info failed: {} - {}", resp.status, text[:200])
                    return None
        except Exception as e:
            logger.error("Fetch tenant info error: {}", e)
            return None

    async def send_text(self, message: str, touser: str = "@all") -> dict:
        """Send a text reply via SillyMD HTTP API."""
        try:
            session = await self._get_http()
            payload = {
                "msg_type": "text",
                "message": message,
                "corp_id": self.corp_id,
                "touser": touser,
            }
            async with session.post(f"{self.base_url}/api/v1/wechat/send", json=payload) as resp:
                result = await resp.json()
                if resp.status != 200:
                    logger.error("Send text failed: {}", result)
                return result
        except Exception as e:
            logger.error("Send text error: {}", e)
            return {"status": "error", "message": str(e)}

    async def send_media(
        self,
        media_type: str,
        file_path: str,
        message: str = "",
        touser: str = "@all",
        title: str = "",
        description: str = "",
    ) -> dict:
        """Send a media message (image/video/file) via multipart upload."""
        try:
            session = await self._get_http()
            form = aiohttp.FormData()
            form.add_field("msg_type", media_type)
            form.add_field("message", message)
            form.add_field("corp_id", self.corp_id)
            form.add_field("touser", touser)
            if title:
                form.add_field("title", title)
            if description:
                form.add_field("description", description)

            file_name = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                file_content = f.read()

            ct = "image/jpeg" if media_type == "image" else "application/octet-stream"
            form.add_field("media_file", file_content, filename=file_name, content_type=ct)

            headers = {"X-API-Key": self.api_key}
            async with session.post(
                f"{self.base_url}/api/v1/wechat/send", data=form, headers=headers
            ) as resp:
                result = await resp.json()
                if resp.status != 200:
                    logger.error("Send media failed: {}", result)
                return result
        except Exception as e:
            logger.error("Send media error: {}", e)
            return {"status": "error", "message": str(e)}

    async def download_media(self, media_id: str) -> bytes | None:
        """Download a media file from WeChat via SillyMD."""
        try:
            session = await self._get_http()
            async with session.get(f"{self.base_url}/api/v1/wechat/media/{media_id}") as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.error("Download media failed: {}", await resp.text())
                return None
        except Exception as e:
            logger.error("Download media error: {}", e)
            return None

    # ── WebSocket ───────────────────────────────────────────────────────

    def add_handler(self, handler: Callable) -> None:
        self._handlers.append(handler)

    async def _dispatch(self, message: dict) -> None:
        for handler in self._handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.error("Handler error: {}", e)

    async def connect(self) -> bool:
        """Connect to SillyMD WebSocket and bind device."""
        if not WEBSOCKETS_AVAILABLE:
            logger.error("websockets is required: pip install websockets")
            return False

        uri = f"{self.ws_url}?token={self.api_key}"
        try:
            logger.info("Connecting to SillyMD WebSocket: {}", self.ws_url)
            self._ws = await websockets.connect(uri, ping_interval=20, ping_timeout=90, close_timeout=10)
            self._connected = True
            self._reconnect_attempts = 0

            # Read initial welcome message
            try:
                await self._ws.recv()
            except Exception:
                pass

            # Bind device
            bind_msg = {"type": "bind", "device_name": "nanobot", "tenant_id": self.tenant_id or ""}
            await self._ws.send(json.dumps(bind_msg))
            resp = json.loads(await self._ws.recv())
            if resp.get("type") == "bound":
                self.device_id = resp.get("device_id", "nanobot")
                if not self.tenant_id and "tenant_id" in resp:
                    self.tenant_id = resp["tenant_id"]
                logger.info("SillyMD device bound: {}", self.device_id)
            else:
                logger.warning("Unexpected bind response: {}", resp)

            return True
        except Exception as e:
            logger.error("WebSocket connect failed: {}", e)
            self._connected = False
            return False

    async def listen(self) -> None:
        """Listen for WebSocket messages until disconnected."""
        if not self._ws or not self._connected:
            return
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                    await self._dispatch(data)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON WebSocket message received")
                except Exception as e:
                    logger.error("Message processing error: {}", e)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("SillyMD WebSocket closed")
            self._connected = False
        except Exception as e:
            logger.error("WebSocket listen error: {}", e)
            self._connected = False

    async def run_forever(self) -> None:
        """Connect, listen, and auto-reconnect."""
        while True:
            try:
                if not self._connected:
                    ok = await self.connect()
                    if not ok:
                        await asyncio.sleep(5)
                        continue
                await self.listen()
                # Disconnected — attempt reconnect
                if self._reconnect_attempts >= self._max_reconnect_attempts:
                    logger.error("Max reconnect attempts reached ({})", self._max_reconnect_attempts)
                    self._reconnect_attempts = 0
                self._reconnect_attempts += 1
                wait = min(2 ** self._reconnect_attempts, 30)
                logger.info("Reconnecting in {}s (attempt {})...", wait, self._reconnect_attempts)
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("WebSocket loop error: {}", e)
                self._connected = False
                await asyncio.sleep(5)

    async def close(self) -> None:
        """Gracefully close all connections."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
            self._connected = False
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
