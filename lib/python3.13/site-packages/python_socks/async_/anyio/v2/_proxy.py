import ssl
from typing import Any, Optional

import anyio

from ._connect import connect_tcp
from ._stream import AnyioSocketStream
from .._resolver import Resolver
from ...._errors import ProxyConnectionError, ProxyTimeoutError, ProxyError

from ...._types import ProxyType
from ...._helpers import parse_proxy_url

from ...._protocols.errors import ReplyError
from ...._connectors.factory_async import create_connector

DEFAULT_TIMEOUT = 60


class AnyioProxy:
    def __init__(
        self,
        proxy_type: ProxyType,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None,
        rdns: Optional[bool] = None,
        proxy_ssl: Optional[ssl.SSLContext] = None,
        forward: Optional['AnyioProxy'] = None,
    ):
        self._proxy_type = proxy_type
        self._proxy_host = host
        self._proxy_port = port
        self._username = username
        self._password = password
        self._rdns = rdns

        self._proxy_ssl = proxy_ssl
        self._forward = forward

        self._resolver = Resolver()

    async def connect(
        self,
        dest_host: str,
        dest_port: int,
        dest_ssl: Optional[ssl.SSLContext] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> AnyioSocketStream:
        if timeout is None:
            timeout = DEFAULT_TIMEOUT

        local_host = kwargs.get('local_host')
        try:
            with anyio.fail_after(timeout):
                return await self._connect(
                    dest_host=dest_host,
                    dest_port=dest_port,
                    dest_ssl=dest_ssl,
                    local_host=local_host,
                )
        except TimeoutError as e:
            raise ProxyTimeoutError('Proxy connection timed out: {}'.format(timeout)) from e

    async def _connect(
        self,
        dest_host: str,
        dest_port: int,
        dest_ssl: Optional[ssl.SSLContext] = None,
        local_host: Optional[str] = None,
    ) -> AnyioSocketStream:
        if self._forward is None:
            try:
                stream = await connect_tcp(
                    host=self._proxy_host,
                    port=self._proxy_port,
                    local_host=local_host,
                )
            except OSError as e:
                raise ProxyConnectionError(
                    e.errno,
                    "Couldn't connect to proxy"
                    f" {self._proxy_host}:{self._proxy_port} [{e.strerror}]",
                ) from e
        else:
            stream = await self._forward.connect(
                dest_host=self._proxy_host,
                dest_port=self._proxy_port,
            )

        try:
            if self._proxy_ssl is not None:
                stream = await stream.start_tls(
                    hostname=self._proxy_host,
                    ssl_context=self._proxy_ssl,
                )

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

            if dest_ssl is not None:
                stream = await stream.start_tls(
                    hostname=dest_host,
                    ssl_context=dest_ssl,
                )
        except ReplyError as e:
            await stream.close()
            raise ProxyError(e, error_code=e.error_code)
        except BaseException:
            with anyio.CancelScope(shield=True):
                await stream.close()
            raise

        return stream

    @classmethod
    def create(cls, *args, **kwargs):  # for backward compatibility
        return cls(*args, **kwargs)

    @classmethod
    def from_url(cls, url: str, **kwargs) -> 'AnyioProxy':
        url_args = parse_proxy_url(url)
        return cls(*url_args, **kwargs)
