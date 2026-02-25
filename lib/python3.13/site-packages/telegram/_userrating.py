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
"""This module contains an object that represents a Telegram user rating."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class UserRating(TelegramObject):
    """
    This object describes the rating of a user based on their Telegram Star spendings.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`level` and :attr:`rating` are equal.

    .. versionadded:: 22.6

    Args:
        level (:obj:`int`): Current level of the user, indicating their reliability when purchasing
            digital goods and services. A higher level suggests a more trustworthy customer; a
            negative level is likely reason for concern.
        rating (:obj:`int`): Numerical value of the user's rating; the higher the rating, the
            better
        current_level_rating (:obj:`int`): The rating value required to get the current level
        next_level_rating (:obj:`int`, optional): The rating value required to get to the next
            level; omitted if the maximum level was reached

    Attributes:
        level (:obj:`int`): Current level of the user, indicating their reliability when purchasing
            digital goods and services. A higher level suggests a more trustworthy customer; a
            negative level is likely reason for concern.
        rating (:obj:`int`): Numerical value of the user's rating; the higher the rating, the
            better
        current_level_rating (:obj:`int`): The rating value required to get the current level
        next_level_rating (:obj:`int`): Optional. The rating value required to get to the next
            level; omitted if the maximum level was reached

    """

    __slots__ = ("current_level_rating", "level", "next_level_rating", "rating")

    def __init__(
        self,
        level: int,
        rating: int,
        current_level_rating: int,
        next_level_rating: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.level: int = level
        self.rating: int = rating
        self.current_level_rating: int = current_level_rating
        self.next_level_rating: int | None = next_level_rating

        self._id_attrs = (self.level, self.rating)

        self._freeze()
