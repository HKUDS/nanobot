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
"""This module contains the classes that represent Telegram MessageOigin."""

import datetime as dtm
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._chat import Chat
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils import enum
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class MessageOrigin(TelegramObject):
    """
    Base class for telegram MessageOrigin object, it can be one of:

    * :class:`MessageOriginUser`
    * :class:`MessageOriginHiddenUser`
    * :class:`MessageOriginChat`
    * :class:`MessageOriginChannel`

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` and :attr:`date` are equal.

    .. versionadded:: 20.8

    Args:
        type (:obj:`str`): Type of the message origin, can be on of:
            :attr:`~telegram.MessageOrigin.USER`, :attr:`~telegram.MessageOrigin.HIDDEN_USER`,
            :attr:`~telegram.MessageOrigin.CHAT`, or :attr:`~telegram.MessageOrigin.CHANNEL`.
        date (:obj:`datetime.datetime`): Date the message was sent originally.
            |datetime_localization|

    Attributes:
        type (:obj:`str`): Type of the message origin, can be on of:
            :attr:`~telegram.MessageOrigin.USER`, :attr:`~telegram.MessageOrigin.HIDDEN_USER`,
            :attr:`~telegram.MessageOrigin.CHAT`, or :attr:`~telegram.MessageOrigin.CHANNEL`.
        date (:obj:`datetime.datetime`): Date the message was sent originally.
            |datetime_localization|
    """

    __slots__ = (
        "date",
        "type",
    )

    USER: Final[str] = constants.MessageOriginType.USER
    """:const:`telegram.constants.MessageOriginType.USER`"""
    HIDDEN_USER: Final[str] = constants.MessageOriginType.HIDDEN_USER
    """:const:`telegram.constants.MessageOriginType.HIDDEN_USER`"""
    CHAT: Final[str] = constants.MessageOriginType.CHAT
    """:const:`telegram.constants.MessageOriginType.CHAT`"""
    CHANNEL: Final[str] = constants.MessageOriginType.CHANNEL
    """:const:`telegram.constants.MessageOriginType.CHANNEL`"""

    def __init__(
        self,
        type: str,  # pylint: disable=W0622
        date: dtm.datetime,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required by all subclasses
        self.type: str = enum.get_member(constants.MessageOriginType, type, type)
        self.date: dtm.datetime = date

        self._id_attrs = (
            self.type,
            self.date,
        )
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "MessageOrigin":
        """Converts JSON data to the appropriate :class:`MessageOrigin` object, i.e. takes
        care of selecting the correct subclass.
        """
        data = cls._parse_data(data)

        _class_mapping: dict[str, type[MessageOrigin]] = {
            cls.USER: MessageOriginUser,
            cls.HIDDEN_USER: MessageOriginHiddenUser,
            cls.CHAT: MessageOriginChat,
            cls.CHANNEL: MessageOriginChannel,
        }
        if cls is MessageOrigin and data.get("type") in _class_mapping:
            return _class_mapping[data.pop("type")].de_json(data=data, bot=bot)

        loc_tzinfo = extract_tzinfo_from_defaults(bot)
        data["date"] = from_timestamp(data.get("date"), tzinfo=loc_tzinfo)

        if "sender_user" in data:
            data["sender_user"] = de_json_optional(data.get("sender_user"), User, bot)

        if "sender_chat" in data:
            data["sender_chat"] = de_json_optional(data.get("sender_chat"), Chat, bot)

        if "chat" in data:
            data["chat"] = de_json_optional(data.get("chat"), Chat, bot)

        return super().de_json(data=data, bot=bot)


class MessageOriginUser(MessageOrigin):
    """
    The message was originally sent by a known user.

    .. versionadded:: 20.8

    Args:
        date (:obj:`datetime.datetime`): Date the message was sent originally.
            |datetime_localization|
        sender_user (:class:`telegram.User`): User that sent the message originally.

    Attributes:
        type (:obj:`str`): Type of the message origin. Always
            :tg-const:`~telegram.MessageOrigin.USER`.
        date (:obj:`datetime.datetime`): Date the message was sent originally.
            |datetime_localization|
        sender_user (:class:`telegram.User`): User that sent the message originally.
    """

    __slots__ = ("sender_user",)

    def __init__(
        self,
        date: dtm.datetime,
        sender_user: User,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.USER, date=date, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.sender_user: User = sender_user


class MessageOriginHiddenUser(MessageOrigin):
    """
    The message was originally sent by an unknown user.

    .. versionadded:: 20.8

    Args:
        date (:obj:`datetime.datetime`): Date the message was sent originally.
            |datetime_localization|
        sender_user_name (:obj:`str`): Name of the user that sent the message originally.

    Attributes:
        type (:obj:`str`): Type of the message origin. Always
            :tg-const:`~telegram.MessageOrigin.HIDDEN_USER`.
        date (:obj:`datetime.datetime`): Date the message was sent originally.
            |datetime_localization|
        sender_user_name (:obj:`str`): Name of the user that sent the message originally.
    """

    __slots__ = ("sender_user_name",)

    def __init__(
        self,
        date: dtm.datetime,
        sender_user_name: str,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.HIDDEN_USER, date=date, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.sender_user_name: str = sender_user_name


class MessageOriginChat(MessageOrigin):
    """
    The message was originally sent on behalf of a chat to a group chat.

    .. versionadded:: 20.8

    Args:
        date (:obj:`datetime.datetime`): Date the message was sent originally.
            |datetime_localization|
        sender_chat (:class:`telegram.Chat`): Chat that sent the message originally.
        author_signature (:obj:`str`, optional): For messages originally sent by an anonymous chat
            administrator, original message author signature

    Attributes:
        type (:obj:`str`): Type of the message origin. Always
            :tg-const:`~telegram.MessageOrigin.CHAT`.
        date (:obj:`datetime.datetime`): Date the message was sent originally.
            |datetime_localization|
        sender_chat (:class:`telegram.Chat`): Chat that sent the message originally.
        author_signature (:obj:`str`): Optional. For messages originally sent by an anonymous chat
            administrator, original message author signature
    """

    __slots__ = (
        "author_signature",
        "sender_chat",
    )

    def __init__(
        self,
        date: dtm.datetime,
        sender_chat: Chat,
        author_signature: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.CHAT, date=date, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.sender_chat: Chat = sender_chat
            self.author_signature: str | None = author_signature


class MessageOriginChannel(MessageOrigin):
    """
    The message was originally sent to a channel chat.

    .. versionadded:: 20.8

    Args:
        date (:obj:`datetime.datetime`): Date the message was sent originally.
            |datetime_localization|
        chat (:class:`telegram.Chat`): Channel chat to which the message was originally sent.
        message_id (:obj:`int`): Unique message identifier inside the chat.
        author_signature (:obj:`str`, optional): Signature of the original post author.

    Attributes:
        type (:obj:`str`): Type of the message origin. Always
            :tg-const:`~telegram.MessageOrigin.CHANNEL`.
        date (:obj:`datetime.datetime`): Date the message was sent originally.
            |datetime_localization|
        chat (:class:`telegram.Chat`): Channel chat to which the message was originally sent.
        message_id (:obj:`int`): Unique message identifier inside the chat.
        author_signature (:obj:`str`): Optional. Signature of the original post author.
    """

    __slots__ = (
        "author_signature",
        "chat",
        "message_id",
    )

    def __init__(
        self,
        date: dtm.datetime,
        chat: Chat,
        message_id: int,
        author_signature: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.CHANNEL, date=date, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.chat: Chat = chat
            self.message_id: int = message_id
            self.author_signature: str | None = author_signature
