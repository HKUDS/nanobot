import hashlib
import json
from typing import Optional, Callable, Any

from lark_oapi.core.const import *
from lark_oapi.core.enum import LogLevel
from lark_oapi.core.exception import InvalidArgsException, AccessDeniedException, CardException, \
    NoAuthorizationException
from lark_oapi.core.http import HttpHandler
from lark_oapi.core.json import JSON
from lark_oapi.core.log import logger
from lark_oapi.core.model import RawRequest, RawResponse
from lark_oapi.core.utils import Strings, AESCipher
from .model import Card


class CardActionHandler(HttpHandler):

    def __init__(self) -> None:
        self._encrypt_key: Optional[str] = None
        self._verification_token: Optional[str] = None
        self._processor: Optional[Callable[[Card], Any]] = None

    def do(self, req: RawRequest) -> RawResponse:
        logger.debug(f"card access, uri: {req.uri}, "
                     f"headers: {JSON.marshal(req.headers)}, "
                     f"body: {str(req.body, UTF_8) if req.body is not None else None}")

        resp = RawResponse()
        resp.status_code = 200
        resp.set_content_type(f"{APPLICATION_JSON}; charset=utf-8")

        try:
            if req.body is None:
                raise InvalidArgsException("request body is null")

            # 消息解密
            plaintext = self._decrypt(req.body)

            # 反序列化
            card = JSON.unmarshal(plaintext, Card)
            card.raw = req

            if URL_VERIFICATION == card.type:
                # 验证回调地址
                # 校验 token
                if self._verification_token != card.token:
                    raise AccessDeniedException("invalid verification_token")

                # 返回 Challenge Code
                resp_body = "{\"challenge\":\"%s\"}" % card.challenge
                resp.content = resp_body.encode(UTF_8)
                return resp
            else:
                # 否则验签
                self._verify_sign(req)

            if self._processor is None:
                raise CardException("processor not found")

            # 处理业务逻辑
            result: Any = self._processor(card)

            # 返回结果
            if result is None:
                resp.content = "{\"msg\":\"success\"}".encode(UTF_8)
            elif isinstance(result, bytes):
                resp.content = result
            elif isinstance(result, str):
                resp.content = bytes(result, UTF_8)
            elif isinstance(result, RawResponse):
                resp = result
            else:
                resp.content = JSON.marshal(result).encode(UTF_8)

            return resp

        except Exception as e:
            logger.exception(
                f"handle card failed, uri: {req.uri}, request_id: {req.headers.get(X_REQUEST_ID)}, err: {e}")
            resp.status_code = 500
            resp_body = "{\"msg\":\"%s\"}" % str(e)
            resp.content = resp_body.encode(UTF_8)

            return resp

    def _decrypt(self, content: bytes) -> str:
        plaintext: str
        encrypt = json.loads(content).get("encrypt")
        if Strings.is_not_empty(encrypt):
            if Strings.is_empty(self._encrypt_key):
                raise NoAuthorizationException("encrypt_key not found")
            plaintext = AESCipher(self._encrypt_key).decrypt_str(encrypt)
        else:
            plaintext = str(content, UTF_8)

        return plaintext

    def _verify_sign(self, request: RawRequest) -> None:
        if self._verification_token is None or self._verification_token == "":
            return
        timestamp = request.headers.get(LARK_REQUEST_TIMESTAMP)
        nonce = request.headers.get(LARK_REQUEST_NONCE)
        signature = request.headers.get(LARK_REQUEST_SIGNATURE)
        bs = (timestamp + nonce + self._verification_token).encode(UTF_8) + request.body
        h = hashlib.sha1(bs)
        if signature != h.hexdigest():
            raise AccessDeniedException("signature verification failed")

    @staticmethod
    def builder(encrypt_key: str, verification_token: str, level: LogLevel = None) -> "CardActionHandlerBuilder":
        if level is not None:
            logger.setLevel(int(level.value))
        return CardActionHandlerBuilder(encrypt_key, verification_token)


class CardActionHandlerBuilder(object):
    def __init__(self, encrypt_key: str, verification_token: str) -> None:
        self._encrypt_key = encrypt_key
        self._verification_token = verification_token
        self._processor: Optional[Callable[[Card], Any]] = None

    def register(self, f: Callable[[Card], Any]) -> "CardActionHandlerBuilder":
        self._processor = f
        return self

    def build(self) -> CardActionHandler:
        card_action_handler = CardActionHandler()
        card_action_handler._encrypt_key = self._encrypt_key
        card_action_handler._verification_token = self._verification_token
        card_action_handler._processor = self._processor
        return card_action_handler
