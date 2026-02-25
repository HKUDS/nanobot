import trio

from ... import _abc as abc


class Resolver(abc.AsyncResolver):
    async def resolve(self, host, port=0, family=trio.socket.AF_UNSPEC):
        infos = await trio.socket.getaddrinfo(
            host=host,
            port=port,
            family=family,
            type=trio.socket.SOCK_STREAM,
        )

        if not infos:  # pragma: no cover
            raise OSError('Can`t resolve address {}:{} [{}]'.format(host, port, family))

        infos = sorted(infos, key=lambda info: info[0])

        family, _, _, _, address = infos[0]
        return family, address[0]
