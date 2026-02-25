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
"""This module contains an object that represents a Telegram CopyTextButton."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class CopyTextButton(TelegramObject):
    """
    This object represents an inline keyboard button that copies specified text to the clipboard.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`text` is equal.

    .. versionadded:: 21.7

    Args:
        text (:obj:`str`): The text to be copied to the clipboard;
            :tg-const:`telegram.constants.InlineKeyboardButtonLimit.MIN_COPY_TEXT`-
            :tg-const:`telegram.constants.InlineKeyboardButtonLimit.MAX_COPY_TEXT` characters

    Attributes:
        text (:obj:`str`): The text to be copied to the clipboard;
            :tg-const:`telegram.constants.InlineKeyboardButtonLimit.MIN_COPY_TEXT`-
            :tg-const:`telegram.constants.InlineKeyboardButtonLimit.MAX_COPY_TEXT` characters

    """

    __slots__ = ("text",)

    def __init__(self, text: str, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.text: str = text

        self._id_attrs = (self.text,)

        self._freeze()
