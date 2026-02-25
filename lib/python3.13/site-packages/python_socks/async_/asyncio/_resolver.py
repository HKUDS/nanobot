import asyncio
import socket

from ... import _abc as abc


class Resolver(abc.AsyncResolver):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        infos = await self._loop.getaddrinfo(
            host=host,
            port=port,
            family=family,
            type=socket.SOCK_STREAM,
        )

        if not infos:  # pragma: no cover
            raise OSError('Can`t resolve address {}:{} [{}]'.format(host, port, family))

        infos = sorted(infos, key=lambda info: info[0])

        family, _, _, _, address = infos[0]
        return family, address[0]
