from typing import TypedDict, List

from .user import Member


class WsContext(TypedDict):
    id: str  # 被动事件里携带的上下文信息，目前仅有部分事件支持


class UserPayload(TypedDict):
    id: str
    username: str
    bot: bool
    status: int
    avatar: str


class MessageRefPayload(TypedDict):
    message_id: str


class MessageAttachPayload(TypedDict):
    content_type: str
    filename: str
    height: int
    width: int
    id: str
    size: int
    url: str


class ReadyEvent(TypedDict):
    version: int
    session_id: str
    user: UserPayload
    shard: List[int]


class WsUrlPayload(TypedDict):
    url: str


class MessagePayload(TypedDict):
    author: UserPayload
    channel_id: str
    content: str
    guild_id: str
    id: str
    member: Member
    message_reference: MessageRefPayload
    mentions: List[UserPayload]
    attachments: List[MessageAttachPayload]
    seq: int
    seq_in_channel: str
    timestamp: str


class DirectMessagePayload(TypedDict):
    author: UserPayload
    channel_id: str
    content: str
    direct_message: bool
    guild_id: str
    id: str
    member: Member
    message_reference: MessageRefPayload
    attachments: List[MessageAttachPayload]
    seq: int
    seq_in_channel: str
    src_guild_id: str
    timestamp: str


class MessageAuditPayload(TypedDict):
    audit_id: str
    message_id: str
    guild_id: str
    channel_id: str
    audit_time: str
    create_time: str
    seq_in_channel: str
