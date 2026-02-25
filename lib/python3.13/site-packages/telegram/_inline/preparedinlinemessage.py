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
"""This module contains an object that represents a Telegram Prepared inline Message."""

import datetime as dtm
from typing import TYPE_CHECKING

from telegram._telegramobject import TelegramObject
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class PreparedInlineMessage(TelegramObject):
    """Describes an inline message to be sent by a user of a Mini App.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`id` is equal.

    .. versionadded:: 21.8

    Args:
        id (:obj:`str`): Unique identifier of the prepared message
        expiration_date (:class:`datetime.datetime`): Expiration date of the prepared message.
            Expired prepared messages can no longer be used.
            |datetime_localization|

    Attributes:
        id (:obj:`str`): Unique identifier of the prepared message
        expiration_date (:class:`datetime.datetime`): Expiration date of the prepared message.
            Expired prepared messages can no longer be used.
            |datetime_localization|
    """

    __slots__ = ("expiration_date", "id")

    def __init__(
        self,
        id: str,  # pylint: disable=redefined-builtin
        expiration_date: dtm.datetime,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.id: str = id
        self.expiration_date: dtm.datetime = expiration_date

        self._id_attrs = (self.id,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "PreparedInlineMessage":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)
        data["expiration_date"] = from_timestamp(data.get("expiration_date"), tzinfo=loc_tzinfo)

        return super().de_json(data=data, bot=bot)
