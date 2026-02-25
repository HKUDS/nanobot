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
"""This module contains an object that represents a Telegram Animation."""

import datetime as dtm

from telegram._files._basethumbedmedium import _BaseThumbedMedium
from telegram._files.photosize import PhotoSize
from telegram._utils.argumentparsing import to_timedelta
from telegram._utils.datetime import get_timedelta_value
from telegram._utils.types import JSONDict, TimePeriod


class Animation(_BaseThumbedMedium):
    """This object represents an animation file (GIF or H.264/MPEG-4 AVC video without sound).

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`file_unique_id` is equal.

    .. versionchanged:: 20.5
      |removed_thumb_note|

    Args:
        file_id (:obj:`str`): Identifier for this file, which can be used to download
            or reuse the file.
        file_unique_id (:obj:`str`): Unique identifier for this file, which
            is supposed to be the same over time and for different bots.
            Can't be used to download or reuse the file.
        width (:obj:`int`): Video width as defined by the sender.
        height (:obj:`int`): Video height as defined by the sender.
        duration (:obj:`int` | :class:`datetime.timedelta`, optional): Duration of the video
            in seconds as defined by the sender.

            .. versionchanged:: v22.2
                |time-period-input|
        file_name (:obj:`str`, optional): Original animation filename as defined by the sender.
        mime_type (:obj:`str`, optional): MIME type of the file as defined by the sender.
        file_size (:obj:`int`, optional): File size in bytes.
        thumbnail (:class:`telegram.PhotoSize`, optional): Animation thumbnail as defined by
            sender.

            .. versionadded:: 20.2

    Attributes:
        file_id (:obj:`str`): Identifier for this file, which can be used to download
            or reuse the file.
        file_unique_id (:obj:`str`): Unique identifier for this file, which
            is supposed to be the same over time and for different bots.
            Can't be used to download or reuse the file.
        width (:obj:`int`): Video width as defined by the sender.
        height (:obj:`int`): Video height as defined by the sender.
        duration (:obj:`int` | :class:`datetime.timedelta`): Duration of the video in seconds
            as defined by the sender.

            .. deprecated:: v22.2
                |time-period-int-deprecated|
        file_name (:obj:`str`): Optional. Original animation filename as defined by the sender.
        mime_type (:obj:`str`): Optional. MIME type of the file as defined by the sender.
        file_size (:obj:`int`): Optional. File size in bytes.
        thumbnail (:class:`telegram.PhotoSize`): Optional. Animation thumbnail as defined by
            sender.

            .. versionadded:: 20.2

    """

    __slots__ = ("_duration", "file_name", "height", "mime_type", "width")

    def __init__(
        self,
        file_id: str,
        file_unique_id: str,
        width: int,
        height: int,
        duration: TimePeriod,
        file_name: str | None = None,
        mime_type: str | None = None,
        file_size: int | None = None,
        thumbnail: PhotoSize | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_size=file_size,
            api_kwargs=api_kwargs,
            thumbnail=thumbnail,
        )
        with self._unfrozen():
            # Required
            self.width: int = width
            self.height: int = height
            self._duration: dtm.timedelta = to_timedelta(duration)
            # Optional
            self.mime_type: str | None = mime_type
            self.file_name: str | None = file_name

    @property
    def duration(self) -> int | dtm.timedelta:
        return get_timedelta_value(  # type: ignore[return-value]
            self._duration, attribute="duration"
        )
