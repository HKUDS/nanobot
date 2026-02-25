from .._abc import SyncSocketStream, AsyncSocketStream


class SyncConnector:
    def connect(
        self,
        stream: SyncSocketStream,
        host: str,
        port: int,
    ):
        raise NotImplementedError


class AsyncConnector:
    async def connect(
        self,
        stream: AsyncSocketStream,
        host: str,
        port: int,
    ):
        raise NotImplementedError
