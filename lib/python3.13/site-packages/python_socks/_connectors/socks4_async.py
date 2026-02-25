import socket
from typing import Optional

from .._abc import AsyncSocketStream, AsyncResolver
from .abc import AsyncConnector

from .._protocols import socks4
from .._helpers import is_ip_address


class Socks4AsyncConnector(AsyncConnector):
    def __init__(
        self,
        user_id: Optional[str],
        rdns: Optional[bool],
        resolver: AsyncResolver,
    ):
        if rdns is None:
            rdns = False

        self._user_id = user_id
        self._rdns = rdns
        self._resolver = resolver

    async def connect(
        self,
        stream: AsyncSocketStream,
        host: str,
        port: int,
    ) -> socks4.ConnectReply:
        conn = socks4.Connection()

        if not is_ip_address(host) and not self._rdns:
            _, host = await self._resolver.resolve(
                host,
                family=socket.AF_INET,
            )

        request = socks4.ConnectRequest(host=host, port=port, user_id=self._user_id)
        data = conn.send(request)
        await stream.write_all(data)

        data = await stream.read_exact(socks4.ConnectReply.SIZE)
        reply: socks4.ConnectReply = conn.receive(data)
        return reply
