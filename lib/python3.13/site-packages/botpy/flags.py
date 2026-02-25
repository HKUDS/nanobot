from typing import Callable, overload, Optional, Any, Type, ClassVar, Dict, Iterator, Tuple, TypeVar

__all__ = ("Intents", "Permission")

BF = TypeVar("BF", bound="BaseFlags")


def fill_with_flags(*, inverted: bool = False) -> Callable[[Type[BF]], Type[BF]]:
    def decorator(cls: Type[BF]) -> Type[BF]:
        # fmt: off
        cls.VALID_FLAGS = {
            name: value.flag
            for name, value in cls.__dict__.items()
            if isinstance(value, Flag)
        }
        # fmt: on

        if inverted:
            max_bits = max(cls.VALID_FLAGS.values()).bit_length()
            cls.DEFAULT_VALUE = -1 + (2**max_bits)
        else:
            cls.DEFAULT_VALUE = 0

        return cls

    return decorator


class BaseFlags:
    VALID_FLAGS: ClassVar[Dict[str, int]]
    DEFAULT_VALUE: ClassVar[int]

    value: int

    __slots__ = ("value",)

    def __init__(self, **kwargs: bool):
        self.value = self.DEFAULT_VALUE
        for key, value in kwargs.items():
            if key not in self.VALID_FLAGS:
                raise TypeError(f"{key!r} is not a valid flag name.")
            setattr(self, key, value)

    @classmethod
    def _from_value(cls, value):
        self = cls.__new__(cls)
        self.value = value
        return self

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__) and self.value == other.value

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self.value)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} value={self.value}>"

    def __iter__(self) -> Iterator[Tuple[str, bool]]:
        for name, value in self.__class__.__dict__.items():
            if isinstance(value, Flag):
                yield name, self.has_flag(value.flag)

    def has_flag(self, o: int) -> bool:
        return (self.value & o) == o

    def set_flag(self, o: int, toggle: bool) -> None:
        if toggle is True:
            self.value |= o
        elif toggle is False:
            self.value &= ~o
        else:
            raise TypeError(f"Value to set for {self.__class__.__name__} must be a bool.")


class Flag:
    def __init__(self, func: Callable[[Any], int]):
        self.flag: int = func(None)
        self.__doc__: Optional[str] = func.__doc__

    @overload
    def __get__(self, instance: None, owner: Type[BF]) -> Any:
        ...

    @overload
    def __get__(self, instance: BF, owner: Type[BF]) -> bool:
        ...

    def __get__(self, instance: Optional[BF], owner: Type[BF]) -> Any:
        if instance is None:
            return self
        return instance.has_flag(self.flag)

    def __set__(self, instance: BF, value: bool) -> None:
        instance.set_flag(self.flag, value)

    def __repr__(self) -> str:
        return f"<flag_value flag={self.flag!r}>"


