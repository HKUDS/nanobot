import socket
from typing import Optional

from .._abc import SyncSocketStream, SyncResolver
from .abc import SyncConnector

from .._protocols import socks5
from .._helpers import is_ip_address


class Socks5SyncConnector(SyncConnector):
    def __init__(
        self,
        username: Optional[str],
        password: Optional[str],
        rdns: Optional[bool],
        resolver: SyncResolver,
    ):
        if rdns is None:
            rdns = True

        self._username = username
        self._password = password
        self._rdns = rdns
        self._resolver = resolver

    def connect(
        self,
        stream: SyncSocketStream,
        host: str,
        port: int,
    ) -> socks5.ConnectReply:
        conn = socks5.Connection()

        # Auth methods
        request = socks5.AuthMethodsRequest(username=self._username, password=self._password)
        data = conn.send(request)
        stream.write_all(data)

        data = stream.read_exact(socks5.AuthMethodReply.SIZE)
        reply: socks5.AuthMethodReply = conn.receive(data)

        # Authenticate
        if reply.method == socks5.AuthMethod.USERNAME_PASSWORD:
            request = socks5.AuthRequest(username=self._username, password=self._password)
            data = conn.send(request)
            stream.write_all(data)

            data = stream.read_exact(socks5.AuthReply.SIZE)
            _: socks5.AuthReply = conn.receive(data)

        # Connect
        if not is_ip_address(host) and not self._rdns:
            _, host = self._resolver.resolve(host, family=socket.AF_UNSPEC)

        request = socks5.ConnectRequest(host=host, port=port)
        data = conn.send(request)
        stream.write_all(data)

        data = self._read_reply(stream)
        reply: socks5.ConnectReply = conn.receive(data)
        return reply

    # noinspection PyMethodMayBeStatic
    def _read_reply(self, stream: SyncSocketStream) -> bytes:
        data = stream.read_exact(3)
        if data[0] != socks5.SOCKS_VER:
            return data
        if data[1] != socks5.ReplyCode.SUCCEEDED:
            return data
        if data[2] != socks5.RSV:
            return data

        data += stream.read_exact(1)
        addr_type = data[3]

        if addr_type == socks5.AddressType.IPV4:
            data += stream.read_exact(6)
        elif addr_type == socks5.AddressType.IPV6:
            data += stream.read_exact(18)
        elif addr_type == socks5.AddressType.DOMAIN:
            data += stream.read_exact(1)
            host_len = data[-1]
            data += stream.read_exact(host_len + 2)

        return data
