from typing import Optional, Tuple

import trio

from ._resolver import Resolver
from ..._helpers import is_ipv4_address, is_ipv6_address


async def connect_tcp(
    host: str,
    port: int,
    local_addr: Optional[Tuple[str, int]] = None,
) -> trio.socket.SocketType:

    family, host = await _resolve_host(host)

    sock = trio.socket.socket(family=family, type=trio.socket.SOCK_STREAM)
    if local_addr is not None:  # pragma: no cover
        await sock.bind(local_addr)

    try:
        await sock.connect((host, port))
    except OSError:
        sock.close()
        raise
    return sock


async def _resolve_host(host):
    if is_ipv4_address(host):
        return trio.socket.AF_INET, host
    if is_ipv6_address(host):
        return trio.socket.AF_INET6, host

    resolver = Resolver()
    return await resolver.resolve(host=host)
