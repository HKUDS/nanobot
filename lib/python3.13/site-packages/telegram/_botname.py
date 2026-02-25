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
"""This module contains an object that represent a Telegram bots name."""

from typing import Final

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class BotName(TelegramObject):
    """This object represents the bot's name.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`name` is equal.

    .. versionadded:: 20.3

    Args:
        name (:obj:`str`): The bot's name.

    Attributes:
        name (:obj:`str`): The bot's name.

    """

    __slots__ = ("name",)

    def __init__(self, name: str, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.name: str = name

        self._id_attrs = (self.name,)

        self._freeze()

    MAX_LENGTH: Final[int] = constants.BotNameLimit.MAX_NAME_LENGTH
    """:const:`telegram.constants.BotNameLimit.MAX_NAME_LENGTH`"""
