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
"""This module contains objects that represent story areas."""

from typing import Final

from telegram import constants
from telegram._reaction import ReactionType
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.types import JSONDict


class StoryAreaPosition(TelegramObject):
    """Describes the position of a clickable area within a story.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if all of their attributes are equal.

    .. versionadded:: 22.1

    Args:
        x_percentage (:obj:`float`): The abscissa of the area's center, as a percentage of the
            media width.
        y_percentage (:obj:`float`): The ordinate of the area's center, as a percentage of the
            media height.
        width_percentage (:obj:`float`): The width of the area's rectangle, as a percentage of the
            media width.
        height_percentage (:obj:`float`): The height of the area's rectangle, as a percentage of
            the media height.
        rotation_angle (:obj:`float`): The clockwise rotation angle of the rectangle, in degrees;
            0-:tg-const:`~telegram.constants.StoryAreaPositionLimit.MAX_ROTATION_ANGLE`.
        corner_radius_percentage (:obj:`float`): The radius of the rectangle corner rounding, as a
            percentage of the media width.

    Attributes:
        x_percentage (:obj:`float`): The abscissa of the area's center, as a percentage of the
            media width.
        y_percentage (:obj:`float`): The ordinate of the area's center, as a percentage of the
            media height.
        width_percentage (:obj:`float`): The width of the area's rectangle, as a percentage of the
            media width.
        height_percentage (:obj:`float`): The height of the area's rectangle, as a percentage of
            the media height.
        rotation_angle (:obj:`float`): The clockwise rotation angle of the rectangle, in degrees;
            0-:tg-const:`~telegram.constants.StoryAreaPositionLimit.MAX_ROTATION_ANGLE`.
        corner_radius_percentage (:obj:`float`): The radius of the rectangle corner rounding, as a
            percentage of the media width.

    """

    __slots__ = (
        "corner_radius_percentage",
        "height_percentage",
        "rotation_angle",
        "width_percentage",
        "x_percentage",
        "y_percentage",
    )

    def __init__(
        self,
        x_percentage: float,
        y_percentage: float,
        width_percentage: float,
        height_percentage: float,
        rotation_angle: float,
        corner_radius_percentage: float,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.x_percentage: float = x_percentage
        self.y_percentage: float = y_percentage
        self.width_percentage: float = width_percentage
        self.height_percentage: float = height_percentage
        self.rotation_angle: float = rotation_angle
        self.corner_radius_percentage: float = corner_radius_percentage

        self._id_attrs = (
            self.x_percentage,
            self.y_percentage,
            self.width_percentage,
            self.height_percentage,
            self.rotation_angle,
            self.corner_radius_percentage,
        )
        self._freeze()


class LocationAddress(TelegramObject):
    """Describes the physical address of a location.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`country_code`, :attr:`state`, :attr:`city` and :attr:`street`
    are equal.

    .. versionadded:: 22.1

    Args:
        country_code (:obj:`str`): The two-letter ``ISO 3166-1 alpha-2`` country code of the
            country where the location is located.
        state (:obj:`str`, optional): State of the location.
        city (:obj:`str`, optional): City of the location.
        street (:obj:`str`, optional): Street address of the location.

    Attributes:
        country_code (:obj:`str`): The two-letter ``ISO 3166-1 alpha-2`` country code of the
            country where the location is located.
        state (:obj:`str`): Optional. State of the location.
        city (:obj:`str`): Optional. City of the location.
        street (:obj:`str`): Optional. Street address of the location.

    """

    __slots__ = ("city", "country_code", "state", "street")

    def __init__(
        self,
        country_code: str,
        state: str | None = None,
        city: str | None = None,
        street: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.country_code: str = country_code
        self.state: str | None = state
        self.city: str | None = city
        self.street: str | None = street

        self._id_attrs = (self.country_code, self.state, self.city, self.street)
        self._freeze()


class StoryAreaType(TelegramObject):
    """Describes the type of a clickable area on a story. Currently, it can be one of:

    * :class:`telegram.StoryAreaTypeLocation`
    * :class:`telegram.StoryAreaTypeSuggestedReaction`
    * :class:`telegram.StoryAreaTypeLink`
    * :class:`telegram.StoryAreaTypeWeather`
    * :class:`telegram.StoryAreaTypeUniqueGift`

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is equal.

    .. versionadded:: 22.1

    Args:
        type (:obj:`str`): Type of the area.

    Attributes:
        type (:obj:`str`): Type of the area.

    """

    __slots__ = ("type",)

    LOCATION: Final[str] = constants.StoryAreaTypeType.LOCATION
    """:const:`telegram.constants.StoryAreaTypeType.LOCATION`"""
    SUGGESTED_REACTION: Final[str] = constants.StoryAreaTypeType.SUGGESTED_REACTION
    """:const:`telegram.constants.StoryAreaTypeType.SUGGESTED_REACTION`"""
    LINK: Final[str] = constants.StoryAreaTypeType.LINK
    """:const:`telegram.constants.StoryAreaTypeType.LINK`"""
    WEATHER: Final[str] = constants.StoryAreaTypeType.WEATHER
    """:const:`telegram.constants.StoryAreaTypeType.WEATHER`"""
    UNIQUE_GIFT: Final[str] = constants.StoryAreaTypeType.UNIQUE_GIFT
    """:const:`telegram.constants.StoryAreaTypeType.UNIQUE_GIFT`"""

    def __init__(
        self,
        type: str,  # pylint: disable=redefined-builtin
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.type: str = enum.get_member(constants.StoryAreaTypeType, type, type)

        self._id_attrs = (self.type,)
        self._freeze()


class StoryAreaTypeLocation(StoryAreaType):
    """Describes a story area pointing to a location. Currently, a story can have up to
    :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_LOCATION_AREAS` location areas.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`latitude` and :attr:`longitude` are equal.

    .. versionadded:: 22.1

    Args:
        latitude (:obj:`float`): Location latitude in degrees.
        longitude (:obj:`float`): Location longitude in degrees.
        address (:class:`telegram.LocationAddress`, optional): Address of the location.

    Attributes:
        type (:obj:`str`): Type of the area, always :attr:`~telegram.StoryAreaType.LOCATION`.
        latitude (:obj:`float`): Location latitude in degrees.
        longitude (:obj:`float`): Location longitude in degrees.
        address (:class:`telegram.LocationAddress`): Optional. Address of the location.

    """

    __slots__ = ("address", "latitude", "longitude")

    def __init__(
        self,
        latitude: float,
        longitude: float,
        address: LocationAddress | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=StoryAreaType.LOCATION, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.latitude: float = latitude
            self.longitude: float = longitude
            self.address: LocationAddress | None = address

            self._id_attrs = (self.type, self.latitude, self.longitude)


class StoryAreaTypeSuggestedReaction(StoryAreaType):
    """
    Describes a story area pointing to a suggested reaction. Currently, a story can have up to
    :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_SUGGESTED_REACTION_AREAS`
    suggested reaction areas.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`reaction_type`, :attr:`is_dark` and :attr:`is_flipped`
    are equal.

    .. versionadded:: 22.1

    Args:
        reaction_type (:class:`ReactionType`): Type of the reaction.
        is_dark (:obj:`bool`, optional): Pass :obj:`True` if the reaction area has a dark
            background.
        is_flipped (:obj:`bool`, optional): Pass :obj:`True` if reaction area corner is flipped.

    Attributes:
        type (:obj:`str`): Type of the area, always
            :tg-const:`~telegram.StoryAreaType.SUGGESTED_REACTION`.
        reaction_type (:class:`ReactionType`): Type of the reaction.
        is_dark (:obj:`bool`): Optional. Pass :obj:`True` if the reaction area has a dark
            background.
        is_flipped (:obj:`bool`): Optional. Pass :obj:`True` if reaction area corner is flipped.

    """

    __slots__ = ("is_dark", "is_flipped", "reaction_type")

    def __init__(
        self,
        reaction_type: ReactionType,
        is_dark: bool | None = None,
        is_flipped: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=StoryAreaType.SUGGESTED_REACTION, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.reaction_type: ReactionType = reaction_type
            self.is_dark: bool | None = is_dark
            self.is_flipped: bool | None = is_flipped

            self._id_attrs = (self.type, self.reaction_type, self.is_dark, self.is_flipped)


class StoryAreaTypeLink(StoryAreaType):
    """Describes a story area pointing to an ``HTTP`` or ``tg://`` link. Currently, a story can
    have up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_LINK_AREAS` link areas.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`url` is equal.

    .. versionadded:: 22.1

    Args:
        url (:obj:`str`): ``HTTP`` or ``tg://`` URL to be opened when the area is clicked.

    Attributes:
        type (:obj:`str`): Type of the area, always :attr:`~telegram.StoryAreaType.LINK`.
        url (:obj:`str`): ``HTTP`` or ``tg://`` URL to be opened when the area is clicked.

    """

    __slots__ = ("url",)

    def __init__(
        self,
        url: str,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=StoryAreaType.LINK, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.url: str = url

            self._id_attrs = (self.type, self.url)


class StoryAreaTypeWeather(StoryAreaType):
    """
    Describes a story area containing weather information. Currently, a story can have up to
    :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_WEATHER_AREAS` weather areas.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`temperature`, :attr:`emoji` and
    :attr:`background_color` are equal.

    .. versionadded:: 22.1

    Args:
        temperature (:obj:`float`): Temperature, in degree Celsius.
        emoji (:obj:`str`): Emoji representing the weather.
        background_color (:obj:`int`): A color of the area background in the ``ARGB`` format.

    Attributes:
        type (:obj:`str`): Type of the area, always
            :tg-const:`~telegram.StoryAreaType.WEATHER`.
        temperature (:obj:`float`): Temperature, in degree Celsius.
        emoji (:obj:`str`): Emoji representing the weather.
        background_color (:obj:`int`): A color of the area background in the ``ARGB`` format.

    """

    __slots__ = ("background_color", "emoji", "temperature")

    def __init__(
        self,
        temperature: float,
        emoji: str,
        background_color: int,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=StoryAreaType.WEATHER, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.temperature: float = temperature
            self.emoji: str = emoji
            self.background_color: int = background_color

            self._id_attrs = (self.type, self.temperature, self.emoji, self.background_color)


class StoryAreaTypeUniqueGift(StoryAreaType):
    """
    Describes a story area pointing to a unique gift. Currently, a story can have at most
    :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_UNIQUE_GIFT_AREAS` unique gift area.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`name` is equal.

    .. versionadded:: 22.1

    Args:
        name (:obj:`str`): Unique name of the gift.

    Attributes:
        type (:obj:`str`): Type of the area, always
            :tg-const:`~telegram.StoryAreaType.UNIQUE_GIFT`.
        name (:obj:`str`): Unique name of the gift.

    """

    __slots__ = ("name",)

    def __init__(
        self,
        name: str,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=StoryAreaType.UNIQUE_GIFT, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.name: str = name

            self._id_attrs = (self.type, self.name)


class StoryArea(TelegramObject):
    """Describes a clickable area on a story media.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`position` and :attr:`type` are equal.

    .. versionadded:: 22.1

    Args:
        position (:class:`telegram.StoryAreaPosition`): Position of the area.
        type (:class:`telegram.StoryAreaType`): Type of the area.

    Attributes:
        position (:class:`telegram.StoryAreaPosition`): Position of the area.
        type (:class:`telegram.StoryAreaType`): Type of the area.

    """

    __slots__ = ("position", "type")

    def __init__(
        self,
        position: StoryAreaPosition,
        type: StoryAreaType,  # pylint: disable=redefined-builtin
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.position: StoryAreaPosition = position
        self.type: StoryAreaType = type
        self._id_attrs = (self.position, self.type)

        self._freeze()
