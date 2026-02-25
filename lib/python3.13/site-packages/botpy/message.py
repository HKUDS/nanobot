from .api import BotAPI
from .types import gateway


class Message:
    __slots__ = (
        "_api",
        "author",
        "content",
        "channel_id",
        "id",
        "guild_id",
        "member",
        "message_reference",
        "mentions",
        "attachments",
        "seq",
        "seq_in_channel",
        "timestamp",
        "event_id",
    )

    def __init__(self, api: BotAPI, event_id, data: gateway.MessagePayload):
        # TODO 创建一些实体类的数据缓存 @veehou
        self._api = api

        self.author = self._User(data.get("author", {}))
        self.channel_id = data.get("channel_id", None)
        self.id = data.get("id", None)
        self.content = data.get("content", None)
        self.guild_id = data.get("guild_id", None)
        self.member = self._Member(data.get("member", {}))
        self.message_reference = self._MessageRef(data.get("message_reference", {}))
        self.mentions = [self._User(items) for items in data.get("mentions", {})]
        self.attachments = [self._Attachments(items) for items in data.get("attachments", {})]
        self.seq = data.get("seq", None)  # 全局消息序号
        self.seq_in_channel = data.get("seq_in_channel", None)  # 子频道消息序号
        self.timestamp = data.get("timestamp", None)
        self.event_id = event_id

    def __repr__(self):
        return str({items: str(getattr(self, items)) for items in self.__slots__ if not items.startswith("_")})

    class _User:
        def __init__(self, data):
            self.id = data.get("id", None)
            self.username = data.get("username", None)
            self.bot = data.get("bot", None)
            self.avatar = data.get("avatar", None)

        def __repr__(self):
            return str(self.__dict__)

    class _Member:
        def __init__(self, data):
            self.nick = data.get("nick", None)
            self.roles = data.get("roles", None)
            self.joined_at = data.get("joined_at", None)

        def __repr__(self):
            return str(self.__dict__)

    class _MessageRef:
        def __init__(self, data):
            self.message_id = data.get("message_id", None)

        def __repr__(self):
            return str(self.__dict__)

    class _Attachments:
        def __init__(self, data):
            self.content_type = data.get("content_type", None)
            self.filename = data.get("filename", None)
            self.height = data.get("height", None)
            self.width = data.get("width", None)
            self.id = data.get("id", None)
            self.size = data.get("size", None)
            self.url = data.get("url", None)

        def __repr__(self):
            return str(self.__dict__)

    async def reply(self, **kwargs):
        return await self._api.post_message(channel_id=self.channel_id, msg_id=self.id, **kwargs)


class DirectMessage:
    __slots__ = (
        "_api",
        "author",
        "content",
        "direct_message",
        "channel_id",
        "id",
        "guild_id",
        "member",
        "message_reference",
        "attachments",
        "seq",
        "seq_in_channel",
        "src_guild_id",
        "timestamp",
        "event_id",
    )

    def __init__(self, api: BotAPI, event_id, data: gateway.DirectMessagePayload):
        self._api = api

        self.author = self._User(data.get("author", {}))
        self.channel_id = data.get("channel_id", None)
        self.id = data.get("id", None)
        self.content = data.get("content", None)
        self.direct_message = data.get("direct_message", None)
        self.guild_id = data.get("guild_id", None)
        self.member = self._Member(data.get("member", {}))
        self.message_reference = self._MessageRef(data.get("message_reference", {}))
        self.attachments = [self._Attachments(items) for items in data.get("attachments", {})]
        self.seq = data.get("seq", None)  # 全局消息序号
        self.seq_in_channel = data.get("seq_in_channel", None)  # 子频道消息序号
        self.src_guild_id = data.get("src_guild_id", None)
        self.timestamp = data.get("timestamp", None)
        self.event_id = event_id

    def __repr__(self):
        return str({items: str(getattr(self, items)) for items in self.__slots__ if not items.startswith("_")})

    class _User:
        def __init__(self, data):
            self.id = data.get("id", None)
            self.username = data.get("username", None)
            self.avatar = data.get("avatar", None)

        def __repr__(self):
            return str(self.__dict__)

    class _Member:
        def __init__(self, data):
            self.joined_at = data.get("joined_at", None)

        def __repr__(self):
            return str(self.__dict__)

    class _MessageRef:
        def __init__(self, data):
            self.message_id = data.get("message_id", None)

        def __repr__(self):
            return str(self.__dict__)

    class _Attachments:
        def __init__(self, data):
            self.content_type = data.get("content_type", None)
            self.filename = data.get("filename", None)
            self.height = data.get("height", None)
            self.width = data.get("width", None)
            self.id = data.get("id", None)
            self.size = data.get("size", None)
            self.url = data.get("url", None)

        def __repr__(self):
            return str(self.__dict__)

    async def reply(self, **kwargs):
        return await self._api.post_dms(guild_id=self.guild_id, msg_id=self.id, **kwargs)


