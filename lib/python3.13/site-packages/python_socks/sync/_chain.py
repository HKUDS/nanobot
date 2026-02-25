from typing import Iterable
import warnings
from ._proxy import SyncProxy


class ProxyChain:
    def __init__(self, proxies: Iterable[SyncProxy]):
        warnings.warn(
            'This implementation of ProxyChain is deprecated and will be removed in the future',
            DeprecationWarning,
            stacklevel=2,
        )
        self._proxies = proxies

    def connect(self, dest_host, dest_port, timeout=None):
        curr_socket = None
        proxies = list(self._proxies)

        length = len(proxies) - 1
        for i in range(length):
            curr_socket = proxies[i].connect(
                dest_host=proxies[i + 1].proxy_host,
                dest_port=proxies[i + 1].proxy_port,
                timeout=timeout,
                _socket=curr_socket,
            )

        curr_socket = proxies[length].connect(
            dest_host=dest_host, dest_port=dest_port, timeout=timeout, _socket=curr_socket
        )

        return curr_socket
