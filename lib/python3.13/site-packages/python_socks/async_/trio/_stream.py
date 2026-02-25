import trio

from ..._errors import ProxyError
from ... import _abc as abc

DEFAULT_RECEIVE_SIZE = 65536


class TrioSocketStream(abc.AsyncSocketStream):
    def __init__(self, sock):
        self._socket = sock

    async def write_all(self, data):
        total_sent = 0
        while total_sent < len(data):
            remaining = data[total_sent:]
            sent = await self._socket.send(remaining)
            total_sent += sent

    async def read(self, max_bytes=DEFAULT_RECEIVE_SIZE):
        return await self._socket.recv(max_bytes)

    async def read_exact(self, n):
        data = bytearray()
        while len(data) < n:
            packet = await self._socket.recv(n - len(data))
            if not packet:  # pragma: no cover
                raise ProxyError('Connection closed unexpectedly')
            data += packet
        return data

    async def close(self):
        if self._socket is not None:
            self._socket.close()
            await trio.lowlevel.checkpoint()
