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
"""This module contains an object that represents a Telegram Birthday."""

import datetime as dtm

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class Birthdate(TelegramObject):
    """
    This object describes the birthdate of a user.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`day`, and :attr:`month` are equal.

    .. versionadded:: 21.1

    Args:
        day (:obj:`int`): Day of the user's birth; 1-31.
        month (:obj:`int`): Month of the user's birth; 1-12.
        year (:obj:`int`, optional): Year of the user's birth.

    Attributes:
        day (:obj:`int`): Day of the user's birth; 1-31.
        month (:obj:`int`): Month of the user's birth; 1-12.
        year (:obj:`int`): Optional. Year of the user's birth.

    """

    __slots__ = ("day", "month", "year")

    def __init__(
        self,
        day: int,
        month: int,
        year: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        # Required
        self.day: int = day
        self.month: int = month
        # Optional
        self.year: int | None = year

        self._id_attrs = (
            self.day,
            self.month,
        )

        self._freeze()

    def to_date(self, year: int | None = None) -> dtm.date:
        """Return the birthdate as a date object.

        .. versionchanged:: 21.2
           Now returns a :obj:`datetime.date` object instead of a :obj:`datetime.datetime` object,
           as was originally intended.

        Args:
            year (:obj:`int`, optional): The year to use. Required, if the :attr:`year` was not
                present.

        Returns:
            :obj:`datetime.date`: The birthdate as a date object.
        """
        if self.year is None and year is None:
            raise ValueError(
                "The `year` argument is required if the `year` attribute was not present."
            )

        return dtm.date(year or self.year, self.month, self.day)  # type: ignore[arg-type]
