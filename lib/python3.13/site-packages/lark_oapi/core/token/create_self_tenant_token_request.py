from typing import Optional

from lark_oapi.core import HttpMethod
from lark_oapi.core.model import BaseRequest
from .create_token_request_body import CreateTokenRequestBody


class CreateSelfTenantTokenRequest(BaseRequest):

    def __init__(self) -> None:
        super().__init__()
        self.request_body: Optional[CreateTokenRequestBody] = None

    @staticmethod
    def builder() -> "CreateSelfTenantTokenRequestBuilder":
        return CreateSelfTenantTokenRequestBuilder()


class CreateSelfTenantTokenRequestBuilder(object):

    def __init__(
            self,
            create_self_tenant_token_request: CreateSelfTenantTokenRequest = CreateSelfTenantTokenRequest()
    ) -> None:
        create_self_tenant_token_request.http_method = HttpMethod.POST
        create_self_tenant_token_request.uri = "/open-apis/auth/v3/tenant_access_token/internal"
        self.__create_self_tenant_token_request: CreateSelfTenantTokenRequest = create_self_tenant_token_request

    def request_body(self, request_body: CreateTokenRequestBody) -> "CreateSelfTenantTokenRequestBuilder":
        self.__create_self_tenant_token_request.request_body = request_body
        self.__create_self_tenant_token_request.body = request_body
        return self

    def build(self) -> CreateSelfTenantTokenRequest:
        return self.__create_self_tenant_token_request
