import asyncio
import time

import aiohttp

from .logging import get_logger
from botpy.types import robot

_log = get_logger()


class Robot:
    def __init__(self, data: robot.Robot):
        self._update(data)

    def _update(self, data: robot.Robot) -> None:
        self.name = data.get("username")
        self.id = int(data["id"])
        self.avatar = data.get("avatar")


class Token:
    TYPE_BOT = "QQBot"
    TYPE_NORMAL = "Bearer"

    def __init__(self, app_id: str, secret: str):
        """
        :param app_id:
            机器人appid
        :param secret:
            机器人密钥
        """
        self.app_id = app_id
        self.secret = secret
        self.access_token = None
        self.expires_in = 0
        self.Type = self.TYPE_BOT

    async def check_token(self):
        if self.access_token is None or int(time.time()) >= self.expires_in:
            await self.update_access_token()

    async def update_access_token(self):
        session = aiohttp.ClientSession()
        data = None
        # TODO 增加超时重试
        try:
            async with session.post(
                url="https://bots.qq.com/app/getAppAccessToken",
                timeout=(aiohttp.ClientTimeout(total=20)),
                json={
                    "appId": self.app_id,
                    "clientSecret": self.secret,
                },
            ) as response:
                data = await response.json()
        except asyncio.TimeoutError as e:
            _log.info("[botpy] access_token TimeoutError:" + str(e))
            raise
        finally:
            await session.close()
        if "access_token" not in data or "expires_in" not in data:
            _log.error("[botpy] 获取token失败，请检查appid和secret填写是否正确！")
            raise RuntimeError(str(data))
        _log.info("[botpy] access_token expires_in " + data["expires_in"])
        self.access_token = data["access_token"]
        self.expires_in = int(data["expires_in"]) + int(time.time())

    # BotToken 机器人身份的 token
    def bot_token(self):
        return self

    # GetString 获取授权头字符串
    def get_string(self):
        if self.Type == self.TYPE_NORMAL:
            return self.access_token
        return "{} {}".format(self.Type, self.access_token)

    def get_type(self):
        return self.Type
