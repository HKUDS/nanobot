import ssl
from typing import Union

import trio

from ...._errors import ProxyError
from .... import _abc as abc

DEFAULT_RECEIVE_SIZE = 65536

TrioStreamType = Union[trio.SocketStream, trio.SSLStream]


class TrioSocketStream(abc.AsyncSocketStream):
    _stream: TrioStreamType

    def __init__(self, stream: TrioStreamType):
        self._stream = stream

    async def write_all(self, data):
        await self._stream.send_all(data)

    async def read(self, max_bytes=DEFAULT_RECEIVE_SIZE):
        return await self._stream.receive_some(max_bytes)

    async def read_exact(self, n):
        data = bytearray()
        while len(data) < n:
            packet = await self._stream.receive_some(n - len(data))
            if not packet:  # pragma: no cover
                raise ProxyError('Connection closed unexpectedly')
            data += packet
        return data

    async def start_tls(
        self,
        hostname: str,
        ssl_context: ssl.SSLContext,
    ) -> 'TrioSocketStream':
        ssl_stream = trio.SSLStream(
            self._stream,
            ssl_context=ssl_context,
            server_hostname=hostname,
            https_compatible=True,
            server_side=False,
        )
        await ssl_stream.do_handshake()
        return TrioSocketStream(ssl_stream)

    async def close(self):
        await self._stream.aclose()

    @property
    def trio_stream(self) -> TrioStreamType:  # pragma: nocover
        return self._stream
