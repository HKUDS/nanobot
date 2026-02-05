#!/usr/bin/env python
#
# A library that provides a Python interface to the Telegram Bot API
# Copyright (C) 2015-2026
# Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Lesser Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].
# pylint: disable=redefined-builtin
"""This module contains objects representing Telegram bot command scopes."""

from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class BotCommandScope(TelegramObject):
    """Base class for objects that represent the scope to which bot commands are applied.
    Currently, the following 7 scopes are supported:

    * :class:`telegram.BotCommandScopeDefault`
    * :class:`telegram.BotCommandScopeAllPrivateChats`
    * :class:`telegram.BotCommandScopeAllGroupChats`
    * :class:`telegram.BotCommandScopeAllChatAdministrators`
    * :class:`telegram.BotCommandScopeChat`
    * :class:`telegram.BotCommandScopeChatAdministrators`
    * :class:`telegram.BotCommandScopeChatMember`

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is equal. For subclasses with additional attributes,
    the notion of equality is overridden.

    Note:
        Please see the `official docs`_ on how Telegram determines which commands to display.

    .. _`official docs`: https://core.telegram.org/bots/api#determining-list-of-commands

    .. versionadded:: 13.7

    Args:
        type (:obj:`str`): Scope type.

    Attributes:
        type (:obj:`str`): Scope type.
    """

    __slots__ = ("type",)

    DEFAULT: Final[str] = constants.BotCommandScopeType.DEFAULT
    """:const:`telegram.constants.BotCommandScopeType.DEFAULT`"""
    ALL_PRIVATE_CHATS: Final[str] = constants.BotCommandScopeType.ALL_PRIVATE_CHATS
    """:const:`telegram.constants.BotCommandScopeType.ALL_PRIVATE_CHATS`"""
    ALL_GROUP_CHATS: Final[str] = constants.BotCommandScopeType.ALL_GROUP_CHATS
    """:const:`telegram.constants.BotCommandScopeType.ALL_GROUP_CHATS`"""
    ALL_CHAT_ADMINISTRATORS: Final[str] = constants.BotCommandScopeType.ALL_CHAT_ADMINISTRATORS
    """:const:`telegram.constants.BotCommandScopeType.ALL_CHAT_ADMINISTRATORS`"""
    CHAT: Final[str] = constants.BotCommandScopeType.CHAT
    """:const:`telegram.constants.BotCommandScopeType.CHAT`"""
    CHAT_ADMINISTRATORS: Final[str] = constants.BotCommandScopeType.CHAT_ADMINISTRATORS
    """:const:`telegram.constants.BotCommandScopeType.CHAT_ADMINISTRATORS`"""
    CHAT_MEMBER: Final[str] = constants.BotCommandScopeType.CHAT_MEMBER
    """:const:`telegram.constants.BotCommandScopeType.CHAT_MEMBER`"""

    def __init__(self, type: str, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.type: str = enum.get_member(constants.BotCommandScopeType, type, type)
        self._id_attrs = (self.type,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "BotCommandScope":
        """Converts JSON data to the appropriate :class:`BotCommandScope` object, i.e. takes
        care of selecting the correct subclass.

        Args:
            data (dict[:obj:`str`, ...]): The JSON data.
            bot (:class:`telegram.Bot`, optional): The bot associated with this object. Defaults to
                :obj:`None`, in which case shortcut methods will not be available.

                .. versionchanged:: 21.4
                   :paramref:`bot` is now optional and defaults to :obj:`None`

        Returns:
            The Telegram object.

        """
        data = cls._parse_data(data)

        _class_mapping: dict[str, type[BotCommandScope]] = {
            cls.DEFAULT: BotCommandScopeDefault,
            cls.ALL_PRIVATE_CHATS: BotCommandScopeAllPrivateChats,
            cls.ALL_GROUP_CHATS: BotCommandScopeAllGroupChats,
            cls.ALL_CHAT_ADMINISTRATORS: BotCommandScopeAllChatAdministrators,
            cls.CHAT: BotCommandScopeChat,
            cls.CHAT_ADMINISTRATORS: BotCommandScopeChatAdministrators,
            cls.CHAT_MEMBER: BotCommandScopeChatMember,
        }

        if cls is BotCommandScope and data.get("type") in _class_mapping:
            return _class_mapping[data.pop("type")].de_json(data=data, bot=bot)
        return super().de_json(data=data, bot=bot)


class BotCommandScopeDefault(BotCommandScope):
    """Represents the default scope of bot commands. Default commands are used if no commands with
    a `narrower scope`_ are specified for the user.

    .. _`narrower scope`: https://core.telegram.org/bots/api#determining-list-of-commands

    .. versionadded:: 13.7
    Attributes:
        type (:obj:`str`): Scope type :tg-const:`telegram.BotCommandScope.DEFAULT`.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None):
        super().__init__(type=BotCommandScope.DEFAULT, api_kwargs=api_kwargs)
        self._freeze()


class BotCommandScopeAllPrivateChats(BotCommandScope):
    """Represents the scope of bot commands, covering all private chats.

    .. versionadded:: 13.7

    Attributes:
        type (:obj:`str`): Scope type :tg-const:`telegram.BotCommandScope.ALL_PRIVATE_CHATS`.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None):
        super().__init__(type=BotCommandScope.ALL_PRIVATE_CHATS, api_kwargs=api_kwargs)
        self._freeze()


class BotCommandScopeAllGroupChats(BotCommandScope):
    """Represents the scope of bot commands, covering all group and supergroup chats.

    .. versionadded:: 13.7
    Attributes:
        type (:obj:`str`): Scope type :tg-const:`telegram.BotCommandScope.ALL_GROUP_CHATS`.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None):
        super().__init__(type=BotCommandScope.ALL_GROUP_CHATS, api_kwargs=api_kwargs)
        self._freeze()


class BotCommandScopeAllChatAdministrators(BotCommandScope):
    """Represents the scope of bot commands, covering all group and supergroup chat administrators.

    .. versionadded:: 13.7
    Attributes:
        type (:obj:`str`): Scope type :tg-const:`telegram.BotCommandScope.ALL_CHAT_ADMINISTRATORS`.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None):
        super().__init__(type=BotCommandScope.ALL_CHAT_ADMINISTRATORS, api_kwargs=api_kwargs)
        self._freeze()


