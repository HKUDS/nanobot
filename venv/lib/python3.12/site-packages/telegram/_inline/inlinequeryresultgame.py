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
"""This module contains the classes that represent Telegram InlineQueryResultGame."""

from telegram._inline.inlinekeyboardmarkup import InlineKeyboardMarkup
from telegram._inline.inlinequeryresult import InlineQueryResult
from telegram._utils.types import JSONDict
from telegram.constants import InlineQueryResultType


class InlineQueryResultGame(InlineQueryResult):
    """Represents a :class:`telegram.Game`.

    Args:
        id (:obj:`str`): Unique identifier for this result,
            :tg-const:`telegram.InlineQueryResult.MIN_ID_LENGTH`-
            :tg-const:`telegram.InlineQueryResult.MAX_ID_LENGTH` Bytes.
        game_short_name (:obj:`str`): Short name of the game.
        reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): Inline keyboard attached
            to the message.

    Attributes:
        type (:obj:`str`): :tg-const:`telegram.constants.InlineQueryResultType.GAME`.
        id (:obj:`str`): Unique identifier for this result,
            :tg-const:`telegram.InlineQueryResult.MIN_ID_LENGTH`-
            :tg-const:`telegram.InlineQueryResult.MAX_ID_LENGTH` Bytes.
        game_short_name (:obj:`str`): Short name of the game.
        reply_markup (:class:`telegram.InlineKeyboardMarkup`): Optional. Inline keyboard attached
            to the message.

    """

    __slots__ = ("game_short_name", "reply_markup")

    def __init__(
        self,
        id: str,  # pylint: disable=redefined-builtin
        game_short_name: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        # Required
        super().__init__(InlineQueryResultType.GAME, id, api_kwargs=api_kwargs)
        with self._unfrozen():
            self.id: str = id
            self.game_short_name: str = game_short_name

            self.reply_markup: InlineKeyboardMarkup | None = reply_markup
