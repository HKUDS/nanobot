from typing import Dict
from .api import BotAPI


class GroupManageEvent:
    __slots__ = (
        "_api",
        "event_id",
        "timestamp",
        "group_openid",
        "op_member_openid",
    )

    def __init__(self, api: BotAPI, event_id, data: Dict):
        self._api = api
        self.event_id = event_id
        self.timestamp = data.get("timestamp", None)
        self.group_openid = data.get("group_openid", None)
        self.op_member_openid = data.get("op_member_openid", None)

    def __repr__(self):
        return str({items: str(getattr(self, items)) for items in self.__slots__ if not items.startswith("_")})


class C2CManageEvent:
    __slots__ = (
        "_api",
        "event_id",
        "timestamp",
        "openid",
    )

    def __init__(self, api: BotAPI, event_id, data: Dict):
        self._api = api
        self.event_id = event_id
        self.timestamp = data.get("timestamp", None)
        self.openid = data.get("openid", None)

    def __repr__(self):
        return str({items: str(getattr(self, items)) for items in self.__slots__ if not items.startswith("_")})
