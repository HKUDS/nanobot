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
"""This module contains an object that represents a type of a Telegram Poll."""

from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.types import JSONDict
from telegram.constants import PollType


class KeyboardButtonPollType(TelegramObject):
    """This object represents type of a poll, which is allowed to be created
    and sent when the corresponding button is pressed.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is equal.

    Examples:
        :any:`Poll Bot <examples.pollbot>`

    Args:
        type (:obj:`str`, optional): If :tg-const:`telegram.Poll.QUIZ` is passed, the user will be
            allowed to create only polls in the quiz mode. If :tg-const:`telegram.Poll.REGULAR` is
            passed, only regular polls will be allowed. Otherwise, the user will be allowed to
            create a poll of any type.
    Attributes:
        type (:obj:`str`): Optional. If equals :tg-const:`telegram.Poll.QUIZ`, the user will
            be allowed to create only polls in the quiz mode. If equals
            :tg-const:`telegram.Poll.REGULAR`, only regular polls will be allowed.
            Otherwise, the user will be allowed to create a poll of any type.
    """

    __slots__ = ("type",)

    def __init__(
        self,
        type: str | None = None,  # pylint: disable=redefined-builtin
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.type: str | None = enum.get_member(PollType, type, type)

        self._id_attrs = (self.type,)

        self._freeze()
