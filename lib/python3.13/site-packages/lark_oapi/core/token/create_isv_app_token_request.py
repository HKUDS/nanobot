from typing import Optional

from lark_oapi.core import HttpMethod
from lark_oapi.core.model import BaseRequest
from .create_token_request_body import CreateTokenRequestBody


class CreateIsvAppTokenRequest(BaseRequest):

    def __init__(self) -> None:
        super().__init__()
        self.request_body: Optional[CreateTokenRequestBody] = None

    @staticmethod
    def builder() -> "CreateIsvAppTokenRequestBuilder":
        return CreateIsvAppTokenRequestBuilder()


class CreateIsvAppTokenRequestBuilder(object):

    def __init__(
            self,
            create_isv_app_token_request: CreateIsvAppTokenRequest = CreateIsvAppTokenRequest()
    ) -> None:
        create_isv_app_token_request.http_method = HttpMethod.POST
        create_isv_app_token_request.uri = "/open-apis/auth/v3/app_access_token"
        self.__create_isv_app_token_request: CreateIsvAppTokenRequest = create_isv_app_token_request

    def request_body(self, request_body: CreateTokenRequestBody) -> "CreateIsvAppTokenRequestBuilder":
        self.__create_isv_app_token_request.request_body = request_body
        self.__create_isv_app_token_request.body = request_body
        return self

    def build(self) -> CreateIsvAppTokenRequest:
        return self.__create_isv_app_token_request
