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
"""This module contains objects related to chat backgrounds."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._files.document import Document
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.argumentparsing import de_json_optional, parse_sequence_arg
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class BackgroundFill(TelegramObject):
    """Base class for Telegram BackgroundFill Objects. It can be one of:

    * :class:`telegram.BackgroundFillSolid`
    * :class:`telegram.BackgroundFillGradient`
    * :class:`telegram.BackgroundFillFreeformGradient`

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is equal.

    .. versionadded:: 21.2

    Args:
        type (:obj:`str`): Type of the background fill. Can be one of:
            :attr:`~telegram.BackgroundFill.SOLID`, :attr:`~telegram.BackgroundFill.GRADIENT`
            or :attr:`~telegram.BackgroundFill.FREEFORM_GRADIENT`.

    Attributes:
        type (:obj:`str`): Type of the background fill. Can be one of:
            :attr:`~telegram.BackgroundFill.SOLID`, :attr:`~telegram.BackgroundFill.GRADIENT`
            or :attr:`~telegram.BackgroundFill.FREEFORM_GRADIENT`.
    """

    __slots__ = ("type",)

    SOLID: Final[constants.BackgroundFillType] = constants.BackgroundFillType.SOLID
    """:const:`telegram.constants.BackgroundFillType.SOLID`"""
    GRADIENT: Final[constants.BackgroundFillType] = constants.BackgroundFillType.GRADIENT
    """:const:`telegram.constants.BackgroundFillType.GRADIENT`"""
    FREEFORM_GRADIENT: Final[constants.BackgroundFillType] = (
        constants.BackgroundFillType.FREEFORM_GRADIENT
    )
    """:const:`telegram.constants.BackgroundFillType.FREEFORM_GRADIENT`"""

    def __init__(
        self,
        type: str,  # pylint: disable=redefined-builtin
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required by all subclasses
        self.type: str = enum.get_member(constants.BackgroundFillType, type, type)

        self._id_attrs = (self.type,)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "BackgroundFill":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        _class_mapping: dict[str, type[BackgroundFill]] = {
            cls.SOLID: BackgroundFillSolid,
            cls.GRADIENT: BackgroundFillGradient,
            cls.FREEFORM_GRADIENT: BackgroundFillFreeformGradient,
        }

        if cls is BackgroundFill and data.get("type") in _class_mapping:
            return _class_mapping[data.pop("type")].de_json(data=data, bot=bot)

        return super().de_json(data=data, bot=bot)


class BackgroundFillSolid(BackgroundFill):
    """
    The background is filled using the selected color.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`color` is equal.

    .. versionadded:: 21.2

    Args:
        color (:obj:`int`): The color of the background fill in the `RGB24` format.

    Attributes:
        type (:obj:`str`): Type of the background fill. Always
            :attr:`~telegram.BackgroundFill.SOLID`.
        color (:obj:`int`): The color of the background fill in the `RGB24` format.
    """

    __slots__ = ("color",)

    def __init__(
        self,
        color: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.SOLID, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.color: int = color

            self._id_attrs = (self.color,)


class BackgroundFillGradient(BackgroundFill):
    """
    The background is a gradient fill.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`top_color`, :attr:`bottom_color`
    and :attr:`rotation_angle` are equal.

    .. versionadded:: 21.2

    Args:
        top_color (:obj:`int`): Top color of the gradient in the `RGB24` format.
        bottom_color (:obj:`int`): Bottom color of the gradient in the `RGB24` format.
        rotation_angle (:obj:`int`): Clockwise rotation angle of the background
            fill in degrees;
            0-:tg-const:`telegram.constants.BackgroundFillLimit.MAX_ROTATION_ANGLE`.


    Attributes:
        type (:obj:`str`): Type of the background fill. Always
            :attr:`~telegram.BackgroundFill.GRADIENT`.
        top_color (:obj:`int`): Top color of the gradient in the `RGB24` format.
        bottom_color (:obj:`int`): Bottom color of the gradient in the `RGB24` format.
        rotation_angle (:obj:`int`): Clockwise rotation angle of the background
            fill in degrees;
            0-:tg-const:`telegram.constants.BackgroundFillLimit.MAX_ROTATION_ANGLE`.
    """

    __slots__ = ("bottom_color", "rotation_angle", "top_color")

    def __init__(
        self,
        top_color: int,
        bottom_color: int,
        rotation_angle: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.GRADIENT, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.top_color: int = top_color
            self.bottom_color: int = bottom_color
            self.rotation_angle: int = rotation_angle

            self._id_attrs = (self.top_color, self.bottom_color, self.rotation_angle)


class BackgroundFillFreeformGradient(BackgroundFill):
    """
    The background is a freeform gradient that rotates after every message in the chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`colors` is equal.

    .. versionadded:: 21.2

    Args:
        colors (Sequence[:obj:`int`]): A list of the 3 or 4 base colors that are used to
            generate the freeform gradient in the `RGB24` format

    Attributes:
        type (:obj:`str`): Type of the background fill. Always
            :attr:`~telegram.BackgroundFill.FREEFORM_GRADIENT`.
        colors (Sequence[:obj:`int`]): A list of the 3 or 4 base colors that are used to
            generate the freeform gradient in the `RGB24` format
    """

    __slots__ = ("colors",)

    def __init__(
        self,
        colors: Sequence[int],
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.FREEFORM_GRADIENT, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.colors: tuple[int, ...] = parse_sequence_arg(colors)

            self._id_attrs = (self.colors,)


class BackgroundType(TelegramObject):
    """Base class for Telegram BackgroundType Objects. It can be one of:

    * :class:`telegram.BackgroundTypeFill`
    * :class:`telegram.BackgroundTypeWallpaper`
    * :class:`telegram.BackgroundTypePattern`
    * :class:`telegram.BackgroundTypeChatTheme`.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is equal.

    .. versionadded:: 21.2

    Args:
        type (:obj:`str`): Type of the background. Can be one of:
            :attr:`~telegram.BackgroundType.FILL`, :attr:`~telegram.BackgroundType.WALLPAPER`
            :attr:`~telegram.BackgroundType.PATTERN` or
            :attr:`~telegram.BackgroundType.CHAT_THEME`.

    Attributes:
        type (:obj:`str`): Type of the background. Can be one of:
            :attr:`~telegram.BackgroundType.FILL`, :attr:`~telegram.BackgroundType.WALLPAPER`
            :attr:`~telegram.BackgroundType.PATTERN` or
            :attr:`~telegram.BackgroundType.CHAT_THEME`.

    """

    __slots__ = ("type",)

    FILL: Final[constants.BackgroundTypeType] = constants.BackgroundTypeType.FILL
    """:const:`telegram.constants.BackgroundTypeType.FILL`"""
    WALLPAPER: Final[constants.BackgroundTypeType] = constants.BackgroundTypeType.WALLPAPER
    """:const:`telegram.constants.BackgroundTypeType.WALLPAPER`"""
    PATTERN: Final[constants.BackgroundTypeType] = constants.BackgroundTypeType.PATTERN
    """:const:`telegram.constants.BackgroundTypeType.PATTERN`"""
    CHAT_THEME: Final[constants.BackgroundTypeType] = constants.BackgroundTypeType.CHAT_THEME
    """:const:`telegram.constants.BackgroundTypeType.CHAT_THEME`"""

    def __init__(
        self,
        type: str,  # pylint: disable=redefined-builtin
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required by all subclasses
        self.type: str = enum.get_member(constants.BackgroundTypeType, type, type)

        self._id_attrs = (self.type,)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "BackgroundType":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        _class_mapping: dict[str, type[BackgroundType]] = {
            cls.FILL: BackgroundTypeFill,
            cls.WALLPAPER: BackgroundTypeWallpaper,
            cls.PATTERN: BackgroundTypePattern,
            cls.CHAT_THEME: BackgroundTypeChatTheme,
        }

        if cls is BackgroundType and data.get("type") in _class_mapping:
            return _class_mapping[data.pop("type")].de_json(data=data, bot=bot)

        if "fill" in data:
            data["fill"] = de_json_optional(data.get("fill"), BackgroundFill, bot)

        if "document" in data:
            data["document"] = de_json_optional(data.get("document"), Document, bot)

        return super().de_json(data=data, bot=bot)


class BackgroundTypeFill(BackgroundType):
    """
    The background is automatically filled based on the selected colors.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`fill` and :attr:`dark_theme_dimming` are equal.

    .. versionadded:: 21.2

    Args:
        fill (:class:`telegram.BackgroundFill`): The background fill.
        dark_theme_dimming (:obj:`int`): Dimming of the background in dark themes, as a
            percentage;
            0-:tg-const:`telegram.constants.BackgroundTypeLimit.MAX_DIMMING`.

    Attributes:
        type (:obj:`str`): Type of the background. Always
            :attr:`~telegram.BackgroundType.FILL`.
        fill (:class:`telegram.BackgroundFill`): The background fill.
        dark_theme_dimming (:obj:`int`): Dimming of the background in dark themes, as a
            percentage;
            0-:tg-const:`telegram.constants.BackgroundTypeLimit.MAX_DIMMING`.
    """

    __slots__ = ("dark_theme_dimming", "fill")

    def __init__(
        self,
        fill: BackgroundFill,
        dark_theme_dimming: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.FILL, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.fill: BackgroundFill = fill
            self.dark_theme_dimming: int = dark_theme_dimming

            self._id_attrs = (self.fill, self.dark_theme_dimming)


class BackgroundTypeWallpaper(BackgroundType):
    """
    The background is a wallpaper in the `JPEG` format.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`document` and :attr:`dark_theme_dimming` are equal.

    .. versionadded:: 21.2

    Args:
        document (:class:`telegram.Document`): Document with the wallpaper
        dark_theme_dimming (:obj:`int`): Dimming of the background in dark themes, as a
            percentage;
            0-:tg-const:`telegram.constants.BackgroundTypeLimit.MAX_DIMMING`.
        is_blurred (:obj:`bool`, optional): :obj:`True`, if the wallpaper is downscaled to fit
            in a 450x450 square and then box-blurred with radius 12
        is_moving (:obj:`bool`, optional): :obj:`True`, if the background moves slightly
            when the device is tilted

    Attributes:
        type (:obj:`str`): Type of the background. Always
            :attr:`~telegram.BackgroundType.WALLPAPER`.
        document (:class:`telegram.Document`): Document with the wallpaper
        dark_theme_dimming (:obj:`int`): Dimming of the background in dark themes, as a
            percentage;
            0-:tg-const:`telegram.constants.BackgroundTypeLimit.MAX_DIMMING`.
        is_blurred (:obj:`bool`): Optional. :obj:`True`, if the wallpaper is downscaled to fit
            in a 450x450 square and then box-blurred with radius 12
        is_moving (:obj:`bool`): Optional. :obj:`True`, if the background moves slightly
            when the device is tilted
    """

    __slots__ = ("dark_theme_dimming", "document", "is_blurred", "is_moving")

    def __init__(
        self,
        document: Document,
        dark_theme_dimming: int,
        is_blurred: bool | None = None,
        is_moving: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.WALLPAPER, api_kwargs=api_kwargs)

        with self._unfrozen():
            # Required
            self.document: Document = document
            self.dark_theme_dimming: int = dark_theme_dimming
            # Optionals
            self.is_blurred: bool | None = is_blurred
            self.is_moving: bool | None = is_moving

            self._id_attrs = (self.document, self.dark_theme_dimming)


class BackgroundTypePattern(BackgroundType):
    """
    The background is a ``.PNG`` or ``.TGV`` (gzipped subset of ``SVG`` with ``MIME`` type
    ``"application/x-tgwallpattern"``) pattern to be combined with the background fill
    chosen by the user.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`document` and :attr:`fill` and :attr:`intensity` are equal.

    .. versionadded:: 21.2

    Args:
        document (:class:`telegram.Document`): Document with the pattern.
        fill (:class:`telegram.BackgroundFill`): The background fill that is combined with
            the pattern.
        intensity (:obj:`int`): Intensity of the pattern when it is shown above the filled
            background;
            0-:tg-const:`telegram.constants.BackgroundTypeLimit.MAX_INTENSITY`.
        is_inverted (:obj:`int`, optional): :obj:`True`, if the background fill must be applied
            only to the pattern itself. All other pixels are black in this case. For dark
            themes only.
        is_moving (:obj:`bool`, optional): :obj:`True`, if the background moves slightly
            when the device is tilted.

    Attributes:
        type (:obj:`str`): Type of the background. Always
            :attr:`~telegram.BackgroundType.PATTERN`.
        document (:class:`telegram.Document`): Document with the pattern.
        fill (:class:`telegram.BackgroundFill`): The background fill that is combined with
            the pattern.
        intensity (:obj:`int`): Intensity of the pattern when it is shown above the filled
            background;
            0-:tg-const:`telegram.constants.BackgroundTypeLimit.MAX_INTENSITY`.
        is_inverted (:obj:`int`): Optional. :obj:`True`, if the background fill must be applied
            only to the pattern itself. All other pixels are black in this case. For dark
            themes only.
        is_moving (:obj:`bool`): Optional. :obj:`True`, if the background moves slightly
            when the device is tilted.
    """

    __slots__ = (
        "document",
        "fill",
        "intensity",
        "is_inverted",
        "is_moving",
    )

    def __init__(
        self,
        document: Document,
        fill: BackgroundFill,
        intensity: int,
        is_inverted: bool | None = None,
        is_moving: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.PATTERN, api_kwargs=api_kwargs)

        with self._unfrozen():
            # Required
            self.document: Document = document
            self.fill: BackgroundFill = fill
            self.intensity: int = intensity
            # Optionals
            self.is_inverted: bool | None = is_inverted
            self.is_moving: bool | None = is_moving

            self._id_attrs = (self.document, self.fill, self.intensity)


class BackgroundTypeChatTheme(BackgroundType):
    """
    The background is taken directly from a built-in chat theme.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`theme_name` is equal.

    .. versionadded:: 21.2

    Args:
        theme_name (:obj:`str`): Name of the chat theme, which is usually an emoji.

    Attributes:
        type (:obj:`str`): Type of the background. Always
            :attr:`~telegram.BackgroundType.CHAT_THEME`.
        theme_name (:obj:`str`): Name of the chat theme, which is usually an emoji.
    """

    __slots__ = ("theme_name",)

    def __init__(
        self,
        theme_name: str,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(type=self.CHAT_THEME, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.theme_name: str = theme_name

            self._id_attrs = (self.theme_name,)


class ChatBackground(TelegramObject):
    """
    This object represents a chat background.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is  equal.

    .. versionadded:: 21.2

    Args:
        type (:class:`telegram.BackgroundType`): Type of the background.

    Attributes:
        type (:class:`telegram.BackgroundType`): Type of the background.
    """

    __slots__ = ("type",)

    def __init__(
        self,
        type: BackgroundType,  # pylint: disable=redefined-builtin
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.type: BackgroundType = type

        self._id_attrs = (self.type,)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChatBackground":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["type"] = de_json_optional(data.get("type"), BackgroundType, bot)

        return super().de_json(data=data, bot=bot)
