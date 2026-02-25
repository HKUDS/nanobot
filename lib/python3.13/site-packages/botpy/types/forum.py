from typing import TypedDict, Literal, List
from botpy.types.rich_text import AuditType

# 1：普通文本 2：HTML 3：Markdown 4： json
Format = Literal[1, 2, 3, 4]


class ThreadInfo(TypedDict):
    thread_id: str
    title: str
    content: str
    date_time: str


class Thread(TypedDict):
    guild_id: str
    channel_id: str
    author_id: str
    thread_info: ThreadInfo


class PostInfo(TypedDict):
    thread_id: str
    post_id: str
    content: str
    date_time: str


class Post(TypedDict):
    guild_id: str
    channel_id: str
    author_id: str
    post_info: PostInfo


class ReplyInfo(TypedDict):
    thread_id: str
    post_id: str
    reply_id: str
    content: str
    date_time: str


class Reply(TypedDict):
    guild_id: str
    channel_id: str
    author_id: str
    reply_info: ReplyInfo


class AuditResult(TypedDict):
    guild_id: str
    channel_id: str
    author_id: str
    thread_id: str
    post_id: str
    reply_id: str
    type: AuditType
    result: int
    err_msg: str


class ForumRsp(TypedDict):
    threads: List[Thread]
    is_finish: int


class PostThreadRsp(TypedDict):
    task_id: str
    create_time: str

class OpenForumEvent(TypedDict):
    guild_id: str
    channel_id: str
    author_id: str
