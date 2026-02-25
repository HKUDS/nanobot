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
"""This module contains two objects that represent a Telegram bots (short) description."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class BotDescription(TelegramObject):
    """This object represents the bot's description.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`description` is equal.

    .. versionadded:: 20.2

    Args:
        description (:obj:`str`): The bot's description.

    Attributes:
        description (:obj:`str`): The bot's description.

    """

    __slots__ = ("description",)

    def __init__(self, description: str, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.description: str = description

        self._id_attrs = (self.description,)

        self._freeze()


class BotShortDescription(TelegramObject):
    """This object represents the bot's short description.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`short_description` is equal.

    .. versionadded:: 20.2

    Args:
        short_description (:obj:`str`): The bot's short description.

    Attributes:
        short_description (:obj:`str`): The bot's short description.

    """

    __slots__ = ("short_description",)

    def __init__(self, short_description: str, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.short_description: str = short_description

        self._id_attrs = (self.short_description,)

        self._freeze()
