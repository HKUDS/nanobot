from lark_oapi.core import JSON, Strings
from lark_oapi.core.cache import *
from lark_oapi.core.const import UTF_8
from lark_oapi.core.exception import ObtainAccessTokenException
from lark_oapi.core.http import Transport
from lark_oapi.core.model import Config, RawResponse
from .access_token_response import AccessTokenResponse
from .create_isv_app_token_request import CreateIsvAppTokenRequest
from .create_isv_tenant_token_request import CreateIsvTenantTokenRequest
from .create_self_app_token_request import CreateSelfAppTokenRequest
from .create_self_tenant_token_request import CreateSelfTenantTokenRequest
from .create_token_request_body import CreateTokenRequestBody


class TokenManager(object):
    cache: ICache = LocalCache.instance()

    @staticmethod
    def get_self_app_token(conf: Config) -> str:
        # 读缓存
        cache_key = f"self_app_token:{conf.app_id}"
        token = TokenManager.cache.get(cache_key)
        if Strings.is_not_empty(token):
            return token

        # 缓存不存在则发起请求获取token
        req: CreateSelfAppTokenRequest = CreateSelfAppTokenRequest.builder() \
            .request_body(CreateTokenRequestBody.builder()
                          .app_id(conf.app_id)
                          .app_secret(conf.app_secret)
                          .build()) \
            .build()
        raw: RawResponse = Transport.execute(conf, req)
        resp = JSON.unmarshal(str(raw.content, UTF_8), AccessTokenResponse)

        if not resp.success():
            raise ObtainAccessTokenException("obtain self app access token failed", resp.code, resp.msg)

        # 写缓存
        token = resp.app_access_token
        expire = time.time() + resp.expire - 10 * 60  # 提前10分钟过期
        TokenManager.cache.set(cache_key, token, int(expire))

        return token

    @staticmethod
    def get_self_tenant_token(config: Config) -> str:
        # 读缓存
        cache_key = f"self_tenant_token:{config.app_id}"
        token = TokenManager.cache.get(cache_key)
        if Strings.is_not_empty(token):
            return token

        # 缓存不存在则发起请求获取token
        req: CreateSelfTenantTokenRequest = CreateSelfTenantTokenRequest.builder() \
            .request_body(CreateTokenRequestBody.builder()
                          .app_id(config.app_id)
                          .app_secret(config.app_secret)
                          .build()) \
            .build()
        raw: RawResponse = Transport.execute(config, req)
        resp = JSON.unmarshal(str(raw.content, UTF_8), AccessTokenResponse)

        if not resp.success():
            raise ObtainAccessTokenException("obtain self tenant access token failed", resp.code, resp.msg)

        # 写缓存
        token = resp.tenant_access_token
        expire = time.time() + resp.expire - 10 * 60  # 提前10分钟过期
        TokenManager.cache.set(cache_key, token, int(expire))

        return token

    @staticmethod
    def get_isv_app_token(config: Config, app_ticket: str) -> str:
        # 读缓存
        cache_key = f"isv_app_token:{config.app_id}"
        token = TokenManager.cache.get(cache_key)
        if Strings.is_not_empty(token):
            return token

        if Strings.is_empty(app_ticket):
            # TODO: get app ticket from ticket cache
            pass

        # 缓存不存在则发起请求获取token
        req: CreateIsvAppTokenRequest = CreateIsvAppTokenRequest.builder() \
            .request_body(CreateTokenRequestBody.builder()
                          .app_id(config.app_id)
                          .app_secret(config.app_secret)
                          .app_ticket(app_ticket).build()) \
            .build()
        raw: RawResponse = Transport.execute(config, req)
        resp = JSON.unmarshal(str(raw.content, UTF_8), AccessTokenResponse)

        if not resp.success():
            raise ObtainAccessTokenException("obtain isv app access token failed", resp.code, resp.msg)

        # 写缓存
        token = resp.app_access_token
        expire = time.time() + resp.expire - 10 * 60  # 提前10分钟过期
        TokenManager.cache.set(cache_key, token, int(expire))

        return token

    @staticmethod
    def get_isv_tenant_token(config: Config, tenant_key: str, app_ticket: str) -> str:
        # 读缓存
        cache_key = f"isv_tenant_token:{config.app_id}:{tenant_key}"
        token = TokenManager.cache.get(cache_key)
        if Strings.is_not_empty(token):
            return token

        app_token = TokenManager.get_isv_app_token(config, app_ticket)
        # 缓存不存在则发起请求获取token
        req: CreateIsvTenantTokenRequest = CreateIsvTenantTokenRequest.builder() \
            .request_body(CreateTokenRequestBody.builder()
                          .app_access_token(app_token)
                          .tenant_key(tenant_key).build()) \
            .build()
        raw: RawResponse = Transport.execute(config, req)
        resp = JSON.unmarshal(str(raw.content, UTF_8), AccessTokenResponse)

        if not resp.success():
            raise ObtainAccessTokenException("obtain isv tenant access token failed", resp.code, resp.msg)

        # 写缓存
        token = resp.tenant_access_token
        expire = time.time() + resp.expire - 10 * 60  # 提前10分钟过期
        TokenManager.cache.set(cache_key, token, int(expire))

        return token
