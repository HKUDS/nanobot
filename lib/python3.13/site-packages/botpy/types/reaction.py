from typing import TypedDict, Literal, List

from .emoji import Emoji
from .user import User

# 0: 消息 1: 帖子 2: 评论 3: 回复
ReactionTargetType = Literal[0, 1, 2, 3]


class ReactionTarget(TypedDict):
    id: str
    type: ReactionTargetType


class Reaction(TypedDict):
    user_id: str
    guild_id: str
    channel_id: str
    target: ReactionTarget
    emoji: Emoji


class ReactionUsers(TypedDict):
    users: List[User]
    cookie: str  # 分页参数，用于拉取下一页
    is_end: bool  # 是否已拉取完成到最后一页，true代表完成
