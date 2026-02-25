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
# along with this program. If not, see [http://www.gnu.org/licenses/].
"""This module contains an object that describes a price change of a paid message."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class PaidMessagePriceChanged(TelegramObject):
    """Describes a service message about a change in the price of paid messages within a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`paid_message_star_count` is equal.

    .. versionadded:: 22.1

    Args:
        paid_message_star_count (:obj:`int`): The new number of Telegram Stars that must be paid by
            non-administrator users of the supergroup chat for each sent message

    Attributes:
        paid_message_star_count (:obj:`int`): The new number of Telegram Stars that must be paid by
            non-administrator users of the supergroup chat for each sent message
    """

    __slots__ = ("paid_message_star_count",)

    def __init__(
        self,
        paid_message_star_count: int,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.paid_message_star_count: int = paid_message_star_count

        self._id_attrs = (self.paid_message_star_count,)
        self._freeze()
