import socket
import asyncio
from typing import Optional, Tuple

from ._resolver import Resolver
from ..._helpers import is_ipv4_address, is_ipv6_address


async def connect_tcp(
    host: str,
    port: int,
    loop: asyncio.AbstractEventLoop,
    local_addr: Optional[Tuple[str, int]] = None,
) -> socket.socket:

    family, host = await _resolve_host(host, loop)

    sock = socket.socket(family=family, type=socket.SOCK_STREAM)
    sock.setblocking(False)
    if local_addr is not None:  # pragma: no cover
        sock.bind(local_addr)

    if is_ipv6_address(host):
        address = (host, port, 0, 0)  # to fix OSError: [WinError 10022]
    else:
        address = (host, port)  # type: ignore[assignment]

    try:
        await loop.sock_connect(sock=sock, address=address)
    except OSError:
        sock.close()
        raise
    return sock


async def _resolve_host(host, loop):
    if is_ipv4_address(host):
        return socket.AF_INET, host
    if is_ipv6_address(host):
        return socket.AF_INET6, host

    resolver = Resolver(loop=loop)
    return await resolver.resolve(host=host)