class MessageAudit:
    __slots__ = (
        "_api",
        "audit_id",
        "message_id",
        "channel_id",
        "guild_id",
        "event_id",
    )

    def __init__(self, api: BotAPI, event_id, data: gateway.MessageAuditPayload):
        self._api = api

        self.audit_id = data.get("audit_id", None)
        self.channel_id = data.get("channel_id", None)
        self.message_id = data.get("message_id", None)
        self.guild_id = data.get("guild_id", None)
        self.event_id = event_id

    def __repr__(self):
        return str({items: str(getattr(self, items)) for items in self.__slots__ if not items.startswith("_")})


class BaseMessage:
    __slots__ = (
        "_api",
        "content",
        "id",
        "message_reference",
        "mentions",
        "attachments",
        "msg_seq",
        "timestamp",
        "event_id",
    )

    def __init__(self, api: BotAPI, event_id, data: gateway.MessagePayload):
        self._api = api
        self.id = data.get("id", None)
        self.content = data.get("content", None)
        self.message_reference = self._MessageRef(data.get("message_reference", {}))
        self.mentions = [self._User(items) for items in data.get("mentions", {})]
        self.attachments = [self._Attachments(items) for items in data.get("attachments", {})]
        self.msg_seq = data.get("msg_seq", None)  # 全局消息序号
        self.timestamp = data.get("timestamp", None)
        self.event_id = event_id

    def __repr__(self):
        return str({items: str(getattr(self, items)) for items in self.__slots__ if not items.startswith("_")})

    class _MessageRef:
        def __init__(self, data):
            self.message_id = data.get("message_id", None)

        def __repr__(self):
            return str(self.__dict__)

    class _Attachments:
        def __init__(self, data):
            self.content_type = data.get("content_type", None)
            self.filename = data.get("filename", None)
            self.height = data.get("height", None)
            self.width = data.get("width", None)
            self.id = data.get("id", None)
            self.size = data.get("size", None)
            self.url = data.get("url", None)

        def __repr__(self):
            return str(self.__dict__)


class GroupMessage(BaseMessage):
    __slots__ = (
        "author",
        "group_openid",
    )

    def __init__(self, api: BotAPI, event_id, data: gateway.MessagePayload):
        super().__init__(api, event_id, data)
        self.author = self._User(data.get("author", {}))
        self.group_openid = data.get("group_openid", None)

    def __repr__(self):
        slots = self.__slots__ + super().__slots__
        return str({items: str(getattr(self, items)) for items in slots if not items.startswith("_")})

    class _User:
        def __init__(self, data):
            self.member_openid = data.get("member_openid", None)

        def __repr__(self):
            return str(self.__dict__)

    async def reply(self, **kwargs):
        return await self._api.post_group_message(group_openid=self.group_openid, msg_id=self.id, **kwargs)
    
class C2CMessage(BaseMessage):
    __slots__ = ("author",)

    def __init__(self, api: BotAPI, event_id, data: gateway.MessagePayload):
        super().__init__(api, event_id, data)

        self.author = self._User(data.get("author", {}))

    def __repr__(self):
        slots = self.__slots__ + super().__slots__
        return str({items: str(getattr(self, items)) for items in slots if not items.startswith("_")})

    class _User:
        def __init__(self, data):
            self.user_openid = data.get("user_openid", None)

        def __repr__(self):
            return str(self.__dict__)

    async def reply(self, **kwargs):
        return await self._api.post_c2c_message(openid=self.author.user_openid, msg_id=self.id, **kwargs)
