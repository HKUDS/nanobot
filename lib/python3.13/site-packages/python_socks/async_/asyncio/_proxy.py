import asyncio
import socket
import sys
from typing import Any, Optional
import warnings

from ..._types import ProxyType
from ..._helpers import parse_proxy_url
from ..._errors import ProxyConnectionError, ProxyTimeoutError, ProxyError
from ._stream import AsyncioSocketStream
from ._resolver import Resolver

from ..._protocols.errors import ReplyError
from ..._connectors.factory_async import create_connector

from ._connect import connect_tcp

if sys.version_info >= (3, 11):
    import asyncio as async_timeout  # pylint:disable=reimported
else:
    import async_timeout

DEFAULT_TIMEOUT = 60


class AsyncioProxy:
    def __init__(
        self,
        proxy_type: ProxyType,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None,
        rdns: Optional[bool] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        if loop is None:
            loop = asyncio.get_event_loop()

        self._loop = loop

        self._proxy_type = proxy_type
        self._proxy_host = host
        self._proxy_port = port
        self._password = password
        self._username = username
        self._rdns = rdns

        self._resolver = Resolver(loop=loop)

    async def connect(
        self,
        dest_host: str,
        dest_port: int,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> socket.socket:
        if timeout is None:
            timeout = DEFAULT_TIMEOUT

        _socket = kwargs.get('_socket')
        if _socket is not None:
            warnings.warn(
                "The '_socket' argument is deprecated and will be removed in the future",
                DeprecationWarning,
                stacklevel=2,
            )

        local_addr = kwargs.get('local_addr')
        try:
            async with async_timeout.timeout(timeout):
                return await self._connect(
                    dest_host=dest_host,
                    dest_port=dest_port,
                    _socket=_socket,
                    local_addr=local_addr,
                )
        except asyncio.TimeoutError as e:
            raise ProxyTimeoutError(f'Proxy connection timed out: {timeout}') from e

    async def _connect(
        self,
        dest_host,
        dest_port,
        _socket=None,
        local_addr=None,
    ) -> socket.socket:
        if _socket is None:
            try:
                _socket = await connect_tcp(
                    host=self._proxy_host,
                    port=self._proxy_port,
                    loop=self._loop,
                    local_addr=local_addr,
                )
            except OSError as e:
                msg = 'Could not connect to proxy {}:{} [{}]'.format(
                    self._proxy_host,
                    self._proxy_port,
                    e.strerror,
                )
                raise ProxyConnectionError(e.errno, msg) from e

        stream = AsyncioSocketStream(sock=_socket, loop=self._loop)

        try:
            connector = create_connector(
                proxy_type=self._proxy_type,
                username=self._username,
                password=self._password,
                rdns=self._rdns,
                resolver=self._resolver,
            )
            await connector.connect(
                stream=stream,
                host=dest_host,
                port=dest_port,
            )

            return _socket
        except ReplyError as e:
            await stream.close()
            raise ProxyError(e, error_code=e.error_code)
        except (asyncio.CancelledError, Exception):  # pragma: no cover
            await stream.close()
            raise

    @property
    def proxy_host(self):
        return self._proxy_host

    @property
    def proxy_port(self):
        return self._proxy_port

    @classmethod
    def create(cls, *args, **kwargs):  # for backward compatibility
        return cls(*args, **kwargs)

    @classmethod
    def from_url(cls, url: str, **kwargs) -> 'AsyncioProxy':
        url_args = parse_proxy_url(url)
        return cls(*url_args, **kwargs)
