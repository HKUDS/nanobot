from typing import Optional
import anyio
import anyio.abc
from ._stream import AnyioSocketStream


async def connect_tcp(
    host: str,
    port: int,
    local_host: Optional[str] = None,
) -> AnyioSocketStream:
    s = await anyio.connect_tcp(
        remote_host=host,
        remote_port=port,
        local_host=local_host,
    )
    return AnyioSocketStream(s)
