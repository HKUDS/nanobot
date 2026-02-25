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
"""This module contains the classes that represent Telegram InlineQueryResultLocation."""

import datetime as dtm
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._inline.inlinekeyboardmarkup import InlineKeyboardMarkup
from telegram._inline.inlinequeryresult import InlineQueryResult
from telegram._utils.argumentparsing import to_timedelta
from telegram._utils.datetime import get_timedelta_value
from telegram._utils.types import JSONDict, TimePeriod

if TYPE_CHECKING:
    from telegram import InputMessageContent


class InlineQueryResultLocation(InlineQueryResult):
    """
    Represents a location on a map. By default, the location will be sent by the user.
    Alternatively, you can use :attr:`input_message_content` to send a message with the specified
    content instead of the location.

    .. versionchanged:: 20.5
        |removed_thumb_wildcard_note|

    Args:
        id (:obj:`str`): Unique identifier for this result,
            :tg-const:`telegram.InlineQueryResult.MIN_ID_LENGTH`-
            :tg-const:`telegram.InlineQueryResult.MAX_ID_LENGTH` Bytes.
        latitude (:obj:`float`): Location latitude in degrees.
        longitude (:obj:`float`): Location longitude in degrees.
        title (:obj:`str`): Location title.
        horizontal_accuracy (:obj:`float`, optional): The radius of uncertainty for the location,
            measured in meters; 0-
            :tg-const:`telegram.InlineQueryResultLocation.HORIZONTAL_ACCURACY`.
        live_period (:obj:`int` | :class:`datetime.timedelta`, optional): Period in seconds for
            which the location will be updated, should be between
            :tg-const:`telegram.InlineQueryResultLocation.MIN_LIVE_PERIOD` and
            :tg-const:`telegram.InlineQueryResultLocation.MAX_LIVE_PERIOD`.

            .. versionchanged:: v22.2
                |time-period-input|
        heading (:obj:`int`, optional): For live locations, a direction in which the user is
            moving, in degrees. Must be between
            :tg-const:`telegram.InlineQueryResultLocation.MIN_HEADING` and
            :tg-const:`telegram.InlineQueryResultLocation.MAX_HEADING` if specified.
        proximity_alert_radius (:obj:`int`, optional): For live locations, a maximum distance
            for proximity alerts about approaching another chat member, in meters. Must be
            between :tg-const:`telegram.InlineQueryResultLocation.MIN_PROXIMITY_ALERT_RADIUS`
            and :tg-const:`telegram.InlineQueryResultLocation.MAX_PROXIMITY_ALERT_RADIUS`
            if specified.
        reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): Inline keyboard attached
            to the message.
        input_message_content (:class:`telegram.InputMessageContent`, optional): Content of the
            message to be sent instead of the location.
        thumbnail_url (:obj:`str`, optional): Url of the thumbnail for the result.

            .. versionadded:: 20.2
        thumbnail_width (:obj:`int`, optional): Thumbnail width.

            .. versionadded:: 20.2
        thumbnail_height (:obj:`int`, optional): Thumbnail height.

            .. versionadded:: 20.2

    Attributes:
        type (:obj:`str`): :tg-const:`telegram.constants.InlineQueryResultType.LOCATION`.
        id (:obj:`str`): Unique identifier for this result,
            :tg-const:`telegram.InlineQueryResult.MIN_ID_LENGTH`-
            :tg-const:`telegram.InlineQueryResult.MAX_ID_LENGTH` Bytes.
        latitude (:obj:`float`): Location latitude in degrees.
        longitude (:obj:`float`): Location longitude in degrees.
        title (:obj:`str`): Location title.
        horizontal_accuracy (:obj:`float`): Optional. The radius of uncertainty for the location,
            measured in meters; 0-
            :tg-const:`telegram.InlineQueryResultLocation.HORIZONTAL_ACCURACY`.
        live_period (:obj:`int` | :class:`datetime.timedelta`): Optional. Period in seconds for
            which the location will be updated, should be between
            :tg-const:`telegram.InlineQueryResultLocation.MIN_LIVE_PERIOD` and
            :tg-const:`telegram.InlineQueryResultLocation.MAX_LIVE_PERIOD` or
            :tg-const:`telegram.constants.LocationLimit.LIVE_PERIOD_FOREVER` for live
            locations that can be edited indefinitely.

            .. deprecated:: v22.2
                |time-period-int-deprecated|
        heading (:obj:`int`): Optional. For live locations, a direction in which the user is
            moving, in degrees. Must be between
            :tg-const:`telegram.InlineQueryResultLocation.MIN_HEADING` and
            :tg-const:`telegram.InlineQueryResultLocation.MAX_HEADING` if specified.
        proximity_alert_radius (:obj:`int`): Optional. For live locations, a maximum distance
            for proximity alerts about approaching another chat member, in meters. Must be
            between :tg-const:`telegram.InlineQueryResultLocation.MIN_PROXIMITY_ALERT_RADIUS`
            and :tg-const:`telegram.InlineQueryResultLocation.MAX_PROXIMITY_ALERT_RADIUS`
            if specified.
        reply_markup (:class:`telegram.InlineKeyboardMarkup`): Optional. Inline keyboard attached
            to the message.
        input_message_content (:class:`telegram.InputMessageContent`): Optional. Content of the
            message to be sent instead of the location.
        thumbnail_url (:obj:`str`): Optional. Url of the thumbnail for the result.

            .. versionadded:: 20.2
        thumbnail_width (:obj:`int`): Optional. Thumbnail width.

            .. versionadded:: 20.2
        thumbnail_height (:obj:`int`): Optional. Thumbnail height.

            .. versionadded:: 20.2

    """

    __slots__ = (
        "_live_period",
        "heading",
        "horizontal_accuracy",
        "input_message_content",
        "latitude",
        "longitude",
        "proximity_alert_radius",
        "reply_markup",
        "thumbnail_height",
        "thumbnail_url",
        "thumbnail_width",
        "title",
    )

    def __init__(
        self,
        id: str,  # pylint: disable=redefined-builtin
        latitude: float,
        longitude: float,
        title: str,
        live_period: TimePeriod | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        input_message_content: "InputMessageContent | None" = None,
        horizontal_accuracy: float | None = None,
        heading: int | None = None,
        proximity_alert_radius: int | None = None,
        thumbnail_url: str | None = None,
        thumbnail_width: int | None = None,
        thumbnail_height: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        # Required
        super().__init__(constants.InlineQueryResultType.LOCATION, id, api_kwargs=api_kwargs)
        with self._unfrozen():
            self.latitude: float = latitude
            self.longitude: float = longitude
            self.title: str = title

            # Optionals
            self._live_period: dtm.timedelta | None = to_timedelta(live_period)
            self.reply_markup: InlineKeyboardMarkup | None = reply_markup
            self.input_message_content: InputMessageContent | None = input_message_content
            self.thumbnail_url: str | None = thumbnail_url
            self.thumbnail_width: int | None = thumbnail_width
            self.thumbnail_height: int | None = thumbnail_height
            self.horizontal_accuracy: float | None = horizontal_accuracy
            self.heading: int | None = heading
            self.proximity_alert_radius: int | None = (
                int(proximity_alert_radius) if proximity_alert_radius else None
            )

    @property
    def live_period(self) -> int | dtm.timedelta | None:
        return get_timedelta_value(self._live_period, attribute="live_period")

    HORIZONTAL_ACCURACY: Final[int] = constants.LocationLimit.HORIZONTAL_ACCURACY
    """:const:`telegram.constants.LocationLimit.HORIZONTAL_ACCURACY`

    .. versionadded:: 20.0
    """
    MIN_HEADING: Final[int] = constants.LocationLimit.MIN_HEADING
    """:const:`telegram.constants.LocationLimit.MIN_HEADING`

    .. versionadded:: 20.0
    """
    MAX_HEADING: Final[int] = constants.LocationLimit.MAX_HEADING
    """:const:`telegram.constants.LocationLimit.MAX_HEADING`

    .. versionadded:: 20.0
    """
    MIN_LIVE_PERIOD: Final[int] = constants.LocationLimit.MIN_LIVE_PERIOD
    """:const:`telegram.constants.LocationLimit.MIN_LIVE_PERIOD`

    .. versionadded:: 20.0
    """
    MAX_LIVE_PERIOD: Final[int] = constants.LocationLimit.MAX_LIVE_PERIOD
    """:const:`telegram.constants.LocationLimit.MAX_LIVE_PERIOD`

    .. versionadded:: 20.0
    """
    MIN_PROXIMITY_ALERT_RADIUS: Final[int] = constants.LocationLimit.MIN_PROXIMITY_ALERT_RADIUS
    """:const:`telegram.constants.LocationLimit.MIN_PROXIMITY_ALERT_RADIUS`

    .. versionadded:: 20.0
    """
    MAX_PROXIMITY_ALERT_RADIUS: Final[int] = constants.LocationLimit.MAX_PROXIMITY_ALERT_RADIUS
    """:const:`telegram.constants.LocationLimit.MAX_PROXIMITY_ALERT_RADIUS`

    .. versionadded:: 20.0
    """
