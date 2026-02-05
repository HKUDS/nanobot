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
"""This module contains an object that represents a Telegram ShippingQuery."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._payment.shippingaddress import ShippingAddress
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import JSONDict, ODVInput

if TYPE_CHECKING:
    from telegram import Bot
    from telegram._payment.shippingoption import ShippingOption


class ShippingQuery(TelegramObject):
    """This object contains information about an incoming shipping query.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`id` is equal.

    Note:
        In Python :keyword:`from` is a reserved word. Use :paramref:`from_user` instead.

    Args:
        id (:obj:`str`): Unique query identifier.
        from_user (:class:`telegram.User`): User who sent the query.
        invoice_payload (:obj:`str`): Bot-specified invoice payload.
        shipping_address (:class:`telegram.ShippingAddress`): User specified shipping address.

    Attributes:
        id (:obj:`str`): Unique query identifier.
        from_user (:class:`telegram.User`): User who sent the query.
        invoice_payload (:obj:`str`): Bot-specified invoice payload.
        shipping_address (:class:`telegram.ShippingAddress`): User specified shipping address.


    """

    __slots__ = ("from_user", "id", "invoice_payload", "shipping_address")

    def __init__(
        self,
        id: str,  # pylint: disable=redefined-builtin
        from_user: User,
        invoice_payload: str,
        shipping_address: ShippingAddress,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.id: str = id
        self.from_user: User = from_user
        self.invoice_payload: str = invoice_payload
        self.shipping_address: ShippingAddress = shipping_address

        self._id_attrs = (self.id,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ShippingQuery":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["from_user"] = de_json_optional(data.pop("from", None), User, bot)
        data["shipping_address"] = de_json_optional(
            data.get("shipping_address"), ShippingAddress, bot
        )

        return super().de_json(data=data, bot=bot)

    async def answer(
        self,
        ok: bool,
        shipping_options: Sequence["ShippingOption"] | None = None,
        error_message: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.answer_shipping_query(update.shipping_query.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.answer_shipping_query`.

        """
        return await self.get_bot().answer_shipping_query(
            shipping_query_id=self.id,
            ok=ok,
            shipping_options=shipping_options,
            error_message=error_message,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
