from typing import Optional
from .._abc import AsyncSocketStream, AsyncResolver
from .abc import AsyncConnector

from .._protocols import http


class HttpAsyncConnector(AsyncConnector):
    def __init__(
        self,
        username: Optional[str],
        password: Optional[str],
        resolver: AsyncResolver,
    ):
        self._username = username
        self._password = password
        self._resolver = resolver

    async def connect(
        self,
        stream: AsyncSocketStream,
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
        await stream.write_all(data)

        data = await stream.read()
        reply: http.ConnectReply = conn.receive(data)
        return reply
