# -*- coding: utf-8 -*-
from typing import TypedDict, List

from botpy.types.user import User


class GuildPayload(TypedDict):
    id: str
    name: str
    icon: str
    owner_id: str
    owner: bool
    member_count: int
    max_members: int
    description: str
    joined_at: str


class Role(TypedDict):
    id: str
    name: str
    color: int
    hoist: int
    number: int
    number_limit: int


class GuildRole(TypedDict):
    guild_id: str
    role_id: str
    role: Role


class GuildRoles(TypedDict):
    guild_id: str
    roles: List[Role]
    role_num_limit: str


class GuildMembers(TypedDict):
    user: List[User]
    nick: str
    roles: List[Role]
    joined_at: str
