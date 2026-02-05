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
"""This module contains an object that represents a Telegram Sent Web App Message."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class SentWebAppMessage(TelegramObject):
    """Contains information about an inline message sent by a Web App on behalf of a user.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`inline_message_id` are equal.

    .. versionadded:: 20.0

    Args:
        inline_message_id (:obj:`str`, optional): Identifier of the sent inline message. Available
            only if there is an :attr:`inline keyboard <telegram.InlineKeyboardMarkup>` attached to
            the message.

    Attributes:
        inline_message_id (:obj:`str`): Optional. Identifier of the sent inline message. Available
            only if there is an :attr:`inline keyboard <telegram.InlineKeyboardMarkup>` attached to
            the message.
    """

    __slots__ = ("inline_message_id",)

    def __init__(
        self, inline_message_id: str | None = None, *, api_kwargs: JSONDict | None = None
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Optionals
        self.inline_message_id: str | None = inline_message_id

        self._id_attrs = (self.inline_message_id,)

        self._freeze()
