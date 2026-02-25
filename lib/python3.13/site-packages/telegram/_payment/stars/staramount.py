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
"""This module contains an object that represents a Telegram StarAmount."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class StarAmount(TelegramObject):
    """Describes an amount of Telegram Stars.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`amount` and :attr:`nanostar_amount` are equal.

    Args:
        amount (:obj:`int`): Integer amount of Telegram Stars, rounded to ``0``; can be negative.
        nanostar_amount (:obj:`int`, optional): The number of
            :tg-const:`telegram.constants.Nanostar.VALUE` shares of Telegram
            Stars; from :tg-const:`telegram.constants.NanostarLimit.MIN_AMOUNT`
            to :tg-const:`telegram.constants.NanostarLimit.MAX_AMOUNT`; can be
            negative if and only if :attr:`amount` is non-positive.

    Attributes:
        amount (:obj:`int`): Integer amount of Telegram Stars, rounded to ``0``; can be negative.
        nanostar_amount (:obj:`int`): Optional. The number of
            :tg-const:`telegram.constants.Nanostar.VALUE` shares of Telegram
            Stars; from :tg-const:`telegram.constants.NanostarLimit.MIN_AMOUNT`
            to :tg-const:`telegram.constants.NanostarLimit.MAX_AMOUNT`; can be
            negative if and only if :attr:`amount` is non-positive.

    """

    __slots__ = ("amount", "nanostar_amount")

    def __init__(
        self,
        amount: int,
        nanostar_amount: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.amount: int = amount
        self.nanostar_amount: int | None = nanostar_amount

        self._id_attrs = (self.amount, self.nanostar_amount)

        self._freeze()
