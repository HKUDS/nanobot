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
"""This module contains an object that represents a Telegram WebAppData."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class WebAppData(TelegramObject):
    """Contains data sent from a `Web App <https://core.telegram.org/bots/webapps>`_ to the bot.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`data` and :attr:`button_text` are equal.

    Examples:
        :any:`Webapp Bot <examples.webappbot>`

    .. versionadded:: 20.0

    Args:
        data (:obj:`str`): The data. Be aware that a bad client can send arbitrary data in this
            field.
        button_text (:obj:`str`): Text of the :paramref:`~telegram.KeyboardButton.web_app` keyboard
            button, from which the Web App was opened.

    Attributes:
        data (:obj:`str`): The data. Be aware that a bad client can send arbitrary data in this
            field.
        button_text (:obj:`str`): Text of the :paramref:`~telegram.KeyboardButton.web_app` keyboard
            button, from which the Web App was opened.

            Warning:
                Be aware that a bad client can send arbitrary data in this field.
    """

    __slots__ = ("button_text", "data")

    def __init__(self, data: str, button_text: str, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.data: str = data
        self.button_text: str = button_text

        self._id_attrs = (self.data, self.button_text)

        self._freeze()
