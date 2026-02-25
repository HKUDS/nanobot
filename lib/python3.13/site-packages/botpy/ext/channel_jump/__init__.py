# -*- coding: utf-8 -*-
"""
对子频道转跳进行操作(#name)
注意:
1、发送格式要求严格(#name )，自动添加的空格不能删除
2、无法识别真假转跳
3、当子频道重名时无法准确识别
4、当提供子频道转跳字段时请弃用本模块
"""

__all__ = [
    "get_channel_jump",
    "get_channel_jump_strict",
    "escape_channel_jump"
]

import re
from typing import List, Dict

from botpy import BotAPI
from botpy.message import Message


def get_channel_jump(text: str = None, message: Message = None) -> List[str]:
    """
    识别文本中的子频道转跳(粗略)
    :param message: 消息对象
    :param text: 文本，为空则message.content
    :return: 子频道名称列表(不带#)
    """
    channel_jump_re = re.compile(r"#(.{1,12}?)(?= )")
    return channel_jump_re.findall(message.content if text is None else text)


async def get_channel_jump_strict(api: BotAPI, message: Message = None, text: str = None,
                                  guild_id: str = None) -> Dict[str, str]:
    """
    识别文本中的子频道转跳(准确)
    :param api: BotAPI
    :param message: 消息对象
    :param text: 文本，为空则message.content
    :param guild_id: 频道id，为空则message.guild_id
    :return: {子频道名称(不带#):子频道id} （去重）
    """
    channels = await api.get_channels(guild_id or message.guild_id)
    text = message.content if text is None else text
    jumps = {}

    for channel in channels:
        if "#%s " % channel["name"] in text:
            jumps[channel["name"]] = channel["id"]

    return jumps


async def escape_channel_jump(api: BotAPI, message: Message = None, text: str = None, guild_id: str = None) -> str:
    """
    转义子频道转跳 (#name -> <#id>)
    :param api: BotAPI
    :param message: 消息对象
    :param text: 文本，为空则message.content
    :param guild_id: 频道id，为空则message.guild_id
    :return: 转义后的文本
    """
    channels = await api.get_channels(guild_id or message.guild_id)
    text = message.content if text is None else text

    for channel in channels:
        text = text.replace("#%s " % channel["name"], "<#%s> " % channel["id"])

    return text
