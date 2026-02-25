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
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._files.photosize import PhotoSize
from telegram._files.video import Video
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils import enum
from telegram._utils.argumentparsing import (
    de_json_optional,
    de_list_optional,
    parse_sequence_arg,
    to_timedelta,
)
from telegram._utils.datetime import get_timedelta_value
from telegram._utils.types import JSONDict, TimePeriod

if TYPE_CHECKING:
    from telegram import Bot


class PaidMedia(TelegramObject):
    """Describes the paid media added to a message. Currently, it can be one of:

    * :class:`telegram.PaidMediaPreview`
    * :class:`telegram.PaidMediaPhoto`
    * :class:`telegram.PaidMediaVideo`

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is equal.

    .. versionadded:: 21.4

    Args:
        type (:obj:`str`): Type of the paid media.

    Attributes:
        type (:obj:`str`): Type of the paid media.
    """

    __slots__ = ("type",)

    PREVIEW: Final[str] = constants.PaidMediaType.PREVIEW
    """:const:`telegram.constants.PaidMediaType.PREVIEW`"""
    PHOTO: Final[str] = constants.PaidMediaType.PHOTO
    """:const:`telegram.constants.PaidMediaType.PHOTO`"""
    VIDEO: Final[str] = constants.PaidMediaType.VIDEO
    """:const:`telegram.constants.PaidMediaType.VIDEO`"""

    def __init__(
        self,
        type: str,  # pylint: disable=redefined-builtin
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.type: str = enum.get_member(constants.PaidMediaType, type, type)

        self._id_attrs = (self.type,)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "PaidMedia":
        """Converts JSON data to the appropriate :class:`PaidMedia` object, i.e. takes
        care of selecting the correct subclass.

        Args:
            data (dict[:obj:`str`, ...]): The JSON data.
            bot (:class:`telegram.Bot`, optional): The bot associated with this object.

        Returns:
            The Telegram object.

        """
        data = cls._parse_data(data)

        _class_mapping: dict[str, type[PaidMedia]] = {
            cls.PREVIEW: PaidMediaPreview,
            cls.PHOTO: PaidMediaPhoto,
            cls.VIDEO: PaidMediaVideo,
        }

        if cls is PaidMedia and data.get("type") in _class_mapping:
            return _class_mapping[data.pop("type")].de_json(data=data, bot=bot)

        if "duration" in data:
            data["duration"] = dtm.timedelta(seconds=s) if (s := data.get("duration")) else None

        return super().de_json(data=data, bot=bot)


class PaidMediaPreview(PaidMedia):
    """The paid media isn't available before the payment.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`width`, :attr:`height`, and :attr:`duration`
    are equal.

    .. versionadded:: 21.4

    .. versionchanged:: v22.2
       As part of the migration to representing time periods using ``datetime.timedelta``,
       equality comparison now considers integer durations and equivalent timedeltas as equal.

    Args:
        type (:obj:`str`): Type of the paid media, always :tg-const:`telegram.PaidMedia.PREVIEW`.
        width (:obj:`int`, optional): Media width as defined by the sender.
        height (:obj:`int`, optional): Media height as defined by the sender.
        duration (:obj:`int` | :class:`datetime.timedelta`, optional): Duration of the media in
            seconds as defined by the sender.

            .. versionchanged:: v22.2
                |time-period-input|

    Attributes:
        type (:obj:`str`): Type of the paid media, always :tg-const:`telegram.PaidMedia.PREVIEW`.
        width (:obj:`int`): Optional. Media width as defined by the sender.
        height (:obj:`int`): Optional. Media height as defined by the sender.
        duration (:obj:`int` | :class:`datetime.timedelta`): Optional. Duration of the media in
            seconds as defined by the sender.

            .. deprecated:: v22.2
                |time-period-int-deprecated|
    """

    __slots__ = ("_duration", "height", "width")

    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        duration: TimePeriod | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=PaidMedia.PREVIEW, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.width: int | None = width
            self.height: int | None = height
            self._duration: dtm.timedelta | None = to_timedelta(duration)

            self._id_attrs = (self.type, self.width, self.height, self._duration)

    @property
    def duration(self) -> int | dtm.timedelta | None:
        return get_timedelta_value(self._duration, attribute="duration")


class PaidMediaPhoto(PaidMedia):
    """
    The paid media is a photo.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`photo` are equal.

    .. versionadded:: 21.4

    Args:
        type (:obj:`str`): Type of the paid media, always :tg-const:`telegram.PaidMedia.PHOTO`.
        photo (Sequence[:class:`telegram.PhotoSize`]): The photo.

    Attributes:
        type (:obj:`str`): Type of the paid media, always :tg-const:`telegram.PaidMedia.PHOTO`.
        photo (tuple[:class:`telegram.PhotoSize`]): The photo.
    """

    __slots__ = ("photo",)

    def __init__(
        self,
        photo: Sequence["PhotoSize"],
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=PaidMedia.PHOTO, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.photo: tuple[PhotoSize, ...] = parse_sequence_arg(photo)

            self._id_attrs = (self.type, self.photo)

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "PaidMediaPhoto":
        data = cls._parse_data(data)

        data["photo"] = de_list_optional(data.get("photo"), PhotoSize, bot)
        return super().de_json(data=data, bot=bot)  # type: ignore[return-value]


class PaidMediaVideo(PaidMedia):
    """
    The paid media is a video.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`video` are equal.

    .. versionadded:: 21.4

    Args:
        type (:obj:`str`): Type of the paid media, always :tg-const:`telegram.PaidMedia.VIDEO`.
        video (:class:`telegram.Video`): The video.

    Attributes:
        type (:obj:`str`): Type of the paid media, always :tg-const:`telegram.PaidMedia.VIDEO`.
        video (:class:`telegram.Video`): The video.
    """

    __slots__ = ("video",)

    def __init__(
        self,
        video: Video,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=PaidMedia.VIDEO, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.video: Video = video

            self._id_attrs = (self.type, self.video)

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "PaidMediaVideo":
        data = cls._parse_data(data)

        data["video"] = de_json_optional(data.get("video"), Video, bot)
        return super().de_json(data=data, bot=bot)  # type: ignore[return-value]


class PaidMediaInfo(TelegramObject):
    """
    Describes the paid media added to a message.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`star_count` and :attr:`paid_media` are equal.

    .. versionadded:: 21.4

    Args:
        star_count (:obj:`int`): The number of Telegram Stars that must be paid to buy access to
            the media.
        paid_media (Sequence[:class:`telegram.PaidMedia`]): Information about the paid media.

    Attributes:
        star_count (:obj:`int`): The number of Telegram Stars that must be paid to buy access to
            the media.
        paid_media (tuple[:class:`telegram.PaidMedia`]): Information about the paid media.
    """

    __slots__ = ("paid_media", "star_count")

    def __init__(
        self,
        star_count: int,
        paid_media: Sequence[PaidMedia],
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.star_count: int = star_count
        self.paid_media: tuple[PaidMedia, ...] = parse_sequence_arg(paid_media)

        self._id_attrs = (self.star_count, self.paid_media)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "PaidMediaInfo":
        data = cls._parse_data(data)

        data["paid_media"] = de_list_optional(data.get("paid_media"), PaidMedia, bot)
        return super().de_json(data=data, bot=bot)


class PaidMediaPurchased(TelegramObject):
    """This object contains information about a paid media purchase.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`from_user` and :attr:`paid_media_payload` are equal.

    Note:
        In Python :keyword:`from` is a reserved word. Use :paramref:`from_user` instead.

    .. versionadded:: 21.6

    Args:
        from_user (:class:`telegram.User`): User who purchased the media.
        paid_media_payload (:obj:`str`): Bot-specified paid media payload.

    Attributes:
        from_user (:class:`telegram.User`): User who purchased the media.
        paid_media_payload (:obj:`str`): Bot-specified paid media payload.
    """

    __slots__ = ("from_user", "paid_media_payload")

    def __init__(
        self,
        from_user: "User",
        paid_media_payload: str,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.from_user: User = from_user
        self.paid_media_payload: str = paid_media_payload

        self._id_attrs = (self.from_user, self.paid_media_payload)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "PaidMediaPurchased":
        data = cls._parse_data(data)

        data["from_user"] = User.de_json(data=data.pop("from"), bot=bot)
        return super().de_json(data=data, bot=bot)
