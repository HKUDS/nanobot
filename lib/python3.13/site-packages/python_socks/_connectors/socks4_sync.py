import socket
from typing import Optional

from .._abc import SyncSocketStream, SyncResolver
from .abc import SyncConnector

from .._protocols import socks4
from .._helpers import is_ip_address


class Socks4SyncConnector(SyncConnector):
    def __init__(
        self,
        user_id: Optional[str],
        rdns: Optional[bool],
        resolver: SyncResolver,
    ):
        if rdns is None:
            rdns = False

        self._user_id = user_id
        self._rdns = rdns
        self._resolver = resolver

    def connect(
        self,
        stream: SyncSocketStream,
        host: str,
        port: int,
    ) -> socks4.ConnectReply:
        conn = socks4.Connection()

        if not is_ip_address(host) and not self._rdns:
            _, host = self._resolver.resolve(
                host,
                family=socket.AF_INET,
            )

        request = socks4.ConnectRequest(host=host, port=port, user_id=self._user_id)
        data = conn.send(request)
        stream.write_all(data)

        data = stream.read_exact(socks4.ConnectReply.SIZE)
        reply: socks4.ConnectReply = conn.receive(data)
        return reply
