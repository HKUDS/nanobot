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
"""This module contains the classes that represent Telegram InlineQueryResultMpeg4Gif."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._inline.inlinekeyboardmarkup import InlineKeyboardMarkup
from telegram._inline.inlinequeryresult import InlineQueryResult
from telegram._messageentity import MessageEntity
from telegram._utils.argumentparsing import parse_sequence_arg, to_timedelta
from telegram._utils.datetime import get_timedelta_value
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import JSONDict, ODVInput, TimePeriod
from telegram.constants import InlineQueryResultType

if TYPE_CHECKING:
    from telegram import InputMessageContent


class InlineQueryResultMpeg4Gif(InlineQueryResult):
    """
    Represents a link to a video animation (H.264/MPEG-4 AVC video without sound). By default, this
    animated MPEG-4 file will be sent by the user with optional caption. Alternatively, you can
    use :attr:`input_message_content` to send a message with the specified content instead of the
    animation.

    .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

    .. versionchanged:: 20.5
        |removed_thumb_wildcard_note|

    Args:
        id (:obj:`str`): Unique identifier for this result,
            :tg-const:`telegram.InlineQueryResult.MIN_ID_LENGTH`-
            :tg-const:`telegram.InlineQueryResult.MAX_ID_LENGTH` Bytes.
        mpeg4_url (:obj:`str`): A valid URL for the MP4 file.
        mpeg4_width (:obj:`int`, optional): Video width.
        mpeg4_height (:obj:`int`, optional): Video height.
        mpeg4_duration (:obj:`int` | :class:`datetime.timedelta`, optional): Video duration
            in seconds.

            .. versionchanged:: v22.2
                |time-period-input|
        thumbnail_url (:obj:`str`): URL of the static (JPEG or GIF) or animated (MPEG4)
            thumbnail for the result.

            .. versionadded:: 20.2

            .. versionchanged:: 20.5
              |thumbnail_url_mandatory|

        thumbnail_mime_type (:obj:`str`, optional): MIME type of the thumbnail, must be one of
            ``'image/jpeg'``, ``'image/gif'``, or ``'video/mp4'``. Defaults to ``'image/jpeg'``.

            .. versionadded:: 20.2
        title (:obj:`str`, optional): Title for the result.
        caption (:obj:`str`, optional): Caption of the MPEG-4 file to be sent,
            0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters
            after entities parsing.
        parse_mode (:obj:`str`, optional): |parse_mode|
        caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
            |captionentitiesattr|

            .. versionchanged:: 20.0
                |sequenceclassargs|

        reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): Inline keyboard attached
            to the message.
        input_message_content (:class:`telegram.InputMessageContent`, optional): Content of the
            message to be sent instead of the video animation.
        show_caption_above_media (:obj:`bool`, optional): Pass |show_cap_above_med|

            .. versionadded:: 21.3

    Attributes:
        type (:obj:`str`): :tg-const:`telegram.constants.InlineQueryResultType.MPEG4GIF`.
        id (:obj:`str`): Unique identifier for this result,
            :tg-const:`telegram.InlineQueryResult.MIN_ID_LENGTH`-
            :tg-const:`telegram.InlineQueryResult.MAX_ID_LENGTH` Bytes.
        mpeg4_url (:obj:`str`): A valid URL for the MP4 file.
        mpeg4_width (:obj:`int`): Optional. Video width.
        mpeg4_height (:obj:`int`): Optional. Video height.
        mpeg4_duration (:obj:`int` | :class:`datetime.timedelta`): Optional. Video duration
            in seconds.

            .. deprecated:: v22.2
                |time-period-int-deprecated|
        thumbnail_url (:obj:`str`): URL of the static (JPEG or GIF) or animated (MPEG4) thumbnail
            for the result.

            .. versionadded:: 20.2
        thumbnail_mime_type (:obj:`str`): Optional. MIME type of the thumbnail, must be one of
            ``'image/jpeg'``, ``'image/gif'``, or ``'video/mp4'``. Defaults to ``'image/jpeg'``.

            .. versionadded:: 20.2
        title (:obj:`str`): Optional. Title for the result.
        caption (:obj:`str`): Optional. Caption of the MPEG-4 file to be sent,
            0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters
            after entities parsing.
        parse_mode (:obj:`str`): Optional. |parse_mode|
        caption_entities (tuple[:class:`telegram.MessageEntity`]): Optional. |caption_entities|

            .. versionchanged:: 20.0

                * |tupleclassattrs|
                * |alwaystuple|

        reply_markup (:class:`telegram.InlineKeyboardMarkup`): Optional. Inline keyboard attached
            to the message.
        input_message_content (:class:`telegram.InputMessageContent`): Optional. Content of the
            message to be sent instead of the video animation.
        show_caption_above_media (:obj:`bool`): Optional. |show_cap_above_med|

            .. versionadded:: 21.3
    """

    __slots__ = (
        "_mpeg4_duration",
        "caption",
        "caption_entities",
        "input_message_content",
        "mpeg4_height",
        "mpeg4_url",
        "mpeg4_width",
        "parse_mode",
        "reply_markup",
        "show_caption_above_media",
        "thumbnail_mime_type",
        "thumbnail_url",
        "title",
    )

    def __init__(
        self,
        id: str,  # pylint: disable=redefined-builtin
        mpeg4_url: str,
        thumbnail_url: str,
        mpeg4_width: int | None = None,
        mpeg4_height: int | None = None,
        title: str | None = None,
        caption: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        input_message_content: "InputMessageContent | None" = None,
        mpeg4_duration: TimePeriod | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence[MessageEntity] | None = None,
        thumbnail_mime_type: str | None = None,
        show_caption_above_media: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        # Required
        super().__init__(InlineQueryResultType.MPEG4GIF, id, api_kwargs=api_kwargs)
        with self._unfrozen():
            self.mpeg4_url: str = mpeg4_url
            self.thumbnail_url: str = thumbnail_url

            # Optional
            self.mpeg4_width: int | None = mpeg4_width
            self.mpeg4_height: int | None = mpeg4_height
            self._mpeg4_duration: dtm.timedelta | None = to_timedelta(mpeg4_duration)
            self.title: str | None = title
            self.caption: str | None = caption
            self.parse_mode: ODVInput[str] = parse_mode
            self.caption_entities: tuple[MessageEntity, ...] = parse_sequence_arg(caption_entities)
            self.reply_markup: InlineKeyboardMarkup | None = reply_markup
            self.input_message_content: InputMessageContent | None = input_message_content
            self.thumbnail_mime_type: str | None = thumbnail_mime_type
            self.show_caption_above_media: bool | None = show_caption_above_media

    @property
    def mpeg4_duration(self) -> int | dtm.timedelta | None:
        return get_timedelta_value(self._mpeg4_duration, attribute="mpeg4_duration")
