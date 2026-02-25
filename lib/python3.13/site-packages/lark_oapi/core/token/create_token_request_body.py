from typing import Optional


class CreateTokenRequestBody(object):
    def __init__(self) -> None:
        self.app_id: Optional[str] = None
        self.app_secret: Optional[str] = None
        self.app_ticket: Optional[str] = None
        self.app_access_token: Optional[str] = None
        self.tenant_key: Optional[str] = None

    @staticmethod
    def builder() -> "CreateTokenRequestBodyBuilder":
        return CreateTokenRequestBodyBuilder()


class CreateTokenRequestBodyBuilder(object):
    def __init__(
            self,
            create_token_request_body: CreateTokenRequestBody = CreateTokenRequestBody()
    ) -> None:
        self.__create_token_request_body: CreateTokenRequestBody = create_token_request_body

    def app_id(self, app_id: str) -> "CreateTokenRequestBodyBuilder":
        self.__create_token_request_body.app_id = app_id
        return self

    def app_secret(self, app_secret: str) -> "CreateTokenRequestBodyBuilder":
        self.__create_token_request_body.app_secret = app_secret
        return self

    def app_ticket(self, app_ticket: str) -> "CreateTokenRequestBodyBuilder":
        self.__create_token_request_body.app_ticket = app_ticket
        return self

    def app_access_token(self, app_access_token: str) -> "CreateTokenRequestBodyBuilder":
        self.__create_token_request_body.app_access_token = app_access_token
        return self

    def tenant_key(self, tenant_key: str) -> "CreateTokenRequestBodyBuilder":
        self.__create_token_request_body.tenant_key = tenant_key
        return self

    def build(self) -> "CreateTokenRequestBody":
        return self.__create_token_request_body
