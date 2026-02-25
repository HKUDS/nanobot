# -*- coding: utf-8 -*-
from enum import Enum
from typing import List, TypedDict


class RecommendChannel(TypedDict):
    channel_id: str
    introduce: str


class AnnouncesType(Enum):
    MEMBER = 0  # 成员公告
    WELCOME = 1  # 欢迎公告

    def __int__(self) -> int:
        return self.value


class Announce(TypedDict):
    guild_id: str
    channel_id: str
    message_id: str
    announces_type: AnnouncesType
    recommend_channels: List[RecommendChannel]
