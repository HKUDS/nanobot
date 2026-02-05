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
"""This module contains an object that represents a Telegram Invoice."""

from typing import Final

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class Invoice(TelegramObject):
    """This object contains basic information about an invoice.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`title`, :attr:`description`, :paramref:`start_parameter`,
    :attr:`currency` and :attr:`total_amount` are equal.

    Args:
        title (:obj:`str`): Product name.
        description (:obj:`str`): Product description.
        start_parameter (:obj:`str`): Unique bot deep-linking parameter that can be used to
            generate this invoice.
        currency (:obj:`str`): Three-letter ISO 4217 currency code, or ``XTR`` for payments in
            |tg_stars|.
        total_amount (:obj:`int`): Total price in the smallest units of the currency (integer,
            **not** float/double). For example, for a price of ``US$ 1.45`` pass ``amount = 145``.
            See the ``exp`` parameter in
            `currencies.json <https://core.telegram.org/bots/payments/currencies.json>`_,
            it shows the number of digits past the decimal point for each currency
            (2 for the majority of currencies).

    Attributes:
        title (:obj:`str`): Product name.
        description (:obj:`str`): Product description.
        start_parameter (:obj:`str`): Unique bot deep-linking parameter that can be used to
            generate this invoice.
        currency (:obj:`str`): Three-letter ISO 4217 currency code, or ``XTR`` for payments in
            |tg_stars|.
        total_amount (:obj:`int`): Total price in the smallest units of the currency (integer,
            **not** float/double). For example, for a price of ``US$ 1.45`` pass ``amount = 145``.
            See the ``exp`` parameter in
            `currencies.json <https://core.telegram.org/bots/payments/currencies.json>`_,
            it shows the number of digits past the decimal point for each currency
            (2 for the majority of currencies).

    """

    __slots__ = (
        "currency",
        "description",
        "start_parameter",
        "title",
        "total_amount",
    )

    def __init__(
        self,
        title: str,
        description: str,
        start_parameter: str,
        currency: str,
        total_amount: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.title: str = title
        self.description: str = description
        self.start_parameter: str = start_parameter
        self.currency: str = currency
        self.total_amount: int = total_amount

        self._id_attrs = (
            self.title,
            self.description,
            self.start_parameter,
            self.currency,
            self.total_amount,
        )

        self._freeze()

    MIN_TITLE_LENGTH: Final[int] = constants.InvoiceLimit.MIN_TITLE_LENGTH
    """:const:`telegram.constants.InvoiceLimit.MIN_TITLE_LENGTH`

    .. versionadded:: 20.0
    """
    MAX_TITLE_LENGTH: Final[int] = constants.InvoiceLimit.MAX_TITLE_LENGTH
    """:const:`telegram.constants.InvoiceLimit.MAX_TITLE_LENGTH`

    .. versionadded:: 20.0
    """
    MIN_DESCRIPTION_LENGTH: Final[int] = constants.InvoiceLimit.MIN_DESCRIPTION_LENGTH
    """:const:`telegram.constants.InvoiceLimit.MIN_DESCRIPTION_LENGTH`

    .. versionadded:: 20.0
    """
    MAX_DESCRIPTION_LENGTH: Final[int] = constants.InvoiceLimit.MAX_DESCRIPTION_LENGTH
    """:const:`telegram.constants.InvoiceLimit.MAX_DESCRIPTION_LENGTH`

    .. versionadded:: 20.0
    """
    MIN_PAYLOAD_LENGTH: Final[int] = constants.InvoiceLimit.MIN_PAYLOAD_LENGTH
    """:const:`telegram.constants.InvoiceLimit.MIN_PAYLOAD_LENGTH`

    .. versionadded:: 20.0
    """
    MAX_PAYLOAD_LENGTH: Final[int] = constants.InvoiceLimit.MAX_PAYLOAD_LENGTH
    """:const:`telegram.constants.InvoiceLimit.MAX_PAYLOAD_LENGTH`

    .. versionadded:: 20.0
    """
    MAX_TIP_AMOUNTS: Final[int] = constants.InvoiceLimit.MAX_TIP_AMOUNTS
    """:const:`telegram.constants.InvoiceLimit.MAX_TIP_AMOUNTS`

    .. versionadded:: 20.0
    """
