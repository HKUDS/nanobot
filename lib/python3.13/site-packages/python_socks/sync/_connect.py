import socket
from typing import Optional, Tuple


def connect_tcp(
    host: str,
    port: int,
    timeout: Optional[float] = None,
    local_addr: Optional[Tuple[str, int]] = None,
) -> socket.socket:
    address = (host, port)
    return socket.create_connection(
        address,
        timeout,
        source_address=local_addr,
    )
