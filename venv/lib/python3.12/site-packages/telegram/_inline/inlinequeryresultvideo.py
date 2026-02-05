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
"""This module contains the classes that represent Telegram InlineQueryResultVideo."""

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


class InlineQueryResultVideo(InlineQueryResult):
    """
    Represents a link to a page containing an embedded video player or a video file. By default,
    this video file will be sent by the user with an optional caption. Alternatively, you can use
    :attr:`input_message_content` to send a message with the specified content instead of
    the video.

    Note:
        If an InlineQueryResultVideo message contains an embedded video (e.g., YouTube), you must
        replace its content using :attr:`input_message_content`.

    .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

    .. versionchanged:: 20.5
        |removed_thumb_url_note|

    Args:
        id (:obj:`str`): Unique identifier for this result,
            :tg-const:`telegram.InlineQueryResult.MIN_ID_LENGTH`-
            :tg-const:`telegram.InlineQueryResult.MAX_ID_LENGTH` Bytes.
        video_url (:obj:`str`): A valid URL for the embedded video player or video file.
        mime_type (:obj:`str`): Mime type of the content of video url, "text/html" or "video/mp4".
        thumbnail_url (:obj:`str`, optional): URL of the thumbnail (JPEG only) for the video.

            .. versionadded:: 20.2

            .. versionchanged:: 20.5
              |thumbnail_url_mandatory|

        title (:obj:`str`): Title for the result.
        caption (:obj:`str`, optional): Caption of the video to be sent,
            0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters after entities
            parsing.
        parse_mode (:obj:`str`, optional): |parse_mode|
        caption_entities (Sequence[:class:`telegram.MessageEntity`], optional): |caption_entities|

            .. versionchanged:: 20.0
                |sequenceclassargs|

        video_width (:obj:`int`, optional): Video width.
        video_height (:obj:`int`, optional): Video height.
        video_duration (:obj:`int` | :class:`datetime.timedelta`, optional): Video duration
            in seconds.

            .. versionchanged:: v22.2
                |time-period-input|
        description (:obj:`str`, optional): Short description of the result.
        reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): Inline keyboard attached
            to the message.
        input_message_content (:class:`telegram.InputMessageContent`, optional): Content of the
            message to be sent instead of the video. This field is required if
            ``InlineQueryResultVideo`` is used to send an HTML-page as a result
            (e.g., a YouTube video).
        show_caption_above_media (:obj:`bool`, optional): Pass |show_cap_above_med|

            .. versionadded:: 21.3

    Attributes:
        type (:obj:`str`): :tg-const:`telegram.constants.InlineQueryResultType.VIDEO`.
        id (:obj:`str`): Unique identifier for this result,
            :tg-const:`telegram.InlineQueryResult.MIN_ID_LENGTH`-
            :tg-const:`telegram.InlineQueryResult.MAX_ID_LENGTH` Bytes.
        video_url (:obj:`str`): A valid URL for the embedded video player or video file.
        mime_type (:obj:`str`): Mime type of the content of video url, "text/html" or "video/mp4".
        thumbnail_url (:obj:`str`): URL of the thumbnail (JPEG only) for the video.

            .. versionadded:: 20.2
        title (:obj:`str`): Title for the result.
        caption (:obj:`str`): Optional. Caption of the video to be sent,
            0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters after entities
            parsing.
        parse_mode (:obj:`str`): Optional. |parse_mode|
        caption_entities (tuple[:class:`telegram.MessageEntity`]): Optional.
            |captionentitiesattr|

            .. versionchanged:: 20.0

                * |tupleclassattrs|
                * |alwaystuple|

        video_width (:obj:`int`): Optional. Video width.
        video_height (:obj:`int`): Optional. Video height.
        video_duration (:obj:`int` | :class:`datetime.timedelta`): Optional. Video duration
            in seconds.

            .. deprecated:: v22.2
                |time-period-int-deprecated|
        description (:obj:`str`): Optional. Short description of the result.
        reply_markup (:class:`telegram.InlineKeyboardMarkup`): Optional. Inline keyboard attached
            to the message.
        input_message_content (:class:`telegram.InputMessageContent`): Optional. Content of the
            message to be sent instead of the video. This field is required if
            ``InlineQueryResultVideo`` is used to send an HTML-page as a result
            (e.g., a YouTube video).
        show_caption_above_media (:obj:`bool`): Optional. |show_cap_above_med|

            .. versionadded:: 21.3

    """

    __slots__ = (
        "_video_duration",
        "caption",
        "caption_entities",
        "description",
        "input_message_content",
        "mime_type",
        "parse_mode",
        "reply_markup",
        "show_caption_above_media",
        "thumbnail_url",
        "title",
        "video_height",
        "video_url",
        "video_width",
    )

    def __init__(
        self,
        id: str,  # pylint: disable=redefined-builtin
        video_url: str,
        mime_type: str,
        thumbnail_url: str,
        title: str,
        caption: str | None = None,
        video_width: int | None = None,
        video_height: int | None = None,
        video_duration: TimePeriod | None = None,
        description: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        input_message_content: "InputMessageContent | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence[MessageEntity] | None = None,
        show_caption_above_media: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        # Required
        super().__init__(InlineQueryResultType.VIDEO, id, api_kwargs=api_kwargs)
        with self._unfrozen():
            self.video_url: str = video_url
            self.mime_type: str = mime_type
            self.thumbnail_url: str = thumbnail_url
            self.title: str = title

            # Optional
            self.caption: str | None = caption
            self.parse_mode: ODVInput[str] = parse_mode
            self.caption_entities: tuple[MessageEntity, ...] = parse_sequence_arg(caption_entities)
            self.video_width: int | None = video_width
            self.video_height: int | None = video_height
            self._video_duration: dtm.timedelta | None = to_timedelta(video_duration)
            self.description: str | None = description
            self.reply_markup: InlineKeyboardMarkup | None = reply_markup
            self.input_message_content: InputMessageContent | None = input_message_content
            self.show_caption_above_media: bool | None = show_caption_above_media

    @property
    def video_duration(self) -> int | dtm.timedelta | None:
        return get_timedelta_value(self._video_duration, attribute="video_duration")
