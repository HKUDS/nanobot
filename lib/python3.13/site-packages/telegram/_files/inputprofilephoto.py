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
"""This module contains an objects that represents a InputProfilePhoto and subclasses."""

import datetime as dtm
from typing import TYPE_CHECKING

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.argumentparsing import to_timedelta
from telegram._utils.files import parse_file_input
from telegram._utils.types import FileInput, JSONDict

if TYPE_CHECKING:
    from telegram import InputFile


class InputProfilePhoto(TelegramObject):
    """This object describes a profile photo to set. Currently, it can be one of

    * :class:`InputProfilePhotoStatic`
    * :class:`InputProfilePhotoAnimated`

    .. versionadded:: 22.1

    Args:
        type (:obj:`str`): Type of the profile photo.

    Attributes:
        type (:obj:`str`): Type of the profile photo.

    """

    STATIC = constants.InputProfilePhotoType.STATIC
    """:obj:`str`: :tg-const:`telegram.constants.InputProfilePhotoType.STATIC`."""
    ANIMATED = constants.InputProfilePhotoType.ANIMATED
    """:obj:`str`: :tg-const:`telegram.constants.InputProfilePhotoType.ANIMATED`."""

    __slots__ = ("type",)

    def __init__(
        self,
        type: str,  # pylint: disable=redefined-builtin
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.type: str = enum.get_member(constants.InputProfilePhotoType, type, type)

        self._freeze()


class InputProfilePhotoStatic(InputProfilePhoto):
    """A static profile photo in the .JPG format.

    .. versionadded:: 22.1

    Args:
        photo (:term:`file object` | :class:`~telegram.InputFile` | :obj:`bytes` | \
            :class:`pathlib.Path`): The static profile photo. |uploadinputnopath|

    Attributes:
        type (:obj:`str`): :tg-const:`telegram.constants.InputProfilePhotoType.STATIC`.
        photo (:class:`telegram.InputFile` | :obj:`str`): The static profile photo.

    """

    __slots__ = ("photo",)

    def __init__(
        self,
        photo: FileInput,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=constants.InputProfilePhotoType.STATIC, api_kwargs=api_kwargs)
        with self._unfrozen():
            # We use local_mode=True because we don't have access to the actual setting and want
            # things to work in local mode.
            self.photo: str | InputFile = parse_file_input(photo, attach=True, local_mode=True)


class InputProfilePhotoAnimated(InputProfilePhoto):
    """An animated profile photo in the MPEG4 format.

    .. versionadded:: 22.1

    Args:
        animation (:term:`file object` | :class:`~telegram.InputFile` | :obj:`bytes` | \
            :class:`pathlib.Path`): The animated profile photo. |uploadinputnopath|
        main_frame_timestamp (:class:`datetime.timedelta` | :obj:`int` | :obj:`float`, optional):
            Timestamp in seconds of the frame that will be used as the static profile photo.
            Defaults to ``0.0``.

    Attributes:
        type (:obj:`str`): :tg-const:`telegram.constants.InputProfilePhotoType.ANIMATED`.
        animation (:class:`telegram.InputFile` | :obj:`str`): The animated profile photo.
        main_frame_timestamp (:class:`datetime.timedelta`): Optional. Timestamp in seconds of the
            frame that will be used as the static profile photo. Defaults to ``0.0``.
    """

    __slots__ = ("animation", "main_frame_timestamp")

    def __init__(
        self,
        animation: FileInput,
        main_frame_timestamp: float | dtm.timedelta | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=constants.InputProfilePhotoType.ANIMATED, api_kwargs=api_kwargs)
        with self._unfrozen():
            # We use local_mode=True because we don't have access to the actual setting and want
            # things to work in local mode.
            self.animation: str | InputFile = parse_file_input(
                animation, attach=True, local_mode=True
            )

            self.main_frame_timestamp: dtm.timedelta | None = to_timedelta(main_frame_timestamp)
