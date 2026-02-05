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
"""This module contains objects related to Telegram forum topics."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class ForumTopic(TelegramObject):
    """
    This object represents a forum topic.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`message_thread_id`, :attr:`name` and :attr:`icon_color`
    are equal.

    .. versionadded:: 20.0

    Args:
        message_thread_id (:obj:`int`): Unique identifier of the forum topic
        name (:obj:`str`): Name of the topic
        icon_color (:obj:`int`): Color of the topic icon in RGB format
        icon_custom_emoji_id (:obj:`str`, optional): Unique identifier of the custom emoji shown
            as the topic icon.
        is_name_implicit (:obj:`bool`, optional): :obj:`True`, if the name of the topic wasn't
            specified explicitly by its creator and likely needs to be changed by the bot.

            .. versionadded:: 22.6

    Attributes:
        message_thread_id (:obj:`int`): Unique identifier of the forum topic
        name (:obj:`str`): Name of the topic
        icon_color (:obj:`int`): Color of the topic icon in RGB format
        icon_custom_emoji_id (:obj:`str`): Optional. Unique identifier of the custom emoji shown
            as the topic icon.
        is_name_implicit (:obj:`bool`): Optional. :obj:`True`, if the name of the topic wasn't
            specified explicitly by its creator and likely needs to be changed by the bot.

            .. versionadded:: 22.6
    """

    __slots__ = (
        "icon_color",
        "icon_custom_emoji_id",
        "is_name_implicit",
        "message_thread_id",
        "name",
    )

    def __init__(
        self,
        message_thread_id: int,
        name: str,
        icon_color: int,
        icon_custom_emoji_id: str | None = None,
        is_name_implicit: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.message_thread_id: int = message_thread_id
        self.name: str = name
        self.icon_color: int = icon_color
        self.icon_custom_emoji_id: str | None = icon_custom_emoji_id
        self.is_name_implicit: bool | None = is_name_implicit

        self._id_attrs = (self.message_thread_id, self.name, self.icon_color)

        self._freeze()


class ForumTopicCreated(TelegramObject):
    """
    This object represents the content of a service message about a new forum topic created in
    the chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`name` and :attr:`icon_color` are equal.

    .. versionadded:: 20.0

    Args:
        name (:obj:`str`): Name of the topic
        icon_color (:obj:`int`): Color of the topic icon in RGB format
        icon_custom_emoji_id (:obj:`str`, optional): Unique identifier of the custom emoji shown
            as the topic icon.
        is_name_implicit (:obj:`bool`, optional): :obj:`True`, if the name of the topic wasn't
            specified explicitly by its creator and likely needs to be changed by the bot.

            .. versionadded:: 22.6

    Attributes:
        name (:obj:`str`): Name of the topic
        icon_color (:obj:`int`): Color of the topic icon in RGB format
        icon_custom_emoji_id (:obj:`str`): Optional. Unique identifier of the custom emoji shown
            as the topic icon.
        is_name_implicit (:obj:`bool`): Optional. :obj:`True`, if the name of the topic wasn't
            specified explicitly by its creator and likely needs to be changed by the bot.

            .. versionadded:: 22.6
    """

    __slots__ = ("icon_color", "icon_custom_emoji_id", "is_name_implicit", "name")

    def __init__(
        self,
        name: str,
        icon_color: int,
        icon_custom_emoji_id: str | None = None,
        is_name_implicit: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.name: str = name
        self.icon_color: int = icon_color
        self.icon_custom_emoji_id: str | None = icon_custom_emoji_id
        self.is_name_implicit: bool | None = is_name_implicit

        self._id_attrs = (self.name, self.icon_color)

        self._freeze()


class ForumTopicClosed(TelegramObject):
    """
    This object represents a service message about a forum topic closed in the chat.
    Currently holds no information.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None) -> None:
        super().__init__(api_kwargs=api_kwargs)

        self._freeze()


class ForumTopicReopened(TelegramObject):
    """
    This object represents a service message about a forum topic reopened in the chat.
    Currently holds no information.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None) -> None:
        super().__init__(api_kwargs=api_kwargs)

        self._freeze()


class ForumTopicEdited(TelegramObject):
    """
    This object represents a service message about an edited forum topic.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`name` and :attr:`icon_custom_emoji_id` are equal.

    .. versionadded:: 20.0

    Args:
        name (:obj:`str`, optional): New name of the topic, if it was edited.
        icon_custom_emoji_id (:obj:`str`, optional): New identifier of the custom emoji shown as
            the topic icon, if it was edited; an empty string if the icon was removed.

    Attributes:
        name (:obj:`str`): Optional. New name of the topic, if it was edited.
        icon_custom_emoji_id (:obj:`str`): Optional. New identifier of the custom emoji shown as
            the topic icon, if it was edited; an empty string if the icon was removed.
    """

    __slots__ = ("icon_custom_emoji_id", "name")

    def __init__(
        self,
        name: str | None = None,
        icon_custom_emoji_id: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.name: str | None = name
        self.icon_custom_emoji_id: str | None = icon_custom_emoji_id

        self._id_attrs = (self.name, self.icon_custom_emoji_id)

        self._freeze()


class GeneralForumTopicHidden(TelegramObject):
    """
    This object represents a service message about General forum topic hidden in the chat.
    Currently holds no information.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)

        self._freeze()


class GeneralForumTopicUnhidden(TelegramObject):
    """
    This object represents a service message about General forum topic unhidden in the chat.
    Currently holds no information.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)

        self._freeze()
