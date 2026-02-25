import socket
import ssl
from typing import Any, Optional

from ._connect import connect_tcp
from ._stream import SyncSocketStream
from .._resolver import SyncResolver
from ..._types import ProxyType
from ..._errors import ProxyConnectionError, ProxyTimeoutError, ProxyError
from ..._helpers import parse_proxy_url

from ..._protocols.errors import ReplyError
from ..._connectors.factory_sync import create_connector


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
        proxy_ssl: Optional[ssl.SSLContext] = None,
        forward: Optional['SyncProxy'] = None,
    ):
        self._proxy_type = proxy_type
        self._proxy_host = host
        self._proxy_port = port
        self._username = username
        self._password = password
        self._rdns = rdns
        self._proxy_ssl = proxy_ssl
        self._forward = forward

        self._resolver = SyncResolver()

    def connect(
        self,
        dest_host: str,
        dest_port: int,
        dest_ssl: Optional[ssl.SSLContext] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> SyncSocketStream:
        if timeout is None:
            timeout = DEFAULT_TIMEOUT

        if self._forward is None:
            local_addr = kwargs.get('local_addr')
            try:
                stream = connect_tcp(
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
        else:
            stream = self._forward.connect(
                dest_host=self._proxy_host,
                dest_port=self._proxy_port,
                timeout=timeout,
            )

        try:
            if self._proxy_ssl is not None:
                stream = stream.start_tls(
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
            connector.connect(
                stream=stream,
                host=dest_host,
                port=dest_port,
            )

            if dest_ssl is not None:
                stream = stream.start_tls(
                    hostname=dest_host,
                    ssl_context=dest_ssl,
                )

            return stream

        except socket.timeout as e:
            stream.close()
            raise ProxyTimeoutError(f'Proxy connection timed out: {timeout}') from e
        except ReplyError as e:
            stream.close()
            raise ProxyError(e, error_code=e.error_code)
        except Exception:
            stream.close()
            raise

    @classmethod
    def create(cls, *args, **kwargs):  # for backward compatibility
        return cls(*args, **kwargs)

    @classmethod
    def from_url(cls, url: str, **kwargs) -> 'SyncProxy':
        url_args = parse_proxy_url(url)
        return cls(*url_args, **kwargs)
