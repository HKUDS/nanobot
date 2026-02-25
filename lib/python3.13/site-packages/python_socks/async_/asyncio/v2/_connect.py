import asyncio
from typing import Optional, Tuple
from ._stream import AsyncioSocketStream


async def connect_tcp(
    host: str,
    port: int,
    loop: asyncio.AbstractEventLoop,
    local_addr: Optional[Tuple[str, int]] = None,
) -> AsyncioSocketStream:
    kwargs = {}
    if local_addr is not None:
        kwargs['local_addr'] = local_addr  # pragma: no cover

    reader, writer = await asyncio.open_connection(
        host=host,
        port=port,
        **kwargs,  # type: ignore
    )

    return AsyncioSocketStream(
        loop=loop,
        reader=reader,
        writer=writer,
    )
