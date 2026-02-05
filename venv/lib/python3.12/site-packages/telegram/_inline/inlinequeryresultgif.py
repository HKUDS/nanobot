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
"""This module contains the classes that represent Telegram InlineQueryResultGif."""

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


class InlineQueryResultGif(InlineQueryResult):
    """
    Represents a link to an animated GIF file. By default, this animated GIF file will be sent by
    the user with optional caption. Alternatively, you can use :attr:`input_message_content` to
    send a message with the specified content instead of the animation.

    .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

    .. versionchanged:: 20.5
      |removed_thumb_wildcard_note|

    Args:
        id (:obj:`str`): Unique identifier for this result,
            :tg-const:`telegram.InlineQueryResult.MIN_ID_LENGTH`-
            :tg-const:`telegram.InlineQueryResult.MAX_ID_LENGTH` Bytes.
        gif_url (:obj:`str`): A valid URL for the GIF file.
        gif_width (:obj:`int`, optional): Width of the GIF.
        gif_height (:obj:`int`, optional): Height of the GIF.
        gif_duration (:obj:`int` | :class:`datetime.timedelta`, optional): Duration of the GIF
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
        caption (:obj:`str`, optional): Caption of the GIF file to be sent,
            0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters
            after entities parsing.
        parse_mode (:obj:`str`, optional): |parse_mode|
        caption_entities (Sequence[:class:`telegram.MessageEntity`], optional): |caption_entities|

            .. versionchanged:: 20.0
                |sequenceclassargs|

        reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): Inline keyboard attached
            to the message.
        input_message_content (:class:`telegram.InputMessageContent`, optional): Content of the
            message to be sent instead of the GIF animation.
        show_caption_above_media (:obj:`bool`, optional): Pass |show_cap_above_med|

            .. versionadded:: 21.3

    Attributes:
        type (:obj:`str`): :tg-const:`telegram.constants.InlineQueryResultType.GIF`.
        id (:obj:`str`): Unique identifier for this result,
            :tg-const:`telegram.InlineQueryResult.MIN_ID_LENGTH`-
            :tg-const:`telegram.InlineQueryResult.MAX_ID_LENGTH` Bytes.
        gif_url (:obj:`str`): A valid URL for the GIF file.
        gif_width (:obj:`int`): Optional. Width of the GIF.
        gif_height (:obj:`int`): Optional. Height of the GIF.
        gif_duration (:obj:`int` | :class:`datetime.timedelta`): Optional. Duration of the GIF
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
        caption (:obj:`str`): Optional. Caption of the GIF file to be sent,
            0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters
            after entities parsing.
        parse_mode (:obj:`str`): Optional. |parse_mode|
        caption_entities (tuple[:class:`telegram.MessageEntity`]): Optional. |captionentitiesattr|

            .. versionchanged:: 20.0

                * |tupleclassattrs|
                * |alwaystuple|
        reply_markup (:class:`telegram.InlineKeyboardMarkup`): Optional. Inline keyboard attached
            to the message.
        input_message_content (:class:`telegram.InputMessageContent`): Optional. Content of the
            message to be sent instead of the GIF animation.
        show_caption_above_media (:obj:`bool`): Optional. |show_cap_above_med|

            .. versionadded:: 21.3

    """

    __slots__ = (
        "_gif_duration",
        "caption",
        "caption_entities",
        "gif_height",
        "gif_url",
        "gif_width",
        "input_message_content",
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
        gif_url: str,
        thumbnail_url: str,
        gif_width: int | None = None,
        gif_height: int | None = None,
        title: str | None = None,
        caption: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        input_message_content: "InputMessageContent | None" = None,
        gif_duration: TimePeriod | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence[MessageEntity] | None = None,
        thumbnail_mime_type: str | None = None,
        show_caption_above_media: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        # Required
        super().__init__(InlineQueryResultType.GIF, id, api_kwargs=api_kwargs)
        with self._unfrozen():
            self.gif_url: str = gif_url
            self.thumbnail_url: str = thumbnail_url

            # Optionals
            self.gif_width: int | None = gif_width
            self.gif_height: int | None = gif_height
            self._gif_duration: dtm.timedelta | None = to_timedelta(gif_duration)
            self.title: str | None = title
            self.caption: str | None = caption
            self.parse_mode: ODVInput[str] = parse_mode
            self.caption_entities: tuple[MessageEntity, ...] = parse_sequence_arg(caption_entities)
            self.reply_markup: InlineKeyboardMarkup | None = reply_markup
            self.input_message_content: InputMessageContent | None = input_message_content
            self.thumbnail_mime_type: str | None = thumbnail_mime_type
            self.show_caption_above_media: bool | None = show_caption_above_media

    @property
    def gif_duration(self) -> int | dtm.timedelta | None:
        return get_timedelta_value(self._gif_duration, attribute="gif_duration")
