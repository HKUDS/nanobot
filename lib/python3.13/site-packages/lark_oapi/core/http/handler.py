from abc import ABC, abstractmethod

from lark_oapi.core.model import RawRequest, RawResponse


class HttpHandler(ABC):
    @abstractmethod
    def do(self, req: RawRequest) -> RawResponse:
        pass
