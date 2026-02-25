from typing import Any, Optional
import warnings
import curio
import curio.io

from ..._types import ProxyType
from ..._helpers import parse_proxy_url
from ..._errors import ProxyConnectionError, ProxyTimeoutError, ProxyError

from ._stream import CurioSocketStream
from ._resolver import Resolver
from ._connect import connect_tcp

from ..._protocols.errors import ReplyError
from ..._connectors.factory_async import create_connector


DEFAULT_TIMEOUT = 60


class CurioProxy:
    def __init__(
        self,
        proxy_type: ProxyType,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None,
        rdns: Optional[bool] = None,
    ):
        self._proxy_type = proxy_type
        self._proxy_host = host
        self._proxy_port = port
        self._password = password
        self._username = username
        self._rdns = rdns

        self._resolver = Resolver()

    async def connect(
        self,
        dest_host: str,
        dest_port: int,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> curio.io.Socket:
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
            return await curio.timeout_after(
                timeout,
                self._connect,
                dest_host,
                dest_port,
                _socket,
                local_addr,
            )
        except curio.TaskTimeout as e:
            raise ProxyTimeoutError(f'Proxy connection timed out: {timeout}') from e

    async def _connect(
        self,
        dest_host: str,
        dest_port: int,
        _socket=None,
        local_addr=None,
    ):
        if _socket is None:
            try:
                _socket = await connect_tcp(
                    host=self._proxy_host,
                    port=self._proxy_port,
                    local_addr=local_addr,
                )
            except OSError as e:
                msg = 'Could not connect to proxy {}:{} [{}]'.format(
                    self._proxy_host,
                    self._proxy_port,
                    e.strerror,
                )
                raise ProxyConnectionError(e.errno, msg) from e

        stream = CurioSocketStream(_socket)

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
        except BaseException:
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
    def from_url(cls, url: str, **kwargs) -> 'CurioProxy':
        url_args = parse_proxy_url(url)
        return cls(*url_args, **kwargs)
