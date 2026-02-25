import curio.io
import curio.socket

from ... import _abc as abc
from ..._errors import ProxyError

DEFAULT_RECEIVE_SIZE = 65536


class CurioSocketStream(abc.AsyncSocketStream):
    _socket: curio.io.Socket = None

    def __init__(self, sock: curio.io.Socket):
        self._socket = sock

    async def write_all(self, data):
        await self._socket.sendall(data)

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
        await self._socket.close()
