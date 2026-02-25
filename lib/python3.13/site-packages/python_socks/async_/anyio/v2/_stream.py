import ssl
from typing import Union

import anyio
import anyio.abc
from anyio.streams.tls import TLSStream

from ...._errors import ProxyError
from .... import _abc as abc

DEFAULT_RECEIVE_SIZE = 65536

AnyioStreamType = Union[anyio.abc.SocketStream, TLSStream]


class AnyioSocketStream(abc.AsyncSocketStream):
    _stream: AnyioStreamType

    def __init__(self, stream: AnyioStreamType) -> None:
        self._stream = stream

    async def write_all(self, data: bytes):
        await self._stream.send(item=data)

    async def read(self, max_bytes: int = DEFAULT_RECEIVE_SIZE):
        try:
            return await self._stream.receive(max_bytes=max_bytes)
        except anyio.EndOfStream:  # pragma: no cover
            return b""

    async def read_exact(self, n: int):
        data = bytearray()
        while len(data) < n:
            packet = await self.read(n - len(data))
            if not packet:  # pragma: no cover
                raise ProxyError('Connection closed unexpectedly')
            data += packet
        return data

    async def start_tls(
        self,
        hostname: str,
        ssl_context: ssl.SSLContext,
    ) -> 'AnyioSocketStream':
        ssl_stream = await TLSStream.wrap(
            self._stream,
            ssl_context=ssl_context,
            hostname=hostname,
            standard_compatible=False,
            server_side=False,
        )
        return AnyioSocketStream(ssl_stream)

    async def close(self):
        await self._stream.aclose()

    @property
    def anyio_stream(self) -> AnyioStreamType:  # pragma: no cover
        return self._stream
