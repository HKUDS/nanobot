from typing import Iterable
from ._proxy import SyncProxy


class ProxyChain:
    def __init__(self, proxies: Iterable[SyncProxy]):
        self._proxies = proxies

    def connect(
        self,
        dest_host,
        dest_port,
        dest_ssl=None,
        timeout=None,
    ):
        forward = None
        for proxy in self._proxies:
            proxy._forward = forward
            forward = proxy

        return forward.connect(
            dest_host=dest_host,
            dest_port=dest_port,
            dest_ssl=dest_ssl,
            timeout=timeout,
        )
