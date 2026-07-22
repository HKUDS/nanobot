"""Lightweight WebSocket test client for integration testing the nanobot WebSocket channel.

Provides an async ``WsTestClient`` class and token-issuance helpers that
integration tests can import and use directly::

    from nanobot.channels.websocket.tests.ws_test_client import WsTestClient

    async with WsTestClient("ws://127.0.0.1:8765/", client_id="t") as c:
        ready = await c.recv_ready()
        await c.send_text("hello")
        msg = await c.recv_message()
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import websockets
from websockets.asyncio.client import ClientConnection
from websockets.datastructures import Headers
from websockets.http11 import Request as WsRequest

from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.webui.http_utils import http_response

_IN_PROCESS_HTTP_CHANNELS: dict[int, InProcessHttpChannel] = {}


class _HttpConnection:
    remote_address = ("127.0.0.1", 12345)

    @staticmethod
    def respond(status: int, body: str) -> object:
        return http_response(body.encode("utf-8"), status=status)


class InProcessHttpChannel(WebSocketChannel):
    """Exercise gateway HTTP dispatch without booting a socket per route test."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._test_stop_event = asyncio.Event()
        _IN_PROCESS_HTTP_CHANNELS[self.config.port] = self

    async def start(self) -> None:
        self._running = True
        await self._test_stop_event.wait()
        self._running = False

    async def stop(self) -> None:
        self._test_stop_event.set()
        if _IN_PROCESS_HTTP_CHANNELS.get(self.config.port) is self:
            _IN_PROCESS_HTTP_CHANNELS.pop(self.config.port, None)


async def _in_process_http_get(
    channel: InProcessHttpChannel,
    request: httpx.Request,
) -> httpx.Response:
    ws_request = WsRequest(
        request.url.raw_path.decode("ascii"),
        Headers(list(request.headers.multi_items())),
    )
    response = await channel._dispatch_http(_HttpConnection(), ws_request)
    assert response is not None
    return httpx.Response(
        response.status_code,
        headers=list(response.headers.raw_items()),
        content=response.body,
        request=request,
    )


@dataclass
class WsMessage:
    """A parsed message received from the WebSocket server."""

    event: str
    raw: dict[str, Any] = field(repr=False)

    @property
    def text(self) -> str | None:
        return self.raw.get("text")

    @property
    def chat_id(self) -> str | None:
        return self.raw.get("chat_id")

    @property
    def client_id(self) -> str | None:
        return self.raw.get("client_id")

    @property
    def media(self) -> list[str] | None:
        return self.raw.get("media")

    @property
    def reply_to(self) -> str | None:
        return self.raw.get("reply_to")

    @property
    def stream_id(self) -> str | None:
        return self.raw.get("stream_id")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WsMessage):
            return NotImplemented
        return self.event == other.event and self.raw == other.raw


