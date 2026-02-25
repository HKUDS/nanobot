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
"""This module contains objects that represent stickers."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._files._basethumbedmedium import _BaseThumbedMedium
from telegram._files.file import File
from telegram._files.photosize import PhotoSize
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.argumentparsing import de_json_optional, de_list_optional, parse_sequence_arg
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class Sticker(_BaseThumbedMedium):
    """This object represents a sticker.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`file_unique_id` is equal.

    Note:
        As of v13.11 :paramref:`is_video` is a required argument and therefore the order of the
        arguments had to be changed. Use keyword arguments to make sure that the arguments are
        passed correctly.

    .. versionchanged:: 20.5
      |removed_thumb_note|

    Args:
        file_id (:obj:`str`): Identifier for this file, which can be used to download
            or reuse the file.
        file_unique_id (:obj:`str`): Unique identifier for this file, which
            is supposed to be the same over time and for different bots.
            Can't be used to download or reuse the file.
        width (:obj:`int`): Sticker width.
        height (:obj:`int`): Sticker height.
        is_animated (:obj:`bool`): :obj:`True`, if the sticker is animated.
        is_video (:obj:`bool`): :obj:`True`, if the sticker is a video sticker.

            .. versionadded:: 13.11
        type (:obj:`str`): Type of the sticker. Currently one of :attr:`REGULAR`,
            :attr:`MASK`, :attr:`CUSTOM_EMOJI`. The type of the sticker is independent from its
            format, which is determined by the fields :attr:`is_animated` and :attr:`is_video`.

            .. versionadded:: 20.0
        emoji (:obj:`str`, optional): Emoji associated with the sticker
        set_name (:obj:`str`, optional): Name of the sticker set to which the sticker belongs.
        mask_position (:class:`telegram.MaskPosition`, optional): For mask stickers, the position
            where the mask should be placed.
        file_size (:obj:`int`, optional): File size in bytes.

        premium_animation (:class:`telegram.File`, optional): For premium regular stickers,
            premium animation for the sticker.

            .. versionadded:: 20.0
        custom_emoji_id (:obj:`str`, optional): For custom emoji stickers, unique identifier of the
            custom emoji.

            .. versionadded:: 20.0
        thumbnail (:class:`telegram.PhotoSize`, optional): Sticker thumbnail in the ``.WEBP`` or
            ``.JPG`` format.

            .. versionadded:: 20.2
        needs_repainting (:obj:`bool`, optional): :obj:`True`, if the sticker must be repainted to
            a text color in messages, the color of the Telegram Premium badge in emoji status,
            white color on chat photos, or another appropriate color in other places.

            .. versionadded:: 20.2

    Attributes:
        file_id (:obj:`str`): Identifier for this file, which can be used to download
            or reuse the file.
        file_unique_id (:obj:`str`): Unique identifier for this file, which
            is supposed to be the same over time and for different bots.
            Can't be used to download or reuse the file.
        width (:obj:`int`): Sticker width.
        height (:obj:`int`): Sticker height.
        is_animated (:obj:`bool`): :obj:`True`, if the sticker is animated.
        is_video (:obj:`bool`): :obj:`True`, if the sticker is a video sticker.

            .. versionadded:: 13.11
        type (:obj:`str`): Type of the sticker. Currently one of :attr:`REGULAR`,
            :attr:`MASK`, :attr:`CUSTOM_EMOJI`. The type of the sticker is independent from its
            format, which is determined by the fields :attr:`is_animated` and :attr:`is_video`.

            .. versionadded:: 20.0
        emoji (:obj:`str`): Optional. Emoji associated with the sticker.
        set_name (:obj:`str`): Optional. Name of the sticker set to which the sticker belongs.
        mask_position (:class:`telegram.MaskPosition`): Optional. For mask stickers, the position
            where the mask should be placed.
        file_size (:obj:`int`): Optional. File size in bytes.

        premium_animation (:class:`telegram.File`): Optional. For premium regular stickers,
            premium animation for the sticker.

            .. versionadded:: 20.0
        custom_emoji_id (:obj:`str`): Optional. For custom emoji stickers, unique identifier of the
            custom emoji.

            .. versionadded:: 20.0
        thumbnail (:class:`telegram.PhotoSize`): Optional. Sticker thumbnail in the ``.WEBP`` or
            ``.JPG`` format.

            .. versionadded:: 20.2
        needs_repainting (:obj:`bool`): Optional. :obj:`True`, if the sticker must be repainted to
            a text color in messages, the color of the Telegram Premium badge in emoji status,
            white color on chat photos, or another appropriate color in other places.

            .. versionadded:: 20.2
    """

    __slots__ = (
        "custom_emoji_id",
        "emoji",
        "height",
        "is_animated",
        "is_video",
        "mask_position",
        "needs_repainting",
        "premium_animation",
        "set_name",
        "type",
        "width",
    )

    def __init__(
        self,
        file_id: str,
        file_unique_id: str,
        width: int,
        height: int,
        is_animated: bool,
        is_video: bool,
        type: str,  # pylint: disable=redefined-builtin
        emoji: str | None = None,
        file_size: int | None = None,
        set_name: str | None = None,
        mask_position: "MaskPosition | None" = None,
        premium_animation: "File | None" = None,
        custom_emoji_id: str | None = None,
        thumbnail: PhotoSize | None = None,
        needs_repainting: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_size=file_size,
            thumbnail=thumbnail,
            api_kwargs=api_kwargs,
        )
        with self._unfrozen():
            # Required
            self.width: int = width
            self.height: int = height
            self.is_animated: bool = is_animated
            self.is_video: bool = is_video
            self.type: str = enum.get_member(constants.StickerType, type, type)
            # Optional
            self.emoji: str | None = emoji
            self.set_name: str | None = set_name
            self.mask_position: MaskPosition | None = mask_position
            self.premium_animation: File | None = premium_animation
            self.custom_emoji_id: str | None = custom_emoji_id
            self.needs_repainting: bool | None = needs_repainting

    REGULAR: Final[str] = constants.StickerType.REGULAR
    """:const:`telegram.constants.StickerType.REGULAR`"""
    MASK: Final[str] = constants.StickerType.MASK
    """:const:`telegram.constants.StickerType.MASK`"""
    CUSTOM_EMOJI: Final[str] = constants.StickerType.CUSTOM_EMOJI
    """:const:`telegram.constants.StickerType.CUSTOM_EMOJI`"""

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "Sticker":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["thumbnail"] = de_json_optional(data.get("thumbnail"), PhotoSize, bot)
        data["mask_position"] = de_json_optional(data.get("mask_position"), MaskPosition, bot)
        data["premium_animation"] = de_json_optional(data.get("premium_animation"), File, bot)

        api_kwargs = {}
        # This is a deprecated field that TG still returns for backwards compatibility
        # Let's filter it out to speed up the de-json process
        if data.get("thumb") is not None:
            api_kwargs["thumb"] = data.pop("thumb")

        return super()._de_json(data=data, bot=bot, api_kwargs=api_kwargs)


class StickerSet(TelegramObject):
    """This object represents a sticker set.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`name` is equal.

    Note:
        As of v13.11 :paramref:`is_video` is a required argument and therefore the order of the
        arguments had to be changed. Use keyword arguments to make sure that the arguments are
        passed correctly.

    .. versionchanged:: 20.0
        The parameter ``contains_masks`` has been removed. Use :paramref:`sticker_type` instead.


    .. versionchanged:: 21.1
        The parameters ``is_video`` and ``is_animated`` are deprecated and now made optional. Thus,
        the order of the arguments had to be changed.

    .. versionchanged:: 20.5
       |removed_thumb_note|

    .. versionremoved:: 21.2
       Removed the deprecated arguments and attributes ``is_animated`` and ``is_video``.

    Args:
        name (:obj:`str`): Sticker set name.
        title (:obj:`str`): Sticker set title.
        stickers (Sequence[:class:`telegram.Sticker`]): List of all set stickers.

            .. versionchanged:: 20.0
                |sequenceclassargs|

        sticker_type (:obj:`str`): Type of stickers in the set, currently one of
            :attr:`telegram.Sticker.REGULAR`, :attr:`telegram.Sticker.MASK`,
            :attr:`telegram.Sticker.CUSTOM_EMOJI`.

            .. versionadded:: 20.0
        thumbnail (:class:`telegram.PhotoSize`, optional): Sticker set thumbnail in the ``.WEBP``,
            ``.TGS``, or ``.WEBM`` format.

            .. versionadded:: 20.2

    Attributes:
        name (:obj:`str`): Sticker set name.
        title (:obj:`str`): Sticker set title.
        stickers (tuple[:class:`telegram.Sticker`]): List of all set stickers.

            .. versionchanged:: 20.0
                |tupleclassattrs|

        sticker_type (:obj:`str`): Type of stickers in the set, currently one of
            :attr:`telegram.Sticker.REGULAR`, :attr:`telegram.Sticker.MASK`,
            :attr:`telegram.Sticker.CUSTOM_EMOJI`.

            .. versionadded:: 20.0
        thumbnail (:class:`telegram.PhotoSize`): Optional. Sticker set thumbnail in the ``.WEBP``,
            ``.TGS``, or ``.WEBM`` format.

            .. versionadded:: 20.2
    """

    __slots__ = (
        "name",
        "sticker_type",
        "stickers",
        "thumbnail",
        "title",
    )

    def __init__(
        self,
        name: str,
        title: str,
        stickers: Sequence[Sticker],
        sticker_type: str,
        thumbnail: PhotoSize | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.name: str = name
        self.title: str = title
        self.stickers: tuple[Sticker, ...] = parse_sequence_arg(stickers)
        self.sticker_type: str = sticker_type
        # Optional
        self.thumbnail: PhotoSize | None = thumbnail
        self._id_attrs = (self.name,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "StickerSet":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["thumbnail"] = de_json_optional(data.get("thumbnail"), PhotoSize, bot)
        data["stickers"] = de_list_optional(data.get("stickers"), Sticker, bot)

        api_kwargs = {}
        # These are deprecated fields that TG still returns for backwards compatibility
        # Let's filter them out to speed up the de-json process
        for deprecated_field in ("contains_masks", "thumb", "is_animated", "is_video"):
            if deprecated_field in data:
                api_kwargs[deprecated_field] = data.pop(deprecated_field)

        return super()._de_json(data=data, bot=bot, api_kwargs=api_kwargs)


class MaskPosition(TelegramObject):
    """This object describes the position on faces where a mask should be placed by default.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`point`, :attr:`x_shift`, :attr:`y_shift` and, :attr:`scale`
    are equal.

    Args:
        point (:obj:`str`): The part of the face relative to which the mask should be placed.
            One of :attr:`FOREHEAD`, :attr:`EYES`, :attr:`MOUTH`, or :attr:`CHIN`.
        x_shift (:obj:`float`): Shift by X-axis measured in widths of the mask scaled to the face
            size, from left to right. For example, choosing ``-1.0`` will place mask just to the
            left of the default mask position.
        y_shift (:obj:`float`): Shift by Y-axis measured in heights of the mask scaled to the face
            size, from top to bottom. For example, ``1.0`` will place the mask just below the
            default mask position.
        scale (:obj:`float`): Mask scaling coefficient. For example, ``2.0`` means double size.

    Attributes:
        point (:obj:`str`): The part of the face relative to which the mask should be placed.
            One of :attr:`FOREHEAD`, :attr:`EYES`, :attr:`MOUTH`, or :attr:`CHIN`.
        x_shift (:obj:`float`): Shift by X-axis measured in widths of the mask scaled to the face
            size, from left to right. For example, choosing ``-1.0`` will place mask just to the
            left of the default mask position.
        y_shift (:obj:`float`): Shift by Y-axis measured in heights of the mask scaled to the face
            size, from top to bottom. For example, ``1.0`` will place the mask just below the
            default mask position.
        scale (:obj:`float`): Mask scaling coefficient. For example, ``2.0`` means double size.

    """

    __slots__ = ("point", "scale", "x_shift", "y_shift")

    FOREHEAD: Final[str] = constants.MaskPosition.FOREHEAD
    """:const:`telegram.constants.MaskPosition.FOREHEAD`"""
    EYES: Final[str] = constants.MaskPosition.EYES
    """:const:`telegram.constants.MaskPosition.EYES`"""
    MOUTH: Final[str] = constants.MaskPosition.MOUTH
    """:const:`telegram.constants.MaskPosition.MOUTH`"""
    CHIN: Final[str] = constants.MaskPosition.CHIN
    """:const:`telegram.constants.MaskPosition.CHIN`"""

    def __init__(
        self,
        point: str,
        x_shift: float,
        y_shift: float,
        scale: float,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.point: str = point
        self.x_shift: float = x_shift
        self.y_shift: float = y_shift
        self.scale: float = scale

        self._id_attrs = (self.point, self.x_shift, self.y_shift, self.scale)

        self._freeze()
