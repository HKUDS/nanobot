from typing import Optional
import anyio
import anyio.abc


async def connect_tcp(
    host: str,
    port: int,
    local_host: Optional[str] = None,
) -> anyio.abc.SocketStream:

    return await anyio.connect_tcp(
        remote_host=host,
        remote_port=port,
        local_host=local_host,
    )
