import socket
import ssl
from typing import Union

from ._ssl_transport import SSLTransport

from ..._errors import ProxyError
from ... import _abc as abc

DEFAULT_RECEIVE_SIZE = 65536

SocketType = Union[socket.socket, ssl.SSLSocket, SSLTransport]


class SyncSocketStream(abc.SyncSocketStream):
    _socket: SocketType

    def __init__(self, sock: SocketType):
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

    def start_tls(self, hostname: str, ssl_context: ssl.SSLContext) -> 'SyncSocketStream':
        if isinstance(self._socket, (ssl.SSLSocket, SSLTransport)):
            ssl_socket = SSLTransport(
                self._socket,
                ssl_context=ssl_context,
                server_hostname=hostname,
            )
        else:  # plain socket?
            ssl_socket = ssl_context.wrap_socket(
                self._socket,
                server_hostname=hostname,
            )

        return SyncSocketStream(ssl_socket)

    def close(self):
        self._socket.close()

    @property
    def socket(self) -> SocketType:  # pragma: nocover
        return self._socket
