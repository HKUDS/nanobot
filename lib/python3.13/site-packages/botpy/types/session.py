from typing import TypedDict

from ..robot import Token


class ShardConfig(TypedDict):
    shard_id: int
    shard_count: int


class Session(TypedDict):
    session_id: str
    last_seq: int
    intent: int
    token: Token
    url: str
    shards: ShardConfig
