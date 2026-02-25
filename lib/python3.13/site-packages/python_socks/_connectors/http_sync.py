from typing import Optional
from .._abc import SyncSocketStream, SyncResolver
from .abc import SyncConnector

from .._protocols import http


class HttpSyncConnector(SyncConnector):
    def __init__(
        self,
        username: Optional[str],
        password: Optional[str],
        resolver: SyncResolver,
    ):
        self._username = username
        self._password = password
        self._resolver = resolver

    def connect(
        self,
        stream: SyncSocketStream,
        host: str,
        port: int,
    ) -> http.ConnectReply:
        conn = http.Connection()

        request = http.ConnectRequest(
            host=host,
            port=port,
            username=self._username,
            password=self._password,
        )
        data = conn.send(request)
        stream.write_all(data)

        data = stream.read()
        reply: http.ConnectReply = conn.receive(data)
        return reply
