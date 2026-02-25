from typing import Optional

from lark_oapi.core import HttpMethod
from lark_oapi.core.model import BaseRequest
from .create_token_request_body import CreateTokenRequestBody


class CreateSelfAppTokenRequest(BaseRequest):

    def __init__(self) -> None:
        super().__init__()
        self.request_body: Optional[CreateTokenRequestBody] = None

    @staticmethod
    def builder() -> "CreateSelfAppTokenRequestBuilder":
        return CreateSelfAppTokenRequestBuilder()


class CreateSelfAppTokenRequestBuilder(object):

    def __init__(
            self,
            create_self_app_token_request: CreateSelfAppTokenRequest = CreateSelfAppTokenRequest()
    ) -> None:
        create_self_app_token_request.http_method = HttpMethod.POST
        create_self_app_token_request.uri = "/open-apis/auth/v3/app_access_token/internal"
        self.__create_self_app_token_request: CreateSelfAppTokenRequest = create_self_app_token_request

    def request_body(self, request_body: CreateTokenRequestBody) -> "CreateSelfAppTokenRequestBuilder":
        self.__create_self_app_token_request.request_body = request_body
        self.__create_self_app_token_request.body = request_body
        return self

    def build(self) -> CreateSelfAppTokenRequest:
        return self.__create_self_app_token_request
