from typing import Optional, Dict

from lark_oapi.core.construct import init


class ClientConfig(object):
    _types = {}

    def __init__(self, d=None):
        self.ReconnectCount: Optional[int] = None
        self.ReconnectInterval: Optional[int] = None
        self.ReconnectNonce: Optional[int] = None
        self.PingInterval: Optional[int] = None
        init(self, d, self._types)


class Endpoint(object):
    _types = {
        "ClientConfig": ClientConfig
    }

    def __init__(self, d=None):
        self.URL: Optional[str] = None
        self.ClientConfig: Optional[ClientConfig] = None
        init(self, d, self._types)


class EndpointResp(object):
    _types = {
        "data": Endpoint
    }

    def __init__(self, d=None):
        self.code: Optional[int] = None
        self.msg: Optional[str] = None
        self.data: Optional[Endpoint] = None
        init(self, d, self._types)


class Response(object):
    def __init__(self, code: int = None, headers: Dict[str, str] = None, data: bytes = None):
        self.code = code
        self.headers = headers
        self.data = data