@fill_with_flags()
class Intents(BaseFlags):
    """
    public_messages 群/C2C公域消息事件
    public_guild_messages	公域消息事件
    guild_messages	消息事件 (仅 私域 机器人能够设置此 intents)
    direct_message	私信事件
    guild_message_reactions	消息相关互动事件
    guilds	频道事件
    guild_members	频道成员事件
    interaction	互动事件
    message_audit	消息审核事件
    forums	论坛事件 (仅 私域 机器人能够设置此 intents)
    audio_action	音频事件
    """

    __slots__ = ()

    def __init__(self, **kwargs: bool) -> None:
        super().__init__(**kwargs)
        self.value: int = self.DEFAULT_VALUE
        for key, value in kwargs.items():
            if key not in self.VALID_FLAGS:
                raise TypeError(f"{key!r} is not a valid flag name.")
            setattr(self, key, value)

    @classmethod
    def all(cls):
        """打开所有事件的监听"""
        self = cls.none()
        self.guild_messages = True
        self.forums = True
        self.interaction = True
        self.audio_action = True
        self.guilds = True
        self.guild_members = True
        self.guild_message_reactions = True
        self.direct_message = True
        self.message_audit = True
        self.public_messages = True
        self.public_guild_messages = True
        self.audio_or_live_channel_member = True
        self.open_forum_event = True
        return self

    @classmethod
    def none(cls):
        """不主动打开"""
        self = cls.__new__(cls)
        self.value = self.DEFAULT_VALUE
        return self

    @classmethod
    def default(cls):
        """打开所有公域事件的监听

        `guild_messages` 和 `forums` 需要私域权限
        """
        self = cls.all()
        self.guild_messages = False
        self.forums = False
        return self

    @Flag
    def guilds(self):
        """:class:`bool`: 是否打开频道事件的监听.

        通过增加`client`的`on_xx`成员方法可以获取事件下发的数据:
        `py
        from botpy.guild import Guild

        async def on_guild_create(self, guild: Guild):
            `执行相关的任务`
        `

        - :func:`on_guild_create(self, guild: Guild)`: 当机器人加入新guild时
        - :func:`on_guild_update(self, guild: Guild)`: 当guild资料发生变更时
        - :func:`on_guild_delete(self, guild: Guild)`: 当机器人退出guild时
        - :func:`on_channel_create(self, channel: Channel)`: 当channel被创建时
        - :func:`on_channel_update(self, channel: Channel)`: 当channel被更新时
        - :func:`on_channel_delete(self, channel: Channel)`: 当channel被删除时

        """
        return 1 << 0

    @Flag
    def guild_members(self):
        """:class:`bool`: 是否打开频道成员事件的监听.

        - :func:`on_guild_member_add(self, member:Member)`: 当成员加入时
        - :func:`on_guild_member_update(self, member:Member)`: 当成员资料变更时
        - :func:`on_guild_member_remove(self, member:Member)`: 当成员被移除时

        """
        return 1 << 1

    @Flag
    def guild_messages(self):
        """:class:`bool`: 是否打开消息事件的监听.

        - :func:`on_message_create(self,message:Message)`:
            发送消息事件，代表频道内的全部消息，而不只是 at 机器人的消息。内容与 AT_MESSAGE_CREATE 相同
        - :func:`on_message_delete(self,message:Message)`: 删除（撤回）消息事件

        注意：仅 *私域* 机器人能够设置此 intents
        """
        return 1 << 9

    @Flag
    def guild_message_reactions(self):
        """:class:`bool`: 是否打开消息相关互动事件的监听.

        - :func:`on_message_reaction_add`: 为消息添加表情表态
        - :func:`on_message_reaction_remove`: 为消息删除表情表态

        """
        return 1 << 10

    @Flag
    def direct_message(self):
        """:class:`bool`: 是否打开私信事件的监听.

        - :func:`on_direct_message_create`: 当收到用户发给机器人的私信消息时
        - :func:`on_direct_message_delete `: 删除（撤回）消息事件

        """
        return 1 << 12

    @Flag
    def interaction(self):
        """:class:`bool`: 是否打开互动事件的监听.

        - :func:`on_interaction_create`: 互动事件创建时

        """
        return 1 << 26

    @Flag
    def message_audit(self):
        """:class:`bool`: 是否打开消息审核事件的监听.

        - :func:`on_message_audit_pass`: 消息审核通过
        - :func:`on_message_audit_reject`: 消息审核不通过

        """
        return 1 << 27

    @Flag
    def forums(self):
        """:class:`bool`: 是否打开论坛事件的监听.

        - :func:`on_forum_thread_create`         当用户创建主题时
        - :func:`on_forum_thread_update`         当用户更新主题时
        - :func:`on_forum_thread_delete`         当用户删除主题时
        - :func:`on_forum_post_create`           当用户创建帖子时
        - :func:`on_forum_post_delete`           当用户删除帖子时
        - :func:`on_forum_reply_create`          当用户回复评论时
        - :func:`on_forum_reply_delete`          当用户删除评论时
        - :func:`on_forum_publish_audit_result`  当用户发表审核通过时
        注意：仅 *私域* 机器人能够设置此 intents
        """
        return 1 << 28

    @Flag
    def audio_action(self):
        """:class:`bool`: 是否打开音频事件的监听.

        - :func:`on_audio_start`: 音频开始播放时
        - :func:`on_audio_finish`: 音频播放结束时
        - :func:`on_audio_on_mic`: 上麦时
        - :func:`on_audio_off_mic`: 下麦时

        """
        return 1 << 29

    @Flag
    def public_guild_messages(self):
        """:class:`bool`: 是否打开公域消息事件的监听.

        通过增加`client`的`on_xx`事件可以获取事件下发的数据:

        - :func:`on_at_message_create`            // 当收到@机器人的消息时
        - :func:`on_public_message_delete`        // 当频道的消息被删除时

        """
        return 1 << 30

    @Flag
    def audio_or_live_channel_member(self):
        """:class:`bool`: 是否打开音视频/直播子频道成员进出事件的监听.

        通过增加`client`的`on_xx`事件可以获取事件下发的数据:

        - :func:`on_audio_or_live_channel_enter`            // 用户进入音视频/直播子频道时
        - :func:`on_audio_or_live_channel_exit`        // 用户退出音视频/直播子频道时

        """
        return 1 << 19

    @Flag
    def open_forum_event(self):
        """:class:`bool`: 开放论坛对象事件的监听.

        通过增加`client`的`on_xx`事件可以获取事件下发的数据:


        - :func:`on_open_forum_thread_create`            // 用户创建主题时
        - :func:`on_open_forum_thread_update`            // 用户修改主题时
        - :func:`on_open_forum_thread_delete`            // 用户删除主题时
        - :func:`on_open_forum_post_create`            // 用户创建帖子时
        - :func:`on_open_forum_post_delete`            // 用户删除帖子时
        - :func:`on_open_forum_reply_create`            // 用户回复评论时
        - :func:`on_open_forum_reply_delete`            // 用户删除评论时

        """
        return 1 << 18

    @Flag
    def public_messages(self):
        """:class:`bool`: 是否打开公域群/C2C消息事件的监听.

        通过增加`client`的`on_xx`事件可以获取事件下发的数据:

        - :func:`on_group_at_message_create`            // 当收到群@机器人的消息时
        - :func:`on_c2c_message_create`                 // 当收到c2c的消息时
        - :func:`on_group_add_robot`                    // 机器人加入群聊
        - :func:`on_group_del_robot`                    // 机器人退出群聊
        - :func:`on_group_msg_reject`                   // 群聊拒绝机器人主动消息
        - :func:`on_group_msg_receive`                  // 群聊接受机器人主动消息
        - :func:`on_friend_add`                         // 用户添加机器人
        - :func:`on_friend_del`                         // 用户删除机器人
        - :func:`on_c2c_msg_reject`                     // 用户拒绝机器人主动消息
        - :func:`on_c2c_msg_receive`                    // 用户接受机器人主动消息

        """
        return 1 << 25


@fill_with_flags()
class Permission(BaseFlags):
    def __init__(self, **kwargs: bool) -> None:
        super().__init__(**kwargs)
        self.value: int = self.DEFAULT_VALUE
        for key, value in kwargs.items():
            if key not in self.VALID_FLAGS:
                raise TypeError(f"{key!r} is not a valid flag name.")
            setattr(self, key, value)

    @Flag
    def view_permission(self):
        """可查看子频道	0x0000000001 (1 << 0)	支持指定成员可见类型，支持身份组可见类型"""
        return 1 << 0

    @Flag
    def manager_permission(self):
        """可管理子频道	0x0000000002 (1 << 1)	创建者、管理员、子频道管理员都具有此权限"""
        return 1 << 1

    @Flag
    def speak_permission(self):
        """可发言子频道	0x0000000004 (1 << 2)	支持指定成员发言类型，支持身份组发言类型"""
        return 1 << 2

    @Flag
    def live_permission(self):
        """可直播子频道	0x0000000008 (1 << 3)	支持指定成员发起直播，支持身份组发起直播；仅可在直播子频道中设置"""
        return 1 << 3
