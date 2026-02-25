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
"""This module contains an object that represents a Telegram UserProfilePhotos."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._files.photosize import PhotoSize
from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class UserProfilePhotos(TelegramObject):
    """This object represents a user's profile pictures.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`total_count` and :attr:`photos` are equal.

    Args:
        total_count (:obj:`int`): Total number of profile pictures the target user has.
        photos (Sequence[Sequence[:class:`telegram.PhotoSize`]]): Requested profile pictures (in up
            to 4 sizes each).

            .. versionchanged:: 20.0
                |sequenceclassargs|

    Attributes:
        total_count (:obj:`int`): Total number of profile pictures.
        photos (tuple[tuple[:class:`telegram.PhotoSize`]]): Requested profile pictures (in up to 4
            sizes each).

            .. versionchanged:: 20.0
                |tupleclassattrs|

    """

    __slots__ = ("photos", "total_count")

    def __init__(
        self,
        total_count: int,
        photos: Sequence[Sequence[PhotoSize]],
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.total_count: int = total_count
        self.photos: tuple[tuple[PhotoSize, ...], ...] = tuple(tuple(sizes) for sizes in photos)

        self._id_attrs = (self.total_count, self.photos)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "UserProfilePhotos":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["photos"] = [PhotoSize.de_list(photo, bot) for photo in data["photos"]]

        return super().de_json(data=data, bot=bot)
