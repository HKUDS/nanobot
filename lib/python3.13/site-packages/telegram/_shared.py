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
"""This module contains two objects used for request chats/users service messages."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._files.photosize import PhotoSize
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_list_optional, parse_sequence_arg
from telegram._utils.types import JSONDict
from telegram._utils.usernames import get_full_name, get_link, get_name

if TYPE_CHECKING:
    from telegram._bot import Bot


class UsersShared(TelegramObject):
    """
    This object contains information about the user whose identifier was shared with the bot
    using a :class:`telegram.KeyboardButtonRequestUsers` button.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`request_id` and :attr:`users` are equal.

    .. versionadded:: 20.8
       Bot API 7.0 replaces ``UserShared`` with this class. The only difference is that now
       the ``user_ids`` is a sequence instead of a single integer.

    .. versionchanged:: 21.1
       The argument :attr:`users` is now considered for the equality comparison instead of
       ``user_ids``.

    .. versionremoved:: 21.2
       Removed the deprecated argument and attribute ``user_ids``.

    Args:
        request_id (:obj:`int`): Identifier of the request.
        users (Sequence[:class:`telegram.SharedUser`]): Information about users shared with the
            bot.

            .. versionadded:: 21.1

            .. versionchanged:: 21.2
               This argument is now required.

    Attributes:
        request_id (:obj:`int`): Identifier of the request.
        users (tuple[:class:`telegram.SharedUser`]): Information about users shared with the
            bot.

            .. versionadded:: 21.1
    """

    __slots__ = ("request_id", "users")

    def __init__(
        self,
        request_id: int,
        users: Sequence["SharedUser"],
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.request_id: int = request_id
        self.users: tuple[SharedUser, ...] = parse_sequence_arg(users)

        self._id_attrs = (self.request_id, self.users)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "UsersShared":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["users"] = de_list_optional(data.get("users"), SharedUser, bot)

        api_kwargs = {}
        # This is a deprecated field that TG still returns for backwards compatibility
        # Let's filter it out to speed up the de-json process
        if user_ids := data.get("user_ids"):
            api_kwargs = {"user_ids": user_ids}

        return super()._de_json(data=data, bot=bot, api_kwargs=api_kwargs)


class ChatShared(TelegramObject):
    """
    This object contains information about the chat whose identifier was shared with the bot
    using a :class:`telegram.KeyboardButtonRequestChat` button.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`request_id` and :attr:`chat_id` are equal.

    .. versionadded:: 20.1

    Args:
        request_id (:obj:`int`): Identifier of the request.
        chat_id (:obj:`int`): Identifier of the shared user. This number may be greater than 32
            bits and some programming languages may have difficulty/silent defects in interpreting
            it. But it is smaller than 52 bits, so a signed 64-bit integer or double-precision
            float type are safe for storing this identifier.
        title (:obj:`str`, optional): Title of the chat, if the title was requested by the bot.

            .. versionadded:: 21.1
        username (:obj:`str`, optional): Username of the chat, if the username was requested by
            the bot and available.

            .. versionadded:: 21.1
        photo (Sequence[:class:`telegram.PhotoSize`], optional): Available sizes of the chat photo,
            if the photo was requested by the bot

            .. versionadded:: 21.1

    Attributes:
        request_id (:obj:`int`): Identifier of the request.
        chat_id (:obj:`int`): Identifier of the shared user. This number may be greater than 32
            bits and some programming languages may have difficulty/silent defects in interpreting
            it. But it is smaller than 52 bits, so a signed 64-bit integer or double-precision
            float type are safe for storing this identifier.
        title (:obj:`str`): Optional. Title of the chat, if the title was requested by the bot.

            .. versionadded:: 21.1
        username (:obj:`str`): Optional. Username of the chat, if the username was requested by
            the bot and available.

            .. versionadded:: 21.1
        photo (tuple[:class:`telegram.PhotoSize`]): Optional. Available sizes of the chat photo,
            if the photo was requested by the bot

            .. versionadded:: 21.1
    """

    __slots__ = ("chat_id", "photo", "request_id", "title", "username")

    def __init__(
        self,
        request_id: int,
        chat_id: int,
        title: str | None = None,
        username: str | None = None,
        photo: Sequence[PhotoSize] | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.request_id: int = request_id
        self.chat_id: int = chat_id
        self.title: str | None = title
        self.username: str | None = username
        self.photo: tuple[PhotoSize, ...] | None = parse_sequence_arg(photo)

        self._id_attrs = (self.request_id, self.chat_id)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChatShared":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["photo"] = de_list_optional(data.get("photo"), PhotoSize, bot)
        return super().de_json(data=data, bot=bot)

    @property
    def link(self) -> str | None:
        """:obj:`str`: Convenience property. If :attr:`username` is available, returns a t.me link
        of the chat.

        .. versionadded:: 22.4
        """
        return get_link(self)


class SharedUser(TelegramObject):
    """
    This object contains information about a user that was shared with the bot using a
    :class:`telegram.KeyboardButtonRequestUsers` button.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`user_id` is equal.

    .. versionadded:: 21.1

    Args:
        user_id (:obj:`int`): Identifier of the shared user. This number may have 32 significant
            bits and some programming languages may have difficulty/silent defects in interpreting
            it. But it has atmost 52 significant bits, so 64-bit integers or double-precision
            float types are safe for storing these identifiers. The bot may not have access to the
            user and could be unable to use this identifier, unless the user is already known to
            the bot by some other means.
        first_name (:obj:`str`, optional): First name of the user, if the name was requested by the
            bot.
        last_name (:obj:`str`, optional): Last name of the user, if the name was requested by the
            bot.
        username (:obj:`str`, optional): Username of the user, if the username was requested by the
            bot.
        photo (Sequence[:class:`telegram.PhotoSize`], optional): Available sizes of the chat photo,
            if the photo was requested by the bot.

    Attributes:
        user_id (:obj:`int`): Identifier of the shared user. This number may have 32 significant
            bits and some programming languages may have difficulty/silent defects in interpreting
            it. But it has atmost 52 significant bits, so 64-bit integers or double-precision
            float types are safe for storing these identifiers. The bot may not have access to the
            user and could be unable to use this identifier, unless the user is already known to
            the bot by some other means.
        first_name (:obj:`str`): Optional. First name of the user, if the name was requested by the
            bot.
        last_name (:obj:`str`): Optional. Last name of the user, if the name was requested by the
            bot.
        username (:obj:`str`): Optional. Username of the user, if the username was requested by the
            bot.
        photo (tuple[:class:`telegram.PhotoSize`]): Available sizes of the chat photo, if
            the photo was requested by the bot. This list is empty if the photo was not requsted.
    """

    __slots__ = ("first_name", "last_name", "photo", "user_id", "username")

    def __init__(
        self,
        user_id: int,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
        photo: Sequence[PhotoSize] | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.user_id: int = user_id
        self.first_name: str | None = first_name
        self.last_name: str | None = last_name
        self.username: str | None = username
        self.photo: tuple[PhotoSize, ...] | None = parse_sequence_arg(photo)

        self._id_attrs = (self.user_id,)

        self._freeze()

    @property
    def name(self) -> str | None:
        """:obj:`str`: Convenience property. If available, returns the user's :attr:`username`
        prefixed with "@". If :attr:`username` is not available, returns :attr:`full_name`.

        .. versionadded:: 22.4
        """
        return get_name(self)

    @property
    def full_name(self) -> str | None:
        """:obj:`str`: Convenience property. If :attr:`first_name` is not :obj:`None`, gives
        :attr:`first_name` followed by (if available) :attr:`last_name`.

        .. versionadded:: 22.4
        """
        return get_full_name(self)

    @property
    def link(self) -> str | None:
        """:obj:`str`: Convenience property. If :attr:`username` is available, returns a t.me link
        of the user.

        .. versionadded:: 22.4
        """
        return get_link(self)

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "SharedUser":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["photo"] = de_list_optional(data.get("photo"), PhotoSize, bot)
        return super().de_json(data=data, bot=bot)
