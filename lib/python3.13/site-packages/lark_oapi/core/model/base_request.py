from typing import *

from lark_oapi.core import HttpMethod, AccessTokenType


class BaseRequest(object):
    def __init__(self) -> None:
        self.http_method: Optional[HttpMethod] = None
        self.uri: Optional[str] = None
        self.token_types: Set[AccessTokenType] = set()
        self.paths: Dict[str, str] = {}
        self.queries: List[Tuple[str, str]] = []
        self.headers: Dict[str, str] = {}
        self.body: Any = None
        self.files: Optional[Dict] = None

    def add_query(self, k: str, v: Any) -> None:
        if isinstance(v, (list, tuple)):
            for i in v:
                self.queries.append((k, str(i)))
        else:
            self.queries.append((k, str(v)))

    @staticmethod
    def builder() -> "BaseRequestBuilder":
        return BaseRequestBuilder()


class BaseRequestBuilder(object):

    def __init__(self) -> None:
        self._base_request: BaseRequest = BaseRequest()

    def http_method(self, http_method: HttpMethod) -> "BaseRequestBuilder":
        self._base_request.http_method = http_method
        return self

    def uri(self, uri: str) -> "BaseRequestBuilder":
        self._base_request.uri = uri
        return self

    def token_types(self, token_types: Set[AccessTokenType]) -> "BaseRequestBuilder":
        self._base_request.token_types = token_types
        return self

    def paths(self, paths: Dict[str, str]) -> "BaseRequestBuilder":
        self._base_request.paths = paths
        return self

    def queries(self, queries: List[Tuple[str, str]]) -> "BaseRequestBuilder":
        self._base_request.queries = queries
        return self

    def headers(self, headers: Dict[str, str]) -> "BaseRequestBuilder":
        self._base_request.headers = headers
        return self

    def body(self, body: Any) -> "BaseRequestBuilder":
        self._base_request.body = body
        return self

    def build(self) -> BaseRequest:
        return self._base_request
