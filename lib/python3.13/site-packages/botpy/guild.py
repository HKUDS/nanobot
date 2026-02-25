from .api import BotAPI
from .types import guild


class Guild:
    __slots__ = (
        "_api",
        "_ctx",
        "id",
        "name",
        "icon",
        "owner_id",
        "is_owner",
        "member_count",
        "max_members",
        "description",
        "joined_at",
        "event_id"
    )

    def __init__(self, api: BotAPI, event_id, data: guild.GuildPayload):
        self._api = api

        self.id = data.get("id", None)
        self.name = data.get("name", None)
        self.icon = data.get("icon", None)
        self.owner_id = data.get("owner_id", None)
        self.is_owner = data.get("owner", None)
        self.member_count = data.get("member_count", None)
        self.max_members = data.get("max_members", None)
        self.description = data.get("description", None)
        self.joined_at = data.get("joined_at", None)
        self.event_id = event_id

    def __repr__(self):
        return str({items: str(getattr(self, items)) for items in self.__slots__ if not items.startswith('_')})
