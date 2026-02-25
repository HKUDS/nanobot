import socket
from typing import Optional

from .._abc import AsyncSocketStream, AsyncResolver
from .abc import AsyncConnector

from .._protocols import socks5
from .._helpers import is_ip_address


class Socks5AsyncConnector(AsyncConnector):
    def __init__(
        self,
        username: Optional[str],
        password: Optional[str],
        rdns: Optional[bool],
        resolver: AsyncResolver,
    ):
        if rdns is None:
            rdns = True

        self._username = username
        self._password = password
        self._rdns = rdns
        self._resolver = resolver

    async def connect(
        self,
        stream: AsyncSocketStream,
        host: str,
        port: int,
    ) -> socks5.ConnectReply:
        conn = socks5.Connection()

        # Auth methods
        request = socks5.AuthMethodsRequest(
            username=self._username,
            password=self._password,
        )
        data = conn.send(request)
        await stream.write_all(data)

        data = await stream.read_exact(socks5.AuthMethodReply.SIZE)
        reply: socks5.AuthMethodReply = conn.receive(data)

        # Authenticate
        if reply.method == socks5.AuthMethod.USERNAME_PASSWORD:
            request = socks5.AuthRequest(
                username=self._username,
                password=self._password,
            )
            data = conn.send(request)
            await stream.write_all(data)

            data = await stream.read_exact(socks5.AuthReply.SIZE)
            _: socks5.AuthReply = conn.receive(data)

        # Connect
        if not is_ip_address(host) and not self._rdns:
            _, host = await self._resolver.resolve(
                host,
                family=socket.AF_UNSPEC,
            )

        request = socks5.ConnectRequest(host=host, port=port)
        data = conn.send(request)
        await stream.write_all(data)

        data = await self._read_reply(stream)
        reply: socks5.ConnectReply = conn.receive(data)
        return reply

    # noinspection PyMethodMayBeStatic
    async def _read_reply(self, stream: AsyncSocketStream) -> bytes:
        data = await stream.read_exact(3)
        if data[0] != socks5.SOCKS_VER:
            return data
        if data[1] != socks5.ReplyCode.SUCCEEDED:
            return data
        if data[2] != socks5.RSV:
            return data

        data += await stream.read_exact(1)
        addr_type = data[3]

        if addr_type == socks5.AddressType.IPV4:
            data += await stream.read_exact(6)
        elif addr_type == socks5.AddressType.IPV6:
            data += await stream.read_exact(18)
        elif addr_type == socks5.AddressType.DOMAIN:
            data += await stream.read_exact(1)
            host_len = data[-1]
            data += await stream.read_exact(host_len + 2)

        return data
