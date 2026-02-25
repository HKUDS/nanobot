from typing import Optional, Tuple

import curio
import curio.io
import curio.socket


async def connect_tcp(
    host: str,
    port: int,
    local_addr: Optional[Tuple[str, int]] = None,
) -> curio.io.Socket:
    return await curio.open_connection(
        host=host,
        port=port,
        source_addr=local_addr,
    )
