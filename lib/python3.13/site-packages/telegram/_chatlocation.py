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
"""This module contains an object that represents a location to which a chat is connected."""

from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._files.location import Location
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class ChatLocation(TelegramObject):
    """This object represents a location to which a chat is connected.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`location` is equal.

    Args:
        location (:class:`telegram.Location`): The location to which the supergroup is connected.
            Can't be a live location.
        address (:obj:`str`): Location address;
            :tg-const:`telegram.ChatLocation.MIN_ADDRESS`-
            :tg-const:`telegram.ChatLocation.MAX_ADDRESS` characters, as defined by the chat owner.
    Attributes:
        location (:class:`telegram.Location`): The location to which the supergroup is connected.
            Can't be a live location.
        address (:obj:`str`): Location address;
            :tg-const:`telegram.ChatLocation.MIN_ADDRESS`-
            :tg-const:`telegram.ChatLocation.MAX_ADDRESS` characters, as defined by the chat owner.

    """

    __slots__ = ("address", "location")

    def __init__(
        self,
        location: Location,
        address: str,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.location: Location = location
        self.address: str = address

        self._id_attrs = (self.location,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChatLocation":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["location"] = de_json_optional(data.get("location"), Location, bot)

        return super().de_json(data=data, bot=bot)

    MIN_ADDRESS: Final[int] = constants.LocationLimit.MIN_CHAT_LOCATION_ADDRESS
    """:const:`telegram.constants.LocationLimit.MIN_CHAT_LOCATION_ADDRESS`

    .. versionadded:: 20.0
    """
    MAX_ADDRESS: Final[int] = constants.LocationLimit.MAX_CHAT_LOCATION_ADDRESS
    """:const:`telegram.constants.LocationLimit.MAX_CHAT_LOCATION_ADDRESS`

    .. versionadded:: 20.0
    """