class WsTestClient:
    """Async WebSocket test client with helper methods for common operations.

    Usage::

        async with WsTestClient("ws://127.0.0.1:8765/", client_id="tester") as client:
            ready = await client.recv_ready()
            await client.send_text("hello")
            msg = await client.recv_message(timeout=5.0)
    """

    def __init__(
        self,
        uri: str,
        *,
        client_id: str = "test-client",
        token: str = "",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        params: list[str] = []
        if client_id:
            params.append(f"client_id={client_id}")
        if token:
            params.append(f"token={token}")
        sep = "&" if "?" in uri else "?"
        self._uri = uri + sep + "&".join(params) if params else uri
        self._extra_headers = extra_headers
        self._ws: ClientConnection | None = None

    async def connect(self, timeout: float = 2.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            try:
                self._ws = await websockets.connect(
                    self._uri,
                    additional_headers=self._extra_headers,
                )
                return
            except OSError:
                if asyncio.get_running_loop().time() >= deadline:
                    raise
                await asyncio.sleep(0.01)

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def __aenter__(self) -> WsTestClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    @property
    def ws(self) -> ClientConnection:
        assert self._ws is not None, "Client is not connected"
        return self._ws

    # -- Receiving --------------------------------------------------------

    async def recv_raw(self, timeout: float = 10.0) -> dict[str, Any]:
        """Receive and parse one raw JSON message with timeout."""
        raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
        return json.loads(raw)

    async def recv(self, timeout: float = 10.0) -> WsMessage:
        """Receive one message, returning a WsMessage wrapper."""
        data = await self.recv_raw(timeout)
        return WsMessage(event=data.get("event", ""), raw=data)

    async def recv_ready(self, timeout: float = 5.0) -> WsMessage:
        """Receive and validate the 'ready' event."""
        msg = await self.recv(timeout)
        assert msg.event == "ready", f"Expected 'ready' event, got '{msg.event}'"
        return msg

    async def recv_message(self, timeout: float = 10.0) -> WsMessage:
        """Receive and validate a 'message' event."""
        msg = await self.recv(timeout)
        assert msg.event == "message", f"Expected 'message' event, got '{msg.event}'"
        return msg

    async def recv_delta(self, timeout: float = 10.0) -> WsMessage:
        """Receive and validate a 'delta' event."""
        msg = await self.recv(timeout)
        assert msg.event == "delta", f"Expected 'delta' event, got '{msg.event}'"
        return msg

    async def recv_stream_end(self, timeout: float = 10.0) -> WsMessage:
        """Receive and validate a 'stream_end' event."""
        msg = await self.recv(timeout)
        assert msg.event == "stream_end", f"Expected 'stream_end' event, got '{msg.event}'"
        return msg

    async def collect_stream(self, timeout: float = 10.0) -> list[WsMessage]:
        """Collect all deltas and the final stream_end into a list."""
        messages: list[WsMessage] = []
        while True:
            msg = await self.recv(timeout)
            messages.append(msg)
            if msg.event == "stream_end":
                break
        return messages

    async def recv_n(self, n: int, timeout: float = 10.0) -> list[WsMessage]:
        """Receive exactly *n* messages."""
        return [await self.recv(timeout) for _ in range(n)]

    # -- Sending ----------------------------------------------------------

    async def send_text(self, text: str) -> None:
        """Send a plain text frame."""
        await self.ws.send(text)

    async def send_json(self, data: dict[str, Any]) -> None:
        """Send a JSON frame."""
        await self.ws.send(json.dumps(data, ensure_ascii=False))

    async def send_content(self, content: str) -> None:
        """Send content in the preferred JSON format ``{"content": ...}``."""
        await self.send_json({"content": content})

    # -- Connection introspection -----------------------------------------

    @property
    def closed(self) -> bool:
        return self._ws is None or self._ws.closed


# -- Token issuance helpers -----------------------------------------------


async def http_get(
    url: str,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET a local test server without loading an unused TLS trust store."""
    request = httpx.Request("GET", url, headers=headers or {})
    channel = _IN_PROCESS_HTTP_CHANNELS.get(request.url.port)
    if channel is not None:
        return await _in_process_http_get(channel, request)

    deadline = asyncio.get_running_loop().time() + 2.0
    while True:
        try:
            async with httpx.AsyncClient(
                timeout=5.0,
                trust_env=False,
                verify=False,
            ) as client:
                return await client.get(url, headers=headers or {})
        except httpx.ConnectError:
            if asyncio.get_running_loop().time() >= deadline:
                raise
            await asyncio.sleep(0.01)


async def issue_token(
    host: str = "127.0.0.1",
    port: int = 8765,
    issue_path: str = "/auth/token",
    secret: str = "",
) -> tuple[dict[str, Any] | None, int]:
    """Request a short-lived token from the token-issue HTTP endpoint.

    Returns ``(parsed_json_or_None, status_code)``.
    """
    url = f"http://{host}:{port}{issue_path}"
    headers: dict[str, str] = {}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    resp = await http_get(url, headers)
    try:
        data = resp.json()
    except Exception:
        data = None
    return data, resp.status_code


async def issue_token_ok(
    host: str = "127.0.0.1",
    port: int = 8765,
    issue_path: str = "/auth/token",
    secret: str = "",
) -> str:
    """Request a token, asserting success, and return the token string."""
    (data, status) = await issue_token(host, port, issue_path, secret)
    assert status == 200, f"Token issue failed with status {status}"
    assert data is not None
    token = data["token"]
    assert token.startswith("nbwt_"), f"Unexpected token format: {token}"
    return token
