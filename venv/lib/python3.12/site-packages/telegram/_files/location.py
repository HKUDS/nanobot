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
"""This module contains an object that represents a Telegram Location."""

import datetime as dtm
from typing import Final

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import to_timedelta
from telegram._utils.datetime import get_timedelta_value
from telegram._utils.types import JSONDict, TimePeriod


class Location(TelegramObject):
    """This object represents a point on the map.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`longitude` and :attr:`latitude` are equal.

    Args:
        longitude (:obj:`float`): Longitude as defined by the sender.
        latitude (:obj:`float`): Latitude as defined by the sender.
        horizontal_accuracy (:obj:`float`, optional): The radius of uncertainty for the location,
            measured in meters; 0-:tg-const:`telegram.Location.HORIZONTAL_ACCURACY`.
        live_period (:obj:`int` | :class:`datetime.timedelta`, optional): Time relative to the
            message sending date, during which the location can be updated, in seconds. For active
            live locations only.

            .. versionchanged:: v22.2
                |time-period-input|
        heading (:obj:`int`, optional): The direction in which user is moving, in degrees;
            :tg-const:`telegram.Location.MIN_HEADING`-:tg-const:`telegram.Location.MAX_HEADING`.
            For active live locations only.
        proximity_alert_radius (:obj:`int`, optional): Maximum distance for proximity alerts about
            approaching another chat member, in meters. For sent live locations only.

    Attributes:
        longitude (:obj:`float`): Longitude as defined by the sender.
        latitude (:obj:`float`): Latitude as defined by the sender.
        horizontal_accuracy (:obj:`float`): Optional. The radius of uncertainty for the location,
            measured in meters; 0-:tg-const:`telegram.Location.HORIZONTAL_ACCURACY`.
        live_period (:obj:`int` | :class:`datetime.timedelta`): Optional. Time relative to the
            message sending date, during which the location can be updated, in seconds. For active
            live locations only.

            .. deprecated:: v22.2
                |time-period-int-deprecated|
        heading (:obj:`int`): Optional. The direction in which user is moving, in degrees;
            :tg-const:`telegram.Location.MIN_HEADING`-:tg-const:`telegram.Location.MAX_HEADING`.
            For active live locations only.
        proximity_alert_radius (:obj:`int`): Optional. Maximum distance for proximity alerts about
            approaching another chat member, in meters. For sent live locations only.

    """

    __slots__ = (
        "_live_period",
        "heading",
        "horizontal_accuracy",
        "latitude",
        "longitude",
        "proximity_alert_radius",
    )

    def __init__(
        self,
        longitude: float,
        latitude: float,
        horizontal_accuracy: float | None = None,
        live_period: TimePeriod | None = None,
        heading: int | None = None,
        proximity_alert_radius: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.longitude: float = longitude
        self.latitude: float = latitude

        # Optionals
        self.horizontal_accuracy: float | None = horizontal_accuracy
        self._live_period: dtm.timedelta | None = to_timedelta(live_period)
        self.heading: int | None = heading
        self.proximity_alert_radius: int | None = (
            int(proximity_alert_radius) if proximity_alert_radius else None
        )

        self._id_attrs = (self.longitude, self.latitude)

        self._freeze()

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
