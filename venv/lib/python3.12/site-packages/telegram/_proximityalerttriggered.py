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
"""This module contains an object that represents a Telegram Proximity Alert."""

from typing import TYPE_CHECKING

from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class ProximityAlertTriggered(TelegramObject):
    """
    This object represents the content of a service message, sent whenever a user in the chat
    triggers a proximity alert set by another user.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`traveler`, :attr:`watcher` and :attr:`distance` are equal.

    Args:
        traveler (:class:`telegram.User`): User that triggered the alert
        watcher (:class:`telegram.User`): User that set the alert
        distance (:obj:`int`): The distance between the users

    Attributes:
        traveler (:class:`telegram.User`): User that triggered the alert
        watcher (:class:`telegram.User`): User that set the alert
        distance (:obj:`int`): The distance between the users

    """

    __slots__ = ("distance", "traveler", "watcher")

    def __init__(
        self,
        traveler: User,
        watcher: User,
        distance: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.traveler: User = traveler
        self.watcher: User = watcher
        self.distance: int = distance

        self._id_attrs = (self.traveler, self.watcher, self.distance)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ProximityAlertTriggered":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["traveler"] = de_json_optional(data.get("traveler"), User, bot)
        data["watcher"] = de_json_optional(data.get("watcher"), User, bot)

        return super().de_json(data=data, bot=bot)
