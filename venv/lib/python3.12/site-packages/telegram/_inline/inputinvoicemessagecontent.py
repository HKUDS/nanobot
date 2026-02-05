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
"""This module contains a class that represents a Telegram InputInvoiceMessageContent."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._inline.inputmessagecontent import InputMessageContent
from telegram._payment.labeledprice import LabeledPrice
from telegram._utils.argumentparsing import de_list_optional, parse_sequence_arg
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class InputInvoiceMessageContent(InputMessageContent):
    """
    Represents the content of a invoice message to be sent as the result of an inline query.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`title`, :attr:`description`, :attr:`payload`,
    :attr:`currency` and :attr:`prices` are equal.

    .. versionadded:: 13.5
    .. versionchanged:: 21.11
       :attr:`provider_token` is no longer considered for equality comparison.

    Args:
        title (:obj:`str`): Product name. :tg-const:`telegram.Invoice.MIN_TITLE_LENGTH`-
            :tg-const:`telegram.Invoice.MAX_TITLE_LENGTH` characters.
        description (:obj:`str`): Product description.
            :tg-const:`telegram.Invoice.MIN_DESCRIPTION_LENGTH`-
            :tg-const:`telegram.Invoice.MAX_DESCRIPTION_LENGTH` characters.
        payload (:obj:`str`): Bot-defined invoice payload.
            :tg-const:`telegram.Invoice.MIN_PAYLOAD_LENGTH`-
            :tg-const:`telegram.Invoice.MAX_PAYLOAD_LENGTH` bytes. This will not be displayed
            to the user, use it for your internal processes.
        provider_token (:obj:`str`, optional): Payment provider token, obtained via
            `@Botfather <https://t.me/Botfather>`_. Pass an empty string for payments in
            |tg_stars|.

            .. versionchanged:: 21.11
                Bot API 7.4 made this parameter is optional and this is now reflected in the
                class signature.
        currency (:obj:`str`): Three-letter ISO 4217 currency code, see more on
            `currencies <https://core.telegram.org/bots/payments#supported-currencies>`_.
            Pass ``XTR`` for payments in |tg_stars|.
        prices (Sequence[:class:`telegram.LabeledPrice`]): Price breakdown, a list of
            components (e.g. product price, tax, discount, delivery cost, delivery tax, bonus,
            etc.). Must contain exactly one item for payments in |tg_stars|.

            .. versionchanged:: 20.0
                |sequenceclassargs|

        max_tip_amount (:obj:`int`, optional): The maximum accepted amount for tips in the
            *smallest units* of the currency (integer, **not** float/double). For example, for a
            maximum tip of ``US$ 1.45`` pass ``max_tip_amount = 145``. See the ``exp`` parameter in
            `currencies.json <https://core.telegram.org/bots/payments/currencies.json>`_, it
            shows the number of digits past the decimal point for each currency (2 for the majority
            of currencies). Defaults to ``0``. Not supported for payments in |tg_stars|.
        suggested_tip_amounts (Sequence[:obj:`int`], optional): An array of suggested
            amounts of tip in the *smallest units* of the currency (integer, **not** float/double).
            At most 4 suggested tip amounts can be specified. The suggested tip amounts must be
            positive, passed in a strictly increased order and must not exceed
            :attr:`max_tip_amount`.

            .. versionchanged:: 20.0

                * |tupleclassattrs|
                * |alwaystuple|

        provider_data (:obj:`str`, optional): An object for data about the invoice,
            which will be shared with the payment provider. A detailed description of the required
            fields should be provided by the payment provider.
        photo_url (:obj:`str`, optional): URL of the product photo for the invoice. Can be a photo
            of the goods or a marketing image for a service. People like it better when they see
            what they are paying for.
        photo_size (:obj:`int`, optional): Photo size.
        photo_width (:obj:`int`, optional): Photo width.
        photo_height (:obj:`int`, optional): Photo height.
        need_name (:obj:`bool`, optional): Pass :obj:`True`, if you require the user's full
            name to complete the order. Ignored for payments in |tg_stars|.
        need_phone_number (:obj:`bool`, optional): Pass :obj:`True`, if you require the user's
            phone number to complete the order. Ignored for payments in |tg_stars|.
        need_email (:obj:`bool`, optional): Pass :obj:`True`, if you require the user's email
            address to complete the order. Ignored for payments in |tg_stars|.
        need_shipping_address (:obj:`bool`, optional): Pass :obj:`True`, if you require the
            user's shipping address to complete the order. Ignored for payments in |tg_stars|
        send_phone_number_to_provider (:obj:`bool`, optional): Pass :obj:`True`, if user's
            phone number should be sent to provider. Ignored for payments in |tg_stars|.
        send_email_to_provider (:obj:`bool`, optional): Pass :obj:`True`, if user's email
            address should be sent to provider. Ignored for payments in |tg_stars|.
        is_flexible (:obj:`bool`, optional): Pass :obj:`True`, if the final price depends on
            the shipping method. Ignored for payments in |tg_stars|.

    Attributes:
        title (:obj:`str`): Product name. :tg-const:`telegram.Invoice.MIN_TITLE_LENGTH`-
            :tg-const:`telegram.Invoice.MAX_TITLE_LENGTH` characters.
        description (:obj:`str`): Product description.
            :tg-const:`telegram.Invoice.MIN_DESCRIPTION_LENGTH`-
            :tg-const:`telegram.Invoice.MAX_DESCRIPTION_LENGTH` characters.
        payload (:obj:`str`): Bot-defined invoice payload.
            :tg-const:`telegram.Invoice.MIN_PAYLOAD_LENGTH`-
            :tg-const:`telegram.Invoice.MAX_PAYLOAD_LENGTH` bytes. This will not be displayed
            to the user, use it for your internal processes.
        provider_token (:obj:`str`): Payment provider token, obtained via
            `@Botfather <https://t.me/Botfather>`_. Pass an empty string for payments in `Telegram
            Stars <https://t.me/BotNews/90>`_.
        currency (:obj:`str`): Three-letter ISO 4217 currency code, see more on
            `currencies <https://core.telegram.org/bots/payments#supported-currencies>`_.
            Pass ``XTR`` for payments in |tg_stars|.
        prices (tuple[:class:`telegram.LabeledPrice`]): Price breakdown, a list of
            components (e.g. product price, tax, discount, delivery cost, delivery tax, bonus,
            etc.). Must contain exactly one item for payments in |tg_stars|.

            .. versionchanged:: 20.0
                |tupleclassattrs|

        max_tip_amount (:obj:`int`): Optional. The maximum accepted amount for tips in the
            *smallest units* of the currency (integer, **not** float/double). For example, for a
            maximum tip of ``US$ 1.45`` ``max_tip_amount`` is ``145``. See the ``exp`` parameter in
            `currencies.json <https://core.telegram.org/bots/payments/currencies.json>`_, it
            shows the number of digits past the decimal point for each currency (2 for the majority
            of currencies). Defaults to ``0``. Not supported for payments in |tg_stars|.
        suggested_tip_amounts (tuple[:obj:`int`]): Optional. An array of suggested
            amounts of tip in the *smallest units* of the currency (integer, **not** float/double).
            At most 4 suggested tip amounts can be specified. The suggested tip amounts must be
            positive, passed in a strictly increased order and must not exceed
            :attr:`max_tip_amount`.

            .. versionchanged:: 20.0
                |tupleclassattrs|

        provider_data (:obj:`str`): Optional. An object for data about the invoice,
            which will be shared with the payment provider. A detailed description of the required
            fields should be provided by the payment provider.
        photo_url (:obj:`str`): Optional. URL of the product photo for the invoice. Can be a photo
            of the goods or a marketing image for a service. People like it better when they see
            what they are paying for.
        photo_size (:obj:`int`): Optional. Photo size.
        photo_width (:obj:`int`): Optional. Photo width.
        photo_height (:obj:`int`): Optional. Photo height.
        need_name (:obj:`bool`): Optional. Pass :obj:`True`, if you require the user's full name to
            complete the order. Ignored for payments in |tg_stars|.
        need_phone_number (:obj:`bool`): Optional. Pass :obj:`True`, if you require the user's
            phone number to complete the order. Ignored for payments in |tg_stars|.
        need_email (:obj:`bool`): Optional. Pass :obj:`True`, if you require the user's email
            address to complete the order. Ignored for payments in |tg_stars|.
        need_shipping_address (:obj:`bool`): Optional. Pass :obj:`True`, if you require the user's
            shipping address to complete the order. Ignored for payments in |tg_stars|.
        send_phone_number_to_provider (:obj:`bool`): Optional. Pass :obj:`True`, if user's phone
            number should be sent to provider. Ignored for payments in |tg_stars|.
        send_email_to_provider (:obj:`bool`): Optional. Pass :obj:`True`, if user's email address
            should be sent to provider. Ignored for payments in |tg_stars|.
        is_flexible (:obj:`bool`): Optional. Pass :obj:`True`, if the final price depends on the
            shipping method. Ignored for payments in |tg_stars|.

    """

    __slots__ = (
        "currency",
        "description",
        "is_flexible",
        "max_tip_amount",
        "need_email",
        "need_name",
        "need_phone_number",
        "need_shipping_address",
        "payload",
        "photo_height",
        "photo_size",
        "photo_url",
        "photo_width",
        "prices",
        "provider_data",
        "provider_token",
        "send_email_to_provider",
        "send_phone_number_to_provider",
        "suggested_tip_amounts",
        "title",
    )

    def __init__(
        self,
        title: str,
        description: str,
        payload: str,
        currency: str,
        prices: Sequence[LabeledPrice],
        provider_token: str | None = None,
        max_tip_amount: int | None = None,
        suggested_tip_amounts: Sequence[int] | None = None,
        provider_data: str | None = None,
        photo_url: str | None = None,
        photo_size: int | None = None,
        photo_width: int | None = None,
        photo_height: int | None = None,
        need_name: bool | None = None,
        need_phone_number: bool | None = None,
        need_email: bool | None = None,
        need_shipping_address: bool | None = None,
        send_phone_number_to_provider: bool | None = None,
        send_email_to_provider: bool | None = None,
        is_flexible: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        with self._unfrozen():
            # Required
            self.title: str = title
            self.description: str = description
            self.payload: str = payload
            self.currency: str = currency
            self.prices: tuple[LabeledPrice, ...] = parse_sequence_arg(prices)
            # Optionals
            self.provider_token: str | None = provider_token
            self.max_tip_amount: int | None = max_tip_amount
            self.suggested_tip_amounts: tuple[int, ...] = parse_sequence_arg(suggested_tip_amounts)
            self.provider_data: str | None = provider_data
            self.photo_url: str | None = photo_url
            self.photo_size: int | None = photo_size
            self.photo_width: int | None = photo_width
            self.photo_height: int | None = photo_height
            self.need_name: bool | None = need_name
            self.need_phone_number: bool | None = need_phone_number
            self.need_email: bool | None = need_email
            self.need_shipping_address: bool | None = need_shipping_address
            self.send_phone_number_to_provider: bool | None = send_phone_number_to_provider
            self.send_email_to_provider: bool | None = send_email_to_provider
            self.is_flexible: bool | None = is_flexible

            self._id_attrs = (
                self.title,
                self.description,
                self.payload,
                self.currency,
                self.prices,
            )

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "InputInvoiceMessageContent":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["prices"] = de_list_optional(data.get("prices"), LabeledPrice, bot)

        return super().de_json(data=data, bot=bot)
