import asyncio
import socket

from ..._errors import ProxyError

from ... import _abc as abc

DEFAULT_RECEIVE_SIZE = 65536


class AsyncioSocketStream(abc.AsyncSocketStream):
    _loop: asyncio.AbstractEventLoop = None
    _socket = None

    def __init__(self, sock: socket.socket, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._socket = sock

    async def write_all(self, data):
        await self._loop.sock_sendall(self._socket, data)

    async def read(self, max_bytes=DEFAULT_RECEIVE_SIZE):
        return await self._loop.sock_recv(self._socket, max_bytes)

    async def read_exact(self, n):
        data = bytearray()
        while len(data) < n:
            packet = await self._loop.sock_recv(self._socket, n - len(data))
            if not packet:  # pragma: no cover
                raise ProxyError('Connection closed unexpectedly')
            data += packet
        return data

    async def close(self):
        if self._socket is not None:
            self._socket.close()
