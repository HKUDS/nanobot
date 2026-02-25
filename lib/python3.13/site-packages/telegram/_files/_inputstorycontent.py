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
# along with this program. If not, see [http://www.gnu.org/licenses/].
"""This module contains objects that represent paid media in Telegram."""

import datetime as dtm
from typing import Final

from telegram import constants
from telegram._files.inputfile import InputFile
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.argumentparsing import to_timedelta
from telegram._utils.files import parse_file_input
from telegram._utils.types import FileInput, JSONDict


class InputStoryContent(TelegramObject):
    """This object describes the content of a story to post. Currently, it can be one of:

    * :class:`telegram.InputStoryContentPhoto`
    * :class:`telegram.InputStoryContentVideo`

    .. versionadded:: 22.1

    Args:
        type (:obj:`str`): Type of the content.

    Attributes:
        type (:obj:`str`): Type of the content.
    """

    __slots__ = ("type",)

    PHOTO: Final[str] = constants.InputStoryContentType.PHOTO
    """:const:`telegram.constants.InputStoryContentType.PHOTO`"""
    VIDEO: Final[str] = constants.InputStoryContentType.VIDEO
    """:const:`telegram.constants.InputStoryContentType.VIDEO`"""

    def __init__(
        self,
        type: str,  # pylint: disable=redefined-builtin
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.type: str = enum.get_member(constants.InputStoryContentType, type, type)

        self._freeze()

    @staticmethod
    def _parse_file_input(file_input: FileInput) -> str | InputFile:
        # We use local_mode=True because we don't have access to the actual setting and want
        # things to work in local mode.
        return parse_file_input(file_input, attach=True, local_mode=True)


class InputStoryContentPhoto(InputStoryContent):
    """Describes a photo to post as a story.

    .. versionadded:: 22.1

    Args:
        photo (:term:`file object` | :obj:`bytes` | :class:`pathlib.Path` | :obj:`str`, \
            optional): The photo to post as a story. The photo must be of the
            size :tg-const:`telegram.constants.InputStoryContentLimit.PHOTO_WIDTH`
            x :tg-const:`telegram.constants.InputStoryContentLimit.PHOTO_HEIGHT` and must not
            exceed :tg-const:`telegram.constants.InputStoryContentLimit.PHOTOSIZE_UPLOAD` MB.
            |uploadinputnopath|.

    Attributes:
        type (:obj:`str`): Type of the content, must be :attr:`~telegram.InputStoryContent.PHOTO`.
        photo (:class:`telegram.InputFile`): The photo to post as a story. The photo must be of the
            size :tg-const:`telegram.constants.InputStoryContentLimit.PHOTO_WIDTH`
            x :tg-const:`telegram.constants.InputStoryContentLimit.PHOTO_HEIGHT` and must not
            exceed :tg-const:`telegram.constants.InputStoryContentLimit.PHOTOSIZE_UPLOAD` MB.

    """

    __slots__ = ("photo",)

    def __init__(
        self,
        photo: FileInput,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=InputStoryContent.PHOTO, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.photo: str | InputFile = self._parse_file_input(photo)


class InputStoryContentVideo(InputStoryContent):
    """
    Describes a video to post as a story.

    .. versionadded:: 22.1

    Args:
        video (:term:`file object` | :obj:`bytes` | :class:`pathlib.Path` | :obj:`str`, \
            optional): The video to post as a story. The video must be of
            the size :tg-const:`telegram.constants.InputStoryContentLimit.VIDEO_WIDTH`
            x :tg-const:`telegram.constants.InputStoryContentLimit.VIDEO_HEIGHT`,
            streamable, encoded with ``H.265`` codec, with key frames added
            each second in the ``MPEG4`` format, and must not exceed
            :tg-const:`telegram.constants.InputStoryContentLimit.VIDEOSIZE_UPLOAD` MB.
            |uploadinputnopath|.
        duration (:class:`datetime.timedelta` | :obj:`int` | :obj:`float`, optional): Precise
            duration of the video in seconds;
            0-:tg-const:`telegram.constants.InputStoryContentLimit.MAX_VIDEO_DURATION`
        cover_frame_timestamp (:class:`datetime.timedelta` | :obj:`int` | :obj:`float`, optional):
            Timestamp in seconds of the frame that will be used as the static cover for the story.
            Defaults to ``0.0``.
        is_animation (:obj:`bool`, optional): Pass :obj:`True` if the video has no sound

    Attributes:
        type (:obj:`str`): Type of the content, must be :attr:`~telegram.InputStoryContent.VIDEO`.
        video (:class:`telegram.InputFile`): The video to post as a story. The video must be of
            the size :tg-const:`telegram.constants.InputStoryContentLimit.VIDEO_WIDTH`
            x :tg-const:`telegram.constants.InputStoryContentLimit.VIDEO_HEIGHT`,
            streamable, encoded with ``H.265`` codec, with key frames added
            each second in the ``MPEG4`` format, and must not exceed
            :tg-const:`telegram.constants.InputStoryContentLimit.VIDEOSIZE_UPLOAD` MB.
        duration (:class:`datetime.timedelta`): Optional. Precise duration of the video in seconds;
            0-:tg-const:`telegram.constants.InputStoryContentLimit.MAX_VIDEO_DURATION`
        cover_frame_timestamp (:class:`datetime.timedelta`): Optional. Timestamp in seconds of the
            frame that will be used as the static cover for the story. Defaults to ``0.0``.
        is_animation (:obj:`bool`): Optional. Pass :obj:`True` if the video has no sound
    """

    __slots__ = ("cover_frame_timestamp", "duration", "is_animation", "video")

    def __init__(
        self,
        video: FileInput,
        duration: float | dtm.timedelta | None = None,
        cover_frame_timestamp: float | dtm.timedelta | None = None,
        is_animation: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=InputStoryContent.VIDEO, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.video: str | InputFile = self._parse_file_input(video)
            self.duration: dtm.timedelta | None = to_timedelta(duration)
            self.cover_frame_timestamp: dtm.timedelta | None = to_timedelta(cover_frame_timestamp)
            self.is_animation: bool | None = is_animation
