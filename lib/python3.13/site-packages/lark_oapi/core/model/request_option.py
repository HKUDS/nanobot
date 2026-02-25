from typing import Optional, Dict


class RequestOption(object):
    def __init__(self):
        self.app_ticket: Optional[str] = None
        self.tenant_key: Optional[str] = None  # 租户key, app_type = ISV 时需配置
        self.user_access_token: Optional[str] = None
        self.tenant_access_token: Optional[str] = None
        self.app_access_token: Optional[str] = None
        self.headers: Dict[str, str] = {}

    @staticmethod
    def builder() -> "RequestOptionBuilder":
        return RequestOptionBuilder()


class RequestOptionBuilder(object):

    def __init__(self) -> None:
        self._request_option: RequestOption = RequestOption()

    def app_ticket(self, app_ticket: str) -> "RequestOptionBuilder":
        self._request_option.app_ticket = app_ticket
        return self

    def tenant_key(self, tenant_key: str) -> "RequestOptionBuilder":
        self._request_option.tenant_key = tenant_key
        return self

    def user_access_token(self, user_access_token: str) -> "RequestOptionBuilder":
        self._request_option.user_access_token = user_access_token
        return self

    def tenant_access_token(self, tenant_access_token: str) -> "RequestOptionBuilder":
        self._request_option.tenant_access_token = tenant_access_token
        return self

    def app_access_token(self, app_access_token: str) -> "RequestOptionBuilder":
        self._request_option.app_access_token = app_access_token
        return self

    def headers(self, headers: Dict[str, str]) -> "RequestOptionBuilder":
        self._request_option.headers = headers
        return self

    def build(self) -> RequestOption:
        return self._request_option