class BotCommandScopeChat(BotCommandScope):
    """Represents the scope of bot commands, covering a specific chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` and :attr:`chat_id` are equal.

    .. versionadded:: 13.7

    Args:
        chat_id (:obj:`str` | :obj:`int`): |chat_id_group|

    Attributes:
        type (:obj:`str`): Scope type :tg-const:`telegram.BotCommandScope.CHAT`.
        chat_id (:obj:`str` | :obj:`int`): |chat_id_group|
    """

    __slots__ = ("chat_id",)

    def __init__(self, chat_id: str | int, *, api_kwargs: JSONDict | None = None):
        super().__init__(type=BotCommandScope.CHAT, api_kwargs=api_kwargs)
        with self._unfrozen():
            self.chat_id: str | int = (
                chat_id if isinstance(chat_id, str) and chat_id.startswith("@") else int(chat_id)
            )
            self._id_attrs = (self.type, self.chat_id)


class BotCommandScopeChatAdministrators(BotCommandScope):
    """Represents the scope of bot commands, covering all administrators of a specific group or
    supergroup chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` and :attr:`chat_id` are equal.

    .. versionadded:: 13.7

    Args:
        chat_id (:obj:`str` | :obj:`int`): |chat_id_group|
    Attributes:
        type (:obj:`str`): Scope type :tg-const:`telegram.BotCommandScope.CHAT_ADMINISTRATORS`.
        chat_id (:obj:`str` | :obj:`int`): |chat_id_group|
    """

    __slots__ = ("chat_id",)

    def __init__(self, chat_id: str | int, *, api_kwargs: JSONDict | None = None):
        super().__init__(type=BotCommandScope.CHAT_ADMINISTRATORS, api_kwargs=api_kwargs)
        with self._unfrozen():
            self.chat_id: str | int = (
                chat_id if isinstance(chat_id, str) and chat_id.startswith("@") else int(chat_id)
            )
            self._id_attrs = (self.type, self.chat_id)


class BotCommandScopeChatMember(BotCommandScope):
    """Represents the scope of bot commands, covering a specific member of a group or supergroup
    chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type`, :attr:`chat_id` and :attr:`user_id` are equal.

    .. versionadded:: 13.7

    Args:
        chat_id (:obj:`str` | :obj:`int`): |chat_id_group|
        user_id (:obj:`int`): Unique identifier of the target user.

    Attributes:
        type (:obj:`str`): Scope type :tg-const:`telegram.BotCommandScope.CHAT_MEMBER`.
        chat_id (:obj:`str` | :obj:`int`): |chat_id_group|
        user_id (:obj:`int`): Unique identifier of the target user.
    """

    __slots__ = ("chat_id", "user_id")

    def __init__(self, chat_id: str | int, user_id: int, *, api_kwargs: JSONDict | None = None):
        super().__init__(type=BotCommandScope.CHAT_MEMBER, api_kwargs=api_kwargs)
        with self._unfrozen():
            self.chat_id: str | int = (
                chat_id if isinstance(chat_id, str) and chat_id.startswith("@") else int(chat_id)
            )
            self.user_id: int = user_id
            self._id_attrs = (self.type, self.chat_id, self.user_id)
