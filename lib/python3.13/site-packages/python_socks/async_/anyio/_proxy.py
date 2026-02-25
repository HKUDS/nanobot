import ssl
from typing import Any, Optional
import warnings

import anyio

from ..._types import ProxyType
from ..._helpers import parse_proxy_url
from ..._errors import ProxyConnectionError, ProxyTimeoutError, ProxyError

from ._resolver import Resolver
from ._stream import AnyioSocketStream
from ._connect import connect_tcp

from ..._protocols.errors import ReplyError
from ..._connectors.factory_async import create_connector

DEFAULT_TIMEOUT = 60


class AnyioProxy:
    _stream: Optional[AnyioSocketStream]

    def __init__(
        self,
        proxy_type: ProxyType,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None,
        rdns: Optional[bool] = None,
        proxy_ssl: Optional[ssl.SSLContext] = None,
    ):
        self._proxy_type = proxy_type
        self._proxy_host = host
        self._proxy_port = port
        self._password = password
        self._username = username
        self._rdns = rdns

        self._proxy_ssl = proxy_ssl
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

        _stream = kwargs.get('_stream')
        if _stream is not None:
            warnings.warn(
                "The '_stream' argument is deprecated and will be removed in the future",
                DeprecationWarning,
                stacklevel=2,
            )

        local_host = kwargs.get('local_host')
        try:
            with anyio.fail_after(timeout):
                if _stream is None:
                    try:
                        _stream = AnyioSocketStream(
                            await connect_tcp(
                                host=self._proxy_host,
                                port=self._proxy_port,
                                local_host=local_host,
                            )
                        )
                    except OSError as e:
                        msg = 'Could not connect to proxy {}:{} [{}]'.format(
                            self._proxy_host,
                            self._proxy_port,
                            e.strerror,
                        )
                        raise ProxyConnectionError(e.errno, msg) from e

                stream = _stream

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

                    return stream
                except ReplyError as e:
                    await stream.close()
                    raise ProxyError(e, error_code=e.error_code)
                except BaseException:
                    await stream.close()
                    raise

        except TimeoutError as e:
            raise ProxyTimeoutError(f'Proxy connection timed out: {timeout}') from e

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
    def from_url(cls, url: str, **kwargs) -> 'AnyioProxy':
        url_args = parse_proxy_url(url)
        return cls(*url_args, **kwargs)
