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
"""This module contains an object that represents a Telegram ChatPhoto."""

from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import JSONDict, ODVInput

if TYPE_CHECKING:
    from telegram import File


class ChatPhoto(TelegramObject):
    """This object represents a chat photo.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`small_file_unique_id` and :attr:`big_file_unique_id` are
    equal.

    Args:
        small_file_id (:obj:`str`): File identifier of small
            (:tg-const:`telegram.ChatPhoto.SIZE_SMALL` x :tg-const:`telegram.ChatPhoto.SIZE_SMALL`)
            chat photo. This file_id can be used only for photo download and only for as long
            as the photo is not changed.
        small_file_unique_id (:obj:`str`): Unique file identifier of small
            (:tg-const:`telegram.ChatPhoto.SIZE_SMALL` x :tg-const:`telegram.ChatPhoto.SIZE_SMALL`)
            chat photo, which is supposed to be the same over time and for different bots.
            Can't be used to download or reuse the file.
        big_file_id (:obj:`str`): File identifier of big
            (:tg-const:`telegram.ChatPhoto.SIZE_BIG` x :tg-const:`telegram.ChatPhoto.SIZE_BIG`)
            chat photo. This file_id can be used only for photo download and only for as long as
            the photo is not changed.
        big_file_unique_id (:obj:`str`): Unique file identifier of big
            (:tg-const:`telegram.ChatPhoto.SIZE_BIG` x :tg-const:`telegram.ChatPhoto.SIZE_BIG`)
            chat photo, which is supposed to be the same over time and for different bots.
            Can't be used to download or reuse the file.

    Attributes:
        small_file_id (:obj:`str`): File identifier of small
            (:tg-const:`telegram.ChatPhoto.SIZE_SMALL` x :tg-const:`telegram.ChatPhoto.SIZE_SMALL`)
            chat photo. This file_id can be used only for photo download and only for as long
            as the photo is not changed.
        small_file_unique_id (:obj:`str`): Unique file identifier of small
            (:tg-const:`telegram.ChatPhoto.SIZE_SMALL` x :tg-const:`telegram.ChatPhoto.SIZE_SMALL`)
            chat photo, which is supposed to be the same over time and for different bots.
            Can't be used to download or reuse the file.
        big_file_id (:obj:`str`): File identifier of big
            (:tg-const:`telegram.ChatPhoto.SIZE_BIG` x :tg-const:`telegram.ChatPhoto.SIZE_BIG`)
            chat photo. This file_id can be used only for photo download and only for as long as
            the photo is not changed.
        big_file_unique_id (:obj:`str`): Unique file identifier of big
            (:tg-const:`telegram.ChatPhoto.SIZE_BIG` x :tg-const:`telegram.ChatPhoto.SIZE_BIG`)
            chat photo, which is supposed to be the same over time and for different bots.
            Can't be used to download or reuse the file.

    """

    __slots__ = (
        "big_file_id",
        "big_file_unique_id",
        "small_file_id",
        "small_file_unique_id",
    )

    def __init__(
        self,
        small_file_id: str,
        small_file_unique_id: str,
        big_file_id: str,
        big_file_unique_id: str,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.small_file_id: str = small_file_id
        self.small_file_unique_id: str = small_file_unique_id
        self.big_file_id: str = big_file_id
        self.big_file_unique_id: str = big_file_unique_id

        self._id_attrs = (
            self.small_file_unique_id,
            self.big_file_unique_id,
        )

        self._freeze()

    async def get_small_file(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "File":
        """Convenience wrapper over :meth:`telegram.Bot.get_file` for getting the small
        (:tg-const:`telegram.ChatPhoto.SIZE_SMALL` x :tg-const:`telegram.ChatPhoto.SIZE_SMALL`)
        chat photo

        For the documentation of the arguments, please see :meth:`telegram.Bot.get_file`.

        Returns:
            :class:`telegram.File`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        return await self.get_bot().get_file(
            file_id=self.small_file_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_big_file(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "File":
        """Convenience wrapper over :meth:`telegram.Bot.get_file` for getting the
        big (:tg-const:`telegram.ChatPhoto.SIZE_BIG` x :tg-const:`telegram.ChatPhoto.SIZE_BIG`)
        chat photo

        For the documentation of the arguments, please see :meth:`telegram.Bot.get_file`.

        Returns:
            :class:`telegram.File`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        return await self.get_bot().get_file(
            file_id=self.big_file_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    SIZE_SMALL: Final[int] = constants.ChatPhotoSize.SMALL
    """:const:`telegram.constants.ChatPhotoSize.SMALL`

    .. versionadded:: 20.0
    """
    SIZE_BIG: Final[int] = constants.ChatPhotoSize.BIG
    """:const:`telegram.constants.ChatPhotoSize.BIG`

    .. versionadded:: 20.0
    """
