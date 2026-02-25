# -*- coding: utf-8 -*-
from typing import TypedDict


class APIPermission(TypedDict):
    path: str
    method: str
    desc: str
    auth_status: int


class APIPermissionDemandIdentify(TypedDict):
    path: str
    method: str


class APIPermissionDemand(TypedDict):
    guild_id: str
    channel_id: str
    api_identify: APIPermissionDemandIdentify
    title: str
    desc: str
