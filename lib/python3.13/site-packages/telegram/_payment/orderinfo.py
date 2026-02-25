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
"""This module contains an object that represents a Telegram OrderInfo."""

from typing import TYPE_CHECKING

from telegram._payment.shippingaddress import ShippingAddress
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class OrderInfo(TelegramObject):
    """This object represents information about an order.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`name`, :attr:`phone_number`, :attr:`email` and
    :attr:`shipping_address` are equal.

    Args:
        name (:obj:`str`, optional): User name.
        phone_number (:obj:`str`, optional): User's phone number.
        email (:obj:`str`, optional): User email.
        shipping_address (:class:`telegram.ShippingAddress`, optional): User shipping address.

    Attributes:
        name (:obj:`str`): Optional. User name.
        phone_number (:obj:`str`): Optional. User's phone number.
        email (:obj:`str`): Optional. User email.
        shipping_address (:class:`telegram.ShippingAddress`): Optional. User shipping address.

    """

    __slots__ = ("email", "name", "phone_number", "shipping_address")

    def __init__(
        self,
        name: str | None = None,
        phone_number: str | None = None,
        email: str | None = None,
        shipping_address: ShippingAddress | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.name: str | None = name
        self.phone_number: str | None = phone_number
        self.email: str | None = email
        self.shipping_address: ShippingAddress | None = shipping_address

        self._id_attrs = (self.name, self.phone_number, self.email, self.shipping_address)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "OrderInfo":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["shipping_address"] = de_json_optional(
            data.get("shipping_address"), ShippingAddress, bot
        )

        return super().de_json(data=data, bot=bot)
