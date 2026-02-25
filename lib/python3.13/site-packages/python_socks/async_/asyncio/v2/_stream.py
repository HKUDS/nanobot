import asyncio
import ssl

from .... import _abc as abc

DEFAULT_RECEIVE_SIZE = 65536


class AsyncioSocketStream(abc.AsyncSocketStream):
    _loop: asyncio.AbstractEventLoop
    _reader: asyncio.StreamReader
    _writer: asyncio.StreamWriter

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        self._loop = loop
        self._reader = reader
        self._writer = writer

    async def write_all(self, data):
        self._writer.write(data)
        await self._writer.drain()

    async def read(self, max_bytes=DEFAULT_RECEIVE_SIZE):
        return await self._reader.read(max_bytes)

    async def read_exact(self, n):
        return await self._reader.readexactly(n)

    async def start_tls(
        self,
        hostname: str,
        ssl_context: ssl.SSLContext,
        ssl_handshake_timeout=None,
    ) -> 'AsyncioSocketStream':
        if hasattr(self._writer, 'start_tls'):  # Python>=3.11
            await self._writer.start_tls(
                ssl_context,
                server_hostname=hostname,
                ssl_handshake_timeout=ssl_handshake_timeout,
            )
            return self

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        transport: asyncio.Transport = await self._loop.start_tls(
            self._writer.transport,  # type: ignore
            protocol,
            ssl_context,
            server_side=False,
            server_hostname=hostname,
            ssl_handshake_timeout=ssl_handshake_timeout,
        )

        # reader.set_transport(transport)

        # Initialize the protocol, so it is made aware of being tied to
        # a TLS connection.
        # See: https://github.com/encode/httpx/issues/859
        protocol.connection_made(transport)

        writer = asyncio.StreamWriter(
            transport=transport,
            protocol=protocol,
            reader=reader,
            loop=self._loop,
        )

        stream = AsyncioSocketStream(loop=self._loop, reader=reader, writer=writer)
        # When we return a new SocketStream with new StreamReader/StreamWriter instances
        # we need to keep references to the old StreamReader/StreamWriter so that they
        # are not garbage collected and closed while we're still using them.
        stream._inner = self  # type: ignore # pylint:disable=W0212,W0201
        return stream

    async def close(self):
        self._writer.close()
        self._writer.transport.abort()  # noqa

    @property
    def reader(self):
        return self._reader  # pragma: no cover

    @property
    def writer(self):
        return self._writer  # pragma: no cover
