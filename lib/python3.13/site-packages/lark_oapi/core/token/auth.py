from lark_oapi.core.exception import NoAuthorizationException
from lark_oapi.core.model import *
from lark_oapi.core.utils import Strings
from .manager import TokenManager


def verify(config: Config, request: BaseRequest, option: RequestOption) -> None:
    # 接口无需token
    if len(request.token_types) == 0:
        return

    # 如开启token配置，需手动传入token
    if config.enable_set_token:
        if Strings.is_not_empty(option.tenant_access_token) and AccessTokenType.TENANT in request.token_types:
            request.token_types = {AccessTokenType.TENANT}
            return
        if Strings.is_not_empty(option.app_access_token) and AccessTokenType.APP in request.token_types:
            request.token_types = {AccessTokenType.APP}
            return
        if Strings.is_not_empty(option.user_access_token) and AccessTokenType.USER in request.token_types:
            request.token_types = {AccessTokenType.USER}
            return

    # 未开启token配置，根据app_id/app_secret获取token
    if Strings.is_empty(config.app_id) or Strings.is_empty(config.app_secret):
        raise NoAuthorizationException("app_id or app_secret not found")

    if AccessTokenType.TENANT in request.token_types:
        tenant_access_token: str
        if AppType.SELF == config.app_type:
            tenant_access_token = TokenManager.get_self_tenant_token(config)
        else:
            if Strings.is_empty(option.tenant_key):
                raise NoAuthorizationException("tenant_key not found")
            tenant_access_token = TokenManager.get_isv_tenant_token(config, option.tenant_key, option.app_ticket)
        option.tenant_access_token = tenant_access_token
        request.token_types = {AccessTokenType.TENANT}
        return

    if AccessTokenType.APP in request.token_types:
        app_access_token: str
        if AppType.SELF == config.app_type:
            app_access_token = TokenManager.get_self_app_token(config)
        else:
            app_access_token = TokenManager.get_isv_app_token(config, option.app_ticket)
        option.app_access_token = app_access_token
        request.token_types = {AccessTokenType.APP}
        return

    if AccessTokenType.APP in request.token_types:
        if Strings.is_empty(option.user_access_token):
            raise NoAuthorizationException("user_access_token not found")
        raise NoAuthorizationException("need enable set token")
