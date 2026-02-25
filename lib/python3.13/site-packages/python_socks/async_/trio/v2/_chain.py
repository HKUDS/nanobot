from typing import Sequence
import warnings
from ._proxy import TrioProxy


class ProxyChain:
    def __init__(self, proxies: Sequence[TrioProxy]):
        warnings.warn(
            'This implementation of ProxyChain is deprecated and will be removed in the future',
            DeprecationWarning,
            stacklevel=2,
        )
        self._proxies = proxies

    async def connect(
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

        return await forward.connect(
            dest_host=dest_host,
            dest_port=dest_port,
            dest_ssl=dest_ssl,
            timeout=timeout,
        )
