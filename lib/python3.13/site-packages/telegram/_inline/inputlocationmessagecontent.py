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
"""This module contains the classes that represent Telegram InputLocationMessageContent."""

import datetime as dtm
from typing import Final

from telegram import constants
from telegram._inline.inputmessagecontent import InputMessageContent
from telegram._utils.argumentparsing import to_timedelta
from telegram._utils.datetime import get_timedelta_value
from telegram._utils.types import JSONDict, TimePeriod


class InputLocationMessageContent(InputMessageContent):
    # fmt: off
    """
    Represents the content of a location message to be sent as the result of an inline query.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`latitude` and :attr:`longitude` are equal.

    Args:
        latitude (:obj:`float`): Latitude of the location in degrees.
        longitude (:obj:`float`): Longitude of the location in degrees.
        horizontal_accuracy (:obj:`float`, optional): The radius of uncertainty for the location,
            measured in meters; 0-
            :tg-const:`telegram.InputLocationMessageContent.HORIZONTAL_ACCURACY`.
        live_period (:obj:`int` | :class:`datetime.timedelta`, optional): Period in seconds for
            which the location will be updated, should be between
            :tg-const:`telegram.InputLocationMessageContent.MIN_LIVE_PERIOD` and
            :tg-const:`telegram.InputLocationMessageContent.MAX_LIVE_PERIOD` or
            :tg-const:`telegram.constants.LocationLimit.LIVE_PERIOD_FOREVER` for live
            locations that can be edited indefinitely.

            .. versionchanged:: v22.2
                |time-period-input|
        heading (:obj:`int`, optional): For live locations, a direction in which the user is
            moving, in degrees. Must be between
            :tg-const:`telegram.InputLocationMessageContent.MIN_HEADING` and
            :tg-const:`telegram.InputLocationMessageContent.MAX_HEADING` if specified.
        proximity_alert_radius (:obj:`int`, optional): For live locations, a maximum distance
            for proximity alerts about approaching another chat member, in meters. Must be
            between :tg-const:`telegram.InputLocationMessageContent.MIN_PROXIMITY_ALERT_RADIUS`
            and :tg-const:`telegram.InputLocationMessageContent.MAX_PROXIMITY_ALERT_RADIUS`
            if specified.

    Attributes:
        latitude (:obj:`float`): Latitude of the location in degrees.
        longitude (:obj:`float`): Longitude of the location in degrees.
        horizontal_accuracy (:obj:`float`): Optional. The radius of uncertainty for the location,
            measured in meters; 0-
            :tg-const:`telegram.InputLocationMessageContent.HORIZONTAL_ACCURACY`.
        live_period (:obj:`int` | :class:`datetime.timedelta`): Optional. Period in seconds for
            which the location can be updated, should be between
            :tg-const:`telegram.InputLocationMessageContent.MIN_LIVE_PERIOD` and
            :tg-const:`telegram.InputLocationMessageContent.MAX_LIVE_PERIOD`.

            .. deprecated:: v22.2
                |time-period-int-deprecated|
        heading (:obj:`int`): Optional. For live locations, a direction in which the user is
            moving, in degrees. Must be between
            :tg-const:`telegram.InputLocationMessageContent.MIN_HEADING` and
            :tg-const:`telegram.InputLocationMessageContent.MAX_HEADING` if specified.
        proximity_alert_radius (:obj:`int`): Optional. For live locations, a maximum distance
            for proximity alerts about approaching another chat member, in meters. Must be
            between :tg-const:`telegram.InputLocationMessageContent.MIN_PROXIMITY_ALERT_RADIUS`
            and :tg-const:`telegram.InputLocationMessageContent.MAX_PROXIMITY_ALERT_RADIUS`
            if specified.

    """

    __slots__ = (
        "_live_period",
        "heading",
        "horizontal_accuracy",
        "latitude",
        "longitude",
        "proximity_alert_radius",
    )
    # fmt: on

    def __init__(
        self,
        latitude: float,
        longitude: float,
        live_period: TimePeriod | None = None,
        horizontal_accuracy: float | None = None,
        heading: int | None = None,
        proximity_alert_radius: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        with self._unfrozen():
            # Required
            self.latitude: float = latitude
            self.longitude: float = longitude

            # Optionals
            self._live_period: dtm.timedelta | None = to_timedelta(live_period)
            self.horizontal_accuracy: float | None = horizontal_accuracy
            self.heading: int | None = heading
            self.proximity_alert_radius: int | None = (
                int(proximity_alert_radius) if proximity_alert_radius else None
            )

            self._id_attrs = (self.latitude, self.longitude)

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
