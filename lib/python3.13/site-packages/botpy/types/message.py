# -*- coding: utf-8 -*-
from enum import Enum
from typing import List, TypedDict

from .gateway import MessagePayload
from .inline import Keyboard


class Attachment(TypedDict):
    url: str


class Thumbnail(TypedDict):
    url: str  # 图片地址


class EmbedField(TypedDict):
    name: str


class Embed(TypedDict, total=False):
    title: str  # 标题
    prompt: str  # 消息弹窗内容
    thumbnail: Thumbnail  # 缩略图
    fields: List[EmbedField]  # 消息创建时间


class ArkObjKv(TypedDict):
    key: str
    value: str


class ArkObj(TypedDict):
    obj_kv: List[ArkObjKv]


class ArkKv(TypedDict, total=False):
    key: str
    value: str
    obj: List[ArkObj]


class Ark(TypedDict):
    template_id: int
    kv: List[ArkKv]


class Reference(TypedDict):
    message_id: str
    ignore_get_message_error: bool


class MessageMarkdownParams(TypedDict):
    key: str
    values: List[str]


class MarkdownPayload(TypedDict, total=False):
    custom_template_id: str
    params: List[MessageMarkdownParams]
    content: str


class KeyboardPayload(TypedDict, total=False):
    id: str
    content: Keyboard

class Media(TypedDict):
    file_uuid: str  # 文件ID
    file_info: str  # 文件信息，用于发消息接口的media字段使用
    ttl: int  # 有效期，标识剩余多少秒到期，到期后 file_info 失效，当等于 0 时，表示可长期使用


class Message(MessagePayload):
    edited_timestamp: str
    mention_everyone: str
    attachments: List[Attachment]
    embeds: List[Embed]
    ark: Ark
    message_reference: Reference
    markdown: MarkdownPayload
    keyboard: KeyboardPayload


class TypesEnum(Enum):
    around = "around"
    before = "before"
    after = "after"
    latest = ""


class MessagesPager(TypedDict):
    type: TypesEnum
    id: str
    limit: str


class DmsPayload(TypedDict):
    guild_id: str  # 注意，这里是私信会话的guild_id， 每个私信会话居然是个单独的guild
    channel_id: str
    creat_time: str


class DMOriginalAuthor(TypedDict):
    id: str
    username: str
    bot: bool


class DeletedMessage(TypedDict):
    guild_id: str
    channel_id: str
    id: str
    author: DMOriginalAuthor


class DeletionOperator(TypedDict):
    id: str


class DeletedMessageInfo(TypedDict):
    message: DeletedMessage
    op_user: DeletionOperator
