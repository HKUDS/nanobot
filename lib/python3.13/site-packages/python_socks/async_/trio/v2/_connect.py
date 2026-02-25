from typing import Optional

import trio
from ._stream import TrioSocketStream


async def connect_tcp(
    host: str,
    port: int,
    local_addr: Optional[str] = None,
) -> TrioSocketStream:
    trio_stream = await trio.open_tcp_stream(
        host=host,
        port=port,
        local_address=local_addr,
    )
    return TrioSocketStream(trio_stream)
