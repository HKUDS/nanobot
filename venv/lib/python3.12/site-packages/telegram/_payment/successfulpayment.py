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
"""This module contains an object that represents a Telegram SuccessfulPayment."""

import datetime as dtm
from typing import TYPE_CHECKING

from telegram._payment.orderinfo import OrderInfo
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class SuccessfulPayment(TelegramObject):
    """This object contains basic information about a successful payment.
    Note that if the buyer initiates a chargeback with the relevant payment provider following
    this transaction, the funds may be debited from your balance. This is outside of
    Telegram's control.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`telegram_payment_charge_id` and
    :attr:`provider_payment_charge_id` are equal.

    Args:
        currency (:obj:`str`): Three-letter ISO 4217 currency code, or ``XTR`` for payments in
            |tg_stars|.
        total_amount (:obj:`int`): Total price in the smallest units of the currency (integer,
            **not** float/double). For example, for a price of ``US$ 1.45`` pass ``amount = 145``.
            See the ``exp`` parameter in
            `currencies.json <https://core.telegram.org/bots/payments/currencies.json>`_,
            it shows the number of digits past the decimal point for each currency
            (2 for the majority of currencies).
        invoice_payload (:obj:`str`): Bot-specified invoice payload.
        subscription_expiration_date (:class:`datetime.datetime`, optional): Expiration date of the
            subscription; for recurring payments only.

            .. versionadded:: 21.8
        is_recurring (:obj:`bool`, optional): True, if the payment is for a subscription.

            .. versionadded:: 21.8
        is_first_recurring (:obj:`bool`, optional): True, if the payment is the first payment of a
            subscription.

            .. versionadded:: 21.8
        shipping_option_id (:obj:`str`, optional): Identifier of the shipping option chosen by the
            user.
        order_info (:class:`telegram.OrderInfo`, optional): Order info provided by the user.
        telegram_payment_charge_id (:obj:`str`): Telegram payment identifier.
        provider_payment_charge_id (:obj:`str`): Provider payment identifier.

    Attributes:
        currency (:obj:`str`): Three-letter ISO 4217 currency code, or ``XTR`` for payments in
            |tg_stars|.
        total_amount (:obj:`int`): Total price in the smallest units of the currency (integer,
            **not** float/double). For example, for a price of ``US$ 1.45`` pass ``amount = 145``.
            See the ``exp`` parameter in
            `currencies.json <https://core.telegram.org/bots/payments/currencies.json>`_,
            it shows the number of digits past the decimal point for each currency
            (2 for the majority of currencies).
        invoice_payload (:obj:`str`): Bot-specified invoice payload.
        subscription_expiration_date (:class:`datetime.datetime`): Optional. Expiration
            date of the subscription; for recurring payments only.

            .. versionadded:: 21.8
        is_recurring (:obj:`bool`): Optional. True, if the payment is for a subscription.

            .. versionadded:: 21.8
        is_first_recurring (:obj:`bool`): Optional. True, if the payment is the first payment of a
            subscription.

            .. versionadded:: 21.8
        shipping_option_id (:obj:`str`): Optional. Identifier of the shipping option chosen by the
            user.
        order_info (:class:`telegram.OrderInfo`): Optional. Order info provided by the user.
        telegram_payment_charge_id (:obj:`str`): Telegram payment identifier.
        provider_payment_charge_id (:obj:`str`): Provider payment identifier.

    """

    __slots__ = (
        "currency",
        "invoice_payload",
        "is_first_recurring",
        "is_recurring",
        "order_info",
        "provider_payment_charge_id",
        "shipping_option_id",
        "subscription_expiration_date",
        "telegram_payment_charge_id",
        "total_amount",
    )

    def __init__(
        self,
        currency: str,
        total_amount: int,
        invoice_payload: str,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str,
        shipping_option_id: str | None = None,
        order_info: OrderInfo | None = None,
        subscription_expiration_date: dtm.datetime | None = None,
        is_recurring: bool | None = None,
        is_first_recurring: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.currency: str = currency
        self.total_amount: int = total_amount
        self.invoice_payload: str = invoice_payload
        self.shipping_option_id: str | None = shipping_option_id
        self.order_info: OrderInfo | None = order_info
        self.telegram_payment_charge_id: str = telegram_payment_charge_id
        self.provider_payment_charge_id: str = provider_payment_charge_id
        self.subscription_expiration_date: dtm.datetime | None = subscription_expiration_date
        self.is_recurring: bool | None = is_recurring
        self.is_first_recurring: bool | None = is_first_recurring

        self._id_attrs = (self.telegram_payment_charge_id, self.provider_payment_charge_id)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "SuccessfulPayment":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["order_info"] = de_json_optional(data.get("order_info"), OrderInfo, bot)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["subscription_expiration_date"] = from_timestamp(
            data.get("subscription_expiration_date"), tzinfo=loc_tzinfo
        )

        return super().de_json(data=data, bot=bot)
