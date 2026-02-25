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
"""This module contains an object that represents a Telegram LabeledPrice."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class LabeledPrice(TelegramObject):
    """This object represents a portion of the price for goods or services.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`label` and :attr:`amount` are equal.

    Examples:
        :any:`Payment Bot <examples.paymentbot>`

    Args:
        label (:obj:`str`): Portion label.
        amount (:obj:`int`): Price of the product in the smallest units of the currency (integer,
            **not** float/double). For example, for a price of ``US$ 1.45`` pass ``amount = 145``.
            See the ``exp`` parameter in
            `currencies.json <https://core.telegram.org/bots/payments/currencies.json>`_,
            it shows the number of digits past the decimal point for each currency
            (2 for the majority of currencies).

    Attributes:
        label (:obj:`str`): Portion label.
        amount (:obj:`int`): Price of the product in the smallest units of the currency (integer,
            **not** float/double). For example, for a price of ``US$ 1.45`` pass ``amount = 145``.
            See the ``exp`` parameter in
            `currencies.json <https://core.telegram.org/bots/payments/currencies.json>`_,
            it shows the number of digits past the decimal point for each currency
            (2 for the majority of currencies).

    """

    __slots__ = ("amount", "label")

    def __init__(self, label: str, amount: int, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.label: str = label
        self.amount: int = amount

        self._id_attrs = (self.label, self.amount)

        self._freeze()
