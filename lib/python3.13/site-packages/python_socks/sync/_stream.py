import socket

from .._errors import ProxyError
from .. import _abc as abc

DEFAULT_RECEIVE_SIZE = 65536


class SyncSocketStream(abc.SyncSocketStream):
    _socket: socket.socket

    def __init__(self, sock: socket.socket):
        self._socket = sock

    def write_all(self, data):
        self._socket.sendall(data)

    def read(self, max_bytes=DEFAULT_RECEIVE_SIZE):
        return self._socket.recv(max_bytes)

    def read_exact(self, n):
        data = bytearray()
        while len(data) < n:
            packet = self._socket.recv(n - len(data))
            if not packet:  # pragma: no cover
                raise ProxyError('Connection closed unexpectedly')
            data += packet
        return data

    def close(self):
        if self._socket is not None:
            self._socket.close()
