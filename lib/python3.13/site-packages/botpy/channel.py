from .api import BotAPI
from .types import channel


class Channel:
    __slots__ = (
        "_api",
        "guild_id",
        "id",
        "name",
        "type",
        "sub_type",
        "position",
        "owner_id",
        "private_type",
        "speak_permission",
        "application_id",
        "permissions",
        "event_id",
    )

    def __init__(self, api: BotAPI, event_id, data: channel.ChannelPayload):
        self._api = api

        self.id = data.get("id", None)
        self.name = data.get("name", None)
        self.type = data.get("type", None)
        self.sub_type = data.get("sub_type", None)
        self.position = data.get("position", None)
        self.owner_id = data.get("owner_id", None)
        self.private_type = data.get("private_type", None)
        self.speak_permission = data.get("speak_permission", None)
        self.application_id = data.get("application_id", None)
        self.permissions = data.get("permissions", None)
        self.event_id = event_id

    def __repr__(self):
        return str({items: str(getattr(self, items)) for items in self.__slots__ if not items.startswith('_')})
