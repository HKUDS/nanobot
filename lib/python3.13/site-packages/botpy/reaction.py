from .api import BotAPI
from .types import reaction


class Reaction:
    __slots__ = (
        "_api",
        "_ctx",
        "user_id",
        "channel_id",
        "guild_id",
        "emoji",
        "target",
        "event_id")

    def __init__(self, api: BotAPI, event_id, data: reaction.Reaction):
        self._api = api

        self.user_id = data.get("user_id", None)
        self.channel_id = data.get("channel_id", None)
        self.guild_id = data.get("guild_id", None)
        self.emoji = self._Emoji(data.get("emoji", {}))
        self.target = self._Target(data.get("target", {}))
        self.event_id = event_id

    def __repr__(self):
        return str({items: str(getattr(self, items)) for items in self.__slots__ if not items.startswith('_')})

    class _Emoji:
        def __init__(self, data):
            self.id = data.get("id", None)
            self.type = data.get("type", None)

        def __repr__(self):
            return str(self.__dict__)

    class _Target:
        def __init__(self, data):
            self.id = data.get("id", None)
            self.type = data.get("type", None)   # 0: 消息 1: 帖子 2: 评论 3: 回复

        def __repr__(self):
            return str(self.__dict__)
