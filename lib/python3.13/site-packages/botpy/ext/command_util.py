# -*- coding: utf-8 -*-
from functools import wraps
from botpy.message import BaseMessage


class Commands:
    """
    指令装饰器

    Args:
      args (tuple): 字符串元组。
    """

    def __init__(self, *args):
        self.commands = args

    def __call__(self, func):
        @wraps(func)
        async def decorated(*args, **kwargs):
            message: BaseMessage = kwargs["message"]
            for command in self.commands:
                if command in message.content:
                    # 分割指令后面的指令参数
                    params = message.content.split(command)[1].strip()
                    kwargs["params"] = params
                    return await func(*args, **kwargs)
            return False

        return decorated

