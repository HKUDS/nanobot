import socket
from typing import Optional, Tuple
from ._stream import SyncSocketStream


def connect_tcp(
    host: str,
    port: int,
    timeout: Optional[float] = None,
    local_addr: Optional[Tuple[str, int]] = None,
) -> SyncSocketStream:
    address = (host, port)
    sock = socket.create_connection(
        address,
        timeout,
        source_address=local_addr,
    )

    return SyncSocketStream(sock)
