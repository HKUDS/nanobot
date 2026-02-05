#!/usr/bin/env python
# pylint: disable=too-many-arguments
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
"""This module contains an object that represents a Telegram ChosenInlineResult."""

from typing import TYPE_CHECKING

from telegram._files.location import Location
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class ChosenInlineResult(TelegramObject):
    """
    Represents a result of an inline query that was chosen by the user and sent to their chat
    partner.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`result_id` is equal.

    Note:
        * In Python :keyword:`from` is a reserved word. Use :paramref:`from_user` instead.
        * It is necessary to enable inline feedback via `@Botfather <https://t.me/BotFather>`_ in
          order to receive these objects in updates.

    Args:
        result_id (:obj:`str`): The unique identifier for the result that was chosen.
        from_user (:class:`telegram.User`): The user that chose the result.
        location (:class:`telegram.Location`, optional): Sender location, only for bots that
            require user location.
        inline_message_id (:obj:`str`, optional): Identifier of the sent inline message. Available
            only if there is an inline keyboard attached to the message. Will be also received in
            callback queries and can be used to edit the message.
        query (:obj:`str`): The query that was used to obtain the result.

    Attributes:
        result_id (:obj:`str`): The unique identifier for the result that was chosen.
        from_user (:class:`telegram.User`): The user that chose the result.
        location (:class:`telegram.Location`): Optional. Sender location, only for bots that
            require user location.
        inline_message_id (:obj:`str`): Optional. Identifier of the sent inline message. Available
            only if there is an inline keyboard attached to the message. Will be also received in
            callback queries and can be used to edit the message.
        query (:obj:`str`): The query that was used to obtain the result.

    """

    __slots__ = ("from_user", "inline_message_id", "location", "query", "result_id")

    def __init__(
        self,
        result_id: str,
        from_user: User,
        query: str,
        location: "Location | None" = None,
        inline_message_id: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        # Required
        self.result_id: str = result_id
        self.from_user: User = from_user
        self.query: str = query
        # Optionals
        self.location: Location | None = location
        self.inline_message_id: str | None = inline_message_id

        self._id_attrs = (self.result_id,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChosenInlineResult":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Required
        data["from_user"] = de_json_optional(data.pop("from", None), User, bot)
        # Optionals
        data["location"] = de_json_optional(data.get("location"), Location, bot)

        return super().de_json(data=data, bot=bot)
