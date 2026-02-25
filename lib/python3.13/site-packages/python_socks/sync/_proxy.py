import socket
from typing import Optional, Any
import warnings

from .._errors import ProxyConnectionError, ProxyTimeoutError, ProxyError

from .._types import ProxyType
from .._helpers import parse_proxy_url
from .._protocols.errors import ReplyError
from .._connectors.factory_sync import create_connector

from ._stream import SyncSocketStream
from ._resolver import SyncResolver
from ._connect import connect_tcp


DEFAULT_TIMEOUT = 60


class SyncProxy:
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

        self._resolver = SyncResolver()

    def connect(
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

        if _socket is None:
            local_addr = kwargs.get('local_addr')
            try:
                _socket = connect_tcp(
                    host=self._proxy_host,
                    port=self._proxy_port,
                    timeout=timeout,
                    local_addr=local_addr,
                )
            except OSError as e:
                msg = 'Could not connect to proxy {}:{} [{}]'.format(
                    self._proxy_host,
                    self._proxy_port,
                    e.strerror,
                )
                raise ProxyConnectionError(e.errno, msg) from e

        stream = SyncSocketStream(_socket)

        try:
            connector = create_connector(
                proxy_type=self._proxy_type,
                username=self._username,
                password=self._password,
                rdns=self._rdns,
                resolver=self._resolver,
            )
            connector.connect(
                stream=stream,
                host=dest_host,
                port=dest_port,
            )

            return _socket
        except socket.timeout as e:
            stream.close()
            raise ProxyTimeoutError('Proxy connection timed out: {}'.format(timeout)) from e
        except ReplyError as e:
            stream.close()
            raise ProxyError(e, error_code=e.error_code)
        except Exception:
            stream.close()
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
    def from_url(cls, url: str, **kwargs) -> 'SyncProxy':
        url_args = parse_proxy_url(url)
        return cls(*url_args, **kwargs)
