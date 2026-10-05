"""A browser origin with local capabilities, not reusable remote credentials.

The private SSH listener is never published. This proxy drains its requests
before releasing that listener; a process reclaiming the public browser port
after shutdown can receive only capabilities from an already-dead proxy.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import re
import secrets
import socket
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, cast

import httpx
from aiohttp import WSMsgType, web
from cryptography.fernet import Fernet, InvalidToken
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException
from websockets.typing import Origin
from yarl import URL

from nanobot.webui.client_contract import assess_webui_contract, compatibility_error
from nanobot.webui.local_client_assets import LocalClientAssets
from nanobot.webui.remote_ssh import (
    RemoteError,
    Tunnel,
    _listen,  # pyright: ignore[reportPrivateUsage]
)

_MAX_BYTES = 64 * 1024 * 1024
_MAX_CAPABILITIES = 10000
_MEDIA_PATH = r"/api/media/[A-Za-z0-9_-]{22}/[A-Za-z0-9_-]+"
# Consume absolute URLs unchanged before matching gateway-relative media paths.
# An external site's similarly named route is not this proxy's capability.
_MEDIA = re.compile(r"(?:[A-Za-z][A-Za-z0-9+.-]*:)?//[^\s<>\"'`()]+|"
                    rf"(?<![A-Za-z0-9_/%:.~-])(?P<media>{_MEDIA_PATH})")
_REQUEST_HEADERS = {"accept", "accept-language", "content-type", "range", "if-range"}
_RESPONSE_HEADERS = {
    "content-type", "content-range", "accept-ranges", "content-disposition",
    "content-security-policy", "x-content-type-options", "last-modified",
}


@dataclass(frozen=True)
class _Grant:
    remote: str
    expires: float
    path: str = ""


class RemoteProxy:
    """Owns the public listener, local credentials and a private SSH transport."""

    def __init__(self, tunnel: Tunnel, secret: str, gateway_id: str, issue_path: str) -> None:
        self.tunnel = tunnel
        self.secret = secrets.token_urlsafe(32)
        self.port = 0
        self._remote_secret = secret
        self._gateway_id = gateway_id
        self._issue_path = issue_path.rstrip("/") or ""
        # Reload caches are scoped to WS pathname. A fresh process must not
        # reuse cached transcripts containing a previous proxy's media grants.
        self._ws_path = "/remote-session/" + secrets.token_urlsafe(18)
        self._api: dict[str, _Grant] = {}
        self._ws: dict[str, _Grant] = {}
        self._media_cipher = Fernet(Fernet.generate_key())
        self._media_cache: OrderedDict[str, str] = OrderedDict()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._bootstrap_lock = asyncio.Lock()
        self._enabled = True
        self._runner: web.AppRunner | None = None
        self.assets = LocalClientAssets()

    @classmethod
    async def open(
        cls, tunnel: Tunnel, secret: str, gateway_id: str, issue_path: str = "",
        *, local_port: int = 0, excluded_ports: set[int] | None = None,
    ) -> RemoteProxy:
        self = cls(tunnel, secret, gateway_id, issue_path)
        if not self.assets.available:
            raise RemoteError("local_webui_unavailable")
        listener = _listen(local_port, excluded_ports or set())
        self.port = int(listener.getsockname()[1])
        app = web.Application(client_max_size=_MAX_BYTES)
        app.router.add_route("*", "/{path:.*}", self._handle)
        self._runner = web.AppRunner(app, access_log=None, handler_cancellation=True)
        try:
            await self._runner.setup()
            await web.SockSite(self._runner, listener).start()
            return self
        except BaseException:
            listener.close()
            await self._runner.cleanup()
            raise

    @property
    def active(self) -> bool:
        return self._enabled and self.tunnel.active

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def resume(self, secret: str, gateway_id: str, issue_path: str = "") -> None:
        if gateway_id != self._gateway_id:
            self._ws_path = "/remote-session/" + secrets.token_urlsafe(18)
            self._api.clear()
            self._ws.clear()
            self._media_cipher = Fernet(Fernet.generate_key())
            self._media_cache.clear()
        self._remote_secret = secret
        self._gateway_id = gateway_id
        self._issue_path = issue_path.rstrip("/") or ""
        self._enabled = True

    async def pause(self) -> None:
        self._enabled = False
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._api.clear()
        self._ws.clear()
        await self.tunnel.pause()

    async def close(self) -> None:
        await self.pause()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self._remote_secret = ""
        self._media_cipher = Fernet(Fernet.generate_key())
        self._media_cache.clear()
        await self.tunnel.close()

    def _credential(self, request: web.Request, *, bootstrap: bool = False) -> str:
        # Decode query names once. Reject duplicates and mixed aliases rather
        # than allowing the client and upstream to disagree about precedence.
        auth = request.headers.getall("Authorization", [])
        issue = request.headers.getall("X-Nanobot-Auth", [])
        query = request.rel_url.query.getall("token", [])
        if len(auth) + len(issue) + len(query) > 1:
            raise web.HTTPUnauthorized()
        if auth:
            scheme, _, value = auth[0].partition(" ")
            if scheme.lower() != "bearer" or not value:
                raise web.HTTPUnauthorized()
            return value
        if bootstrap and issue:
            return issue[0]
        if not bootstrap and query:
            return query[0]
        return ""

    def _grant(self, token: str, grants: dict[str, _Grant], *, consume: bool = False) -> _Grant:
        grant = grants.pop(token, None) if consume else grants.get(token)
        if grant is None or grant.expires <= time.monotonic():
            raise web.HTTPUnauthorized()
        return grant

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        if (request.headers.getall("Host", []) != [f"127.0.0.1:{self.port}"]
                or request.headers.getall("Origin", []) not in ([], [self.origin])):
            raise web.HTTPForbidden()
        if not self.active:
            raise web.HTTPServiceUnavailable()
        task = asyncio.current_task()
        assert task is not None
        self._tasks.add(task)
        try:
            # The upstream gateway uses the raw path (not unquoted path) for
            # routing. Keep it intact and do not normalize escaped separators.
            path = request.rel_url.raw_path.rstrip("/") or "/"
            if path == self._issue_path:
                raise web.HTTPForbidden()
            if request.headers.get("Upgrade", "").lower() == "websocket":
                if path != self._ws_path:
                    raise web.HTTPNotFound()
                grant = self._grant(self._credential(request), self._ws, consume=True)
                return await self._websocket(request, grant)
            if path == "/webui/bootstrap":
                if request.method != "GET":
                    raise web.HTTPMethodNotAllowed(request.method, ["GET"])
                supplied = self._credential(request, bootstrap=True)
                if not secrets.compare_digest(supplied.encode(), self.secret.encode()):
                    raise web.HTTPUnauthorized()
                async with self._bootstrap_lock:
                    return await self._bootstrap()
            if path == "/webui/terminal":
                raise web.HTTPForbidden()
            if not path.startswith("/api/"):
                return self.assets.response(request)
            return await self._http(request, path)
        except (httpx.HTTPError, WebSocketException, OSError, ValueError):
            # Never reflect upstream URLs, credentials or raw exception text.
            raise web.HTTPBadGateway(text="Remote connection unavailable") from None
        finally:
            self._tasks.discard(task)

    def _headers(self, request: web.Request) -> dict[str, str]:
        headers = {key: value for key, value in request.headers.items()
                   if key.lower() in _REQUEST_HEADERS}
        headers["Host"] = f"127.0.0.1:{self.port}"
        headers["Origin"] = self.origin
        return headers

    def _upstream(self, path: str) -> str:
        return f"http://127.0.0.1:{self.tunnel.port}{path}"

    async def _bootstrap(self) -> web.Response:
        now = time.monotonic()
        for grants in (self._api, self._ws):
            for key in [key for key, value in grants.items() if value.expires <= now]:
                del grants[key]
            if len(grants) >= _MAX_CAPABILITIES:
                raise web.HTTPTooManyRequests()
        async with httpx.AsyncClient(trust_env=False, timeout=20) as client:
            response = await client.get(self._upstream("/webui/bootstrap"), headers={
                "X-Nanobot-Auth": self._remote_secret, "Host": f"127.0.0.1:{self.port}",
            })
        if response.status_code != 200:
            raise web.HTTPBadGateway(text="Remote authentication unavailable")
        payload: object = response.json()
        if not isinstance(payload, dict):
            raise ValueError("invalid bootstrap")
        data = cast(dict[str, Any], payload)
        terminal = data.get("terminal")
        if not isinstance(terminal, dict):
            raise ValueError("invalid terminal")
        terminal = cast(dict[str, Any], terminal)
        report = assess_webui_contract(terminal.get("webui"))
        error = compatibility_error(report)
        if error:
            return web.json_response({"error": error, "compatibility": report}, status=409,
                                     headers={"Cache-Control": "no-store"})
        ttl, ws_path = data.get("expires_in"), data.get("ws_path")
        if (terminal.get("gatewayId") != self._gateway_id
                or terminal.get("protocolVersion") != 1
                or not isinstance(ttl, (float, int)) or not math.isfinite(ttl) or not 0 < ttl <= 86400
                or not isinstance(ws_path, str) or not ws_path.startswith("/")
                or ws_path.startswith("//") or "?" in ws_path or "#" in ws_path
                or any(ord(c) < 33 for c in ws_path)
                or not isinstance(data.get("token"), str) or not data["token"]
                or not isinstance(data.get("api_token"), str) or not data["api_token"]):
            raise ValueError("incompatible bootstrap")
        token, api_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        # Count elapsed upstream time against the remote token's TTL.
        self._ws[token] = _Grant(data["token"], now + ttl, ws_path)
        self._api[api_token] = _Grant(data["api_token"], now + ttl)
        result = {key: data[key] for key in (
            "limits", "model_name", "runtime_surface", "runtime_capabilities",
        ) if key in data}
        result.update(token=token, api_token=api_token, expires_in=ttl,
                      terminal={"protocolVersion": 1, "gatewayId": self._gateway_id,
                                "webui": terminal["webui"]},
                      ws_path=self._ws_path, ws_url=f"ws://127.0.0.1:{self.port}{self._ws_path}")
        result["host_compatibility"] = report
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    def _local_media(self, match: re.Match[str]) -> str:
        remote = match.group("media")
        if remote is None:
            return match.group()
        existing = self._media_cache.get(remote)
        if existing:
            self._media_cache.move_to_end(remote)
            return existing
        # Authenticated encryption hides the remote bearer URL without retaining
        # an unbounded mapping. Eviction only changes future URL spelling: every
        # previously issued URL still works for this proxy's lifetime.
        local = "/api/media/local/" + self._media_cipher.encrypt(remote.encode()).decode()
        if len(self._media_cache) >= _MAX_CAPABILITIES:
            self._media_cache.popitem(last=False)
        self._media_cache[remote] = local
        return local

    def _remote_media(self, path: str) -> str:
        prefix = "/api/media/local/"
        if not path.startswith(prefix):
            raise web.HTTPUnauthorized()
        try:
            remote = self._media_cipher.decrypt(path[len(prefix):].encode()).decode()
        except (InvalidToken, UnicodeError, ValueError):
            raise web.HTTPUnauthorized() from None
        if not re.fullmatch(_MEDIA_PATH, remote):
            raise web.HTTPUnauthorized()
        return remote

    def _rewrite(self, value: Any) -> Any:
        if isinstance(value, str):
            return _MEDIA.sub(self._local_media, value)
        if isinstance(value, list):
            return [self._rewrite(item) for item in cast(list[Any], value)]
        if isinstance(value, dict):
            return {key: self._rewrite(item) for key, item in cast(dict[str, Any], value).items()}
        return value

    async def _http(self, request: web.Request, path: str) -> web.StreamResponse:
        url = request.rel_url.with_query([
            (key, value) for key, value in request.rel_url.query.items() if key != "token"
        ])
        headers = self._headers(request)
        if path.startswith("/api/media/"):
            remote = self._remote_media(path)
            url = URL(remote).with_query(url.query)
        elif path.startswith("/api/"):
            grant = self._grant(self._credential(request), self._api)
            headers["Authorization"] = "Bearer " + grant.remote
        # HTTP API responses are read-only. WebUI writes travel over
        # its authenticated multiplex WebSocket, not an arbitrary HTTP relay.
        if request.method not in {"GET", "HEAD"}:
            raise web.HTTPMethodNotAllowed(request.method, ["GET", "HEAD"])
        async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
            async with client.stream(request.method, self._upstream(str(url)), headers=headers) as upstream:
                if upstream.is_redirect:
                    raise web.HTTPBadGateway(text="Unexpected remote redirect")
                outgoing = {key: value for key, value in upstream.headers.items()
                            if key.lower() in _RESPONSE_HEADERS}
                outgoing["Cache-Control"] = "no-store"
                # Remote documents/media are data, never executable client code.
                # Keep them sandboxed even if a host omits or relaxes its headers.
                outgoing["X-Content-Type-Options"] = "nosniff"
                outgoing["Content-Security-Policy"] = (
                    "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:"
                )
                if "application/json" in upstream.headers.get("content-type", ""):
                    body = bytearray()
                    async for chunk in upstream.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_BYTES:
                            raise ValueError("response too large")
                    if request.method == "HEAD":
                        return web.Response(status=upstream.status_code, headers=outgoing)
                    return web.Response(body=json.dumps(self._rewrite(json.loads(body))).encode(),
                                        status=upstream.status_code, headers=outgoing)
                result = web.StreamResponse(status=upstream.status_code, headers=outgoing)
                await result.prepare(request)
                async for chunk in upstream.aiter_bytes():
                    await result.write(chunk)
                await result.write_eof()
                return result

    async def _websocket(self, request: web.Request, grant: _Grant) -> web.WebSocketResponse:
        # An already-connected socket fixes the upstream and disables all WS
        # redirects. Its HTTP authority still matches the browser's origin.
        upstream_socket = socket.socket()
        upstream_socket.setblocking(False)
        try:
            await asyncio.wait_for(asyncio.get_running_loop().sock_connect(
                upstream_socket, ("127.0.0.1", self.tunnel.port),
            ), 20)
            query = [(key, value) for key, value in request.rel_url.query.items() if key != "token"]
            query.append(("token", grant.remote))
            url = URL(f"ws://127.0.0.1:{self.port}").with_path(grant.path, encoded=True).with_query(query)
            async with connect(str(url), sock=upstream_socket, proxy=None, origin=Origin(self.origin),
                               max_size=_MAX_BYTES, open_timeout=20, close_timeout=2) as upstream:
                browser = web.WebSocketResponse(max_msg_size=_MAX_BYTES, heartbeat=30)
                await browser.prepare(request)

                async def receive() -> None:
                    try:
                        async for message in upstream:
                            if isinstance(message, bytes):
                                await browser.send_bytes(message)
                            else:
                                await browser.send_str(json.dumps(self._rewrite(json.loads(message))))
                    finally:
                        await browser.close()

                reader = asyncio.create_task(receive())
                try:
                    async for message in browser:
                        if message.type in {WSMsgType.TEXT, WSMsgType.BINARY}:
                            await upstream.send(message.data)
                finally:
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                    await browser.close()
                return browser
        finally:
            # connect owns the socket after handoff; close is also safe if
            # cancellation occurred before the protocol took ownership.
            with contextlib.suppress(OSError):
                upstream_socket.close()
