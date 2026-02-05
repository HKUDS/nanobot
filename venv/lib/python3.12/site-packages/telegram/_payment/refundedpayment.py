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
"""This module contains an object that represents a Telegram RefundedPayment."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class RefundedPayment(TelegramObject):
    """This object contains basic information about a refunded payment.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`telegram_payment_charge_id` is equal.

    .. versionadded:: 21.4

    Args:
        currency (:obj:`str`): Three-letter ISO 4217 `currency
            <https://core.telegram.org/bots/payments#supported-currencies>`_ code, or ``XTR`` for
            payments in |tg_stars|. Currently, always ``XTR``.
        total_amount (:obj:`int`): Total refunded price in the *smallest units* of the currency
            (integer, **not** float/double). For example, for a price of ``US$ 1.45``,
            ``total_amount = 145``. See the *exp* parameter in
            `currencies.json <https://core.telegram.org/bots/payments/currencies.json>`_,
            it shows the number of digits past the decimal point for each currency
            (2 for the majority of currencies).
        invoice_payload (:obj:`str`): Bot-specified invoice payload.
        telegram_payment_charge_id (:obj:`str`): Telegram payment identifier.
        provider_payment_charge_id (:obj:`str`, optional): Provider payment identifier.

    Attributes:
        currency (:obj:`str`): Three-letter ISO 4217 `currency
            <https://core.telegram.org/bots/payments#supported-currencies>`_ code, or ``XTR`` for
            payments in |tg_stars|. Currently, always ``XTR``.
        total_amount (:obj:`int`): Total refunded price in the *smallest units* of the currency
            (integer, **not** float/double). For example, for a price of ``US$ 1.45``,
            ``total_amount = 145``. See the *exp* parameter in
            `currencies.json <https://core.telegram.org/bots/payments/currencies.json>`_,
            it shows the number of digits past the decimal point for each currency
            (2 for the majority of currencies).
        invoice_payload (:obj:`str`): Bot-specified invoice payload.
        telegram_payment_charge_id (:obj:`str`): Telegram payment identifier.
        provider_payment_charge_id (:obj:`str`): Optional. Provider payment identifier.

    """

    __slots__ = (
        "currency",
        "invoice_payload",
        "provider_payment_charge_id",
        "telegram_payment_charge_id",
        "total_amount",
    )

    def __init__(
        self,
        currency: str,
        total_amount: int,
        invoice_payload: str,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.currency: str = currency
        self.total_amount: int = total_amount
        self.invoice_payload: str = invoice_payload
        self.telegram_payment_charge_id: str = telegram_payment_charge_id
        # Optional
        self.provider_payment_charge_id: str | None = provider_payment_charge_id

        self._id_attrs = (self.telegram_payment_charge_id,)

        self._freeze()
