# -*- coding: utf-8 -*-
from enum import Enum
from typing import TypedDict


class ChannelType(Enum):
    TEXT_CHANNEL = 0  # 文字子频道
    # x_CHANNEL = 1    # 保留，不可用
    VOICE_CHANNEL = 2  # 语音子频道
    # x_CHANNEL = 3    # 保留，不可用
    GROUP_CHANNEL = 4  # 子频道分组
    LIVE_CHANNEL = 10005  # 直播子频道
    APP_CHANNEL = 10006  # 应用子频道
    DISCUSSION_CHANNEL = 10007  # 论坛子频道

    def __int__(self) -> int:
        return self.value


class ChannelSubType(Enum):
    TALK = 0  # 闲聊
    POST = 1  # 公告
    CHEAT = 2  # 攻略
    BLACK = 3  # 开黑

    def __int__(self) -> int:
        return self.value


class PrivateType(Enum):
    PUBLIC = 0  # 公开频道
    ADMIN = 1  # 管理员和群主可见
    SPECIFIED_USER = 2  # 群主管理员+指定成员，可使用 修改子频道权限接口 指定成员

    def __int__(self) -> int:
        return self.value


class SpeakPermission(Enum):
    INVALID = 0  # 无效类型
    EVERYONE = 1  # 所有人
    ADMIN = 2  # 群主管理员+指定成员，可使用 修改子频道权限接口 指定成员

    def __int__(self) -> int:
        return self.value


class ChannelPayload(TypedDict):
    id: str
    guild_id: str
    name: str
    type: ChannelType
    sub_type: ChannelSubType
    position: int
    parent_id: str
    owner_id: str
    private_type: PrivateType
    speak_permission: SpeakPermission
    application_id: str
    permissions: str


class ChannelPermissions(TypedDict):
    channel_id: str
    user_id: str
    permissions: str
    role_id: str
