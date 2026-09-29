"""Body-capable HTTP bridge for the existing websockets listener.

GET (including WebSocket upgrades) remains on websockets' existing parser and
handshake path. Other methods go directly to aiohttp's bounded streaming HTTP
parser on the same socket, without proxying or changing the authenticated peer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

from aiohttp import web
from aiohttp.web_protocol import RequestHandler
from websockets.asyncio.server import ServerConnection


class BinaryHTTPBridge:
    """Own HTTP connections alongside a websockets ``serve`` instance.

    Pass ``connection_factory`` as ``create_connection`` to serve/unix_serve.
    After closing the listening server, await ``shutdown`` before disposing the
    upload store. Request decompression is deliberately disabled: declared body
    lengths must measure the exact bytes the upload store writes.
    """

    def __init__(self, handler: Callable[[web.BaseRequest], Awaitable[web.StreamResponse]]) -> None:
        self.http_server = web.Server(handler, auto_decompress=False, keepalive_timeout=5)
        self.pending_connections: set[_BridgeConnection] = set()

        bridge = self

        class Connection(_BridgeConnection):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, bridge=bridge, **kwargs)

        self.connection_factory: type[ServerConnection] = Connection

    async def shutdown(self) -> None:
        for connection in tuple(self.pending_connections):
            connection.transport.close()
        await self.http_server.shutdown(timeout=1)


class _BridgeConnection(ServerConnection):
    def __init__(self, *args: Any, bridge: BinaryHTTPBridge, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._bridge = bridge
        self._prefix = bytearray()
        self._http_protocol: RequestHandler | None = None
        self._selected = False
        self._prefix_timeout: asyncio.TimerHandle | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        # Delay websockets' handshake task until we know which parser owns this
        # connection. In particular, never feed a POST to Request.parse().
        self.transport = cast(asyncio.Transport, transport)
        self._bridge.pending_connections.add(self)
        self._prefix_timeout = asyncio.get_running_loop().call_later(10, self.transport.close)

    def data_received(self, data: bytes) -> None:
        if not self._selected:
            needed = 4 - len(self._prefix)
            self._prefix.extend(data[:needed])
            if len(self._prefix) < 4:
                return
            data = bytes(self._prefix) + data[needed:]
            self._prefix.clear()
            self._selected = True
            self._bridge.pending_connections.discard(self)
            if self._prefix_timeout is not None:
                self._prefix_timeout.cancel()
            if data.startswith(b"GET "):
                super().connection_made(self.transport)
            else:
                self._http_protocol = self._bridge.http_server()
                self._http_protocol.connection_made(self.transport)
        if self._http_protocol is not None:
            self._http_protocol.data_received(data)
        else:
            super().data_received(data)

    def eof_received(self) -> None:
        if self._http_protocol is not None:
            return self._http_protocol.eof_received()
        if self._selected:
            return super().eof_received()
        return None

    def connection_lost(self, exc: Exception | None) -> None:
        self._bridge.pending_connections.discard(self)
        if self._prefix_timeout is not None:
            self._prefix_timeout.cancel()
        if self._http_protocol is not None:
            self._http_protocol.connection_lost(exc)
        elif self._selected:
            super().connection_lost(exc)

    def pause_writing(self) -> None:
        if self._http_protocol is not None:
            self._http_protocol.pause_writing()
        elif self._selected:
            super().pause_writing()

    def resume_writing(self) -> None:
        if self._http_protocol is not None:
            self._http_protocol.resume_writing()
        elif self._selected:
            super().resume_writing()

