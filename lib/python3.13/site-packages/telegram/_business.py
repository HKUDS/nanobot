#!/usr/bin/env python
# pylint: disable=redefined-builtin
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
# along with this program.  If not, see [http://www.gnu.org/licenses/]
"""This module contains the Telegram Business related classes."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from telegram._chat import Chat
from telegram._files.location import Location
from telegram._files.sticker import Sticker
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils.argumentparsing import (
    de_json_optional,
    de_list_optional,
    parse_sequence_arg,
)
from telegram._utils.datetime import (
    extract_tzinfo_from_defaults,
    from_timestamp,
    get_zone_info,
)
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class BusinessBotRights(TelegramObject):
    """
    This object represents the rights of a business bot.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if all their attributes are equal.

    .. versionadded:: 22.1

    Args:
        can_reply (:obj:`bool`, optional): True, if the bot can send and edit messages in the
            private chats that had incoming messages in the last 24 hours.
        can_read_messages (:obj:`bool`, optional): True, if the bot can mark incoming private
            messages as read.
        can_delete_sent_messages (:obj:`bool`, optional): True, if the bot can delete messages
            sent by the bot.
        can_delete_all_messages (:obj:`bool`, optional): True, if the bot can delete all private
            messages in managed chats.
        can_edit_name (:obj:`bool`, optional): True, if the bot can edit the first and last name
            of the business account.
        can_edit_bio (:obj:`bool`, optional): True, if the bot can edit the bio of the
            business account.
        can_edit_profile_photo (:obj:`bool`, optional): True, if the bot can edit the profile
            photo of the business account.
        can_edit_username (:obj:`bool`, optional): True, if the bot can edit the username of the
            business account.
        can_change_gift_settings (:obj:`bool`, optional): True, if the bot can change the privacy
            settings pertaining to gifts for the business account.
        can_view_gifts_and_stars (:obj:`bool`, optional): True, if the bot can view gifts and the
            amount of Telegram Stars owned by the business account.
        can_convert_gifts_to_stars (:obj:`bool`, optional): True, if the bot can convert regular
            gifts owned by the business account to Telegram Stars.
        can_transfer_and_upgrade_gifts (:obj:`bool`, optional): True, if the bot can transfer and
            upgrade gifts owned by the business account.
        can_transfer_stars (:obj:`bool`, optional): True, if the bot can transfer Telegram Stars
            received by the business account to its own account, or use them to upgrade and
            transfer gifts.
        can_manage_stories (:obj:`bool`, optional): True, if the bot can post, edit and delete
            stories on behalf of the business account.

    Attributes:
        can_reply (:obj:`bool`): Optional. True, if the bot can send and edit messages in the
            private chats that had incoming messages in the last 24 hours.
        can_read_messages (:obj:`bool`): Optional. True, if the bot can mark incoming private
            messages as read.
        can_delete_sent_messages (:obj:`bool`): Optional. True, if the bot can delete messages
            sent by the bot.
        can_delete_all_messages (:obj:`bool`): Optional. True, if the bot can delete all private
            messages in managed chats.
        can_edit_name (:obj:`bool`): Optional. True, if the bot can edit the first and last name
            of the business account.
        can_edit_bio (:obj:`bool`): Optional. True, if the bot can edit the bio of the
            business account.
        can_edit_profile_photo (:obj:`bool`): Optional. True, if the bot can edit the profile
            photo of the business account.
        can_edit_username (:obj:`bool`): Optional. True, if the bot can edit the username of the
            business account.
        can_change_gift_settings (:obj:`bool`): Optional. True, if the bot can change the privacy
            settings pertaining to gifts for the business account.
        can_view_gifts_and_stars (:obj:`bool`): Optional. True, if the bot can view gifts and the
            amount of Telegram Stars owned by the business account.
        can_convert_gifts_to_stars (:obj:`bool`): Optional. True, if the bot can convert regular
            gifts owned by the business account to Telegram Stars.
        can_transfer_and_upgrade_gifts (:obj:`bool`): Optional. True, if the bot can transfer and
            upgrade gifts owned by the business account.
        can_transfer_stars (:obj:`bool`): Optional. True, if the bot can transfer Telegram Stars
            received by the business account to its own account, or use them to upgrade and
            transfer gifts.
        can_manage_stories (:obj:`bool`): Optional. True, if the bot can post, edit and delete
            stories on behalf of the business account.
    """

    __slots__ = (
        "can_change_gift_settings",
        "can_convert_gifts_to_stars",
        "can_delete_all_messages",
        "can_delete_sent_messages",
        "can_edit_bio",
        "can_edit_name",
        "can_edit_profile_photo",
        "can_edit_username",
        "can_manage_stories",
        "can_read_messages",
        "can_reply",
        "can_transfer_and_upgrade_gifts",
        "can_transfer_stars",
        "can_view_gifts_and_stars",
    )

    def __init__(
        self,
        can_reply: bool | None = None,
        can_read_messages: bool | None = None,
        can_delete_sent_messages: bool | None = None,
        can_delete_all_messages: bool | None = None,
        can_edit_name: bool | None = None,
        can_edit_bio: bool | None = None,
        can_edit_profile_photo: bool | None = None,
        can_edit_username: bool | None = None,
        can_change_gift_settings: bool | None = None,
        can_view_gifts_and_stars: bool | None = None,
        can_convert_gifts_to_stars: bool | None = None,
        can_transfer_and_upgrade_gifts: bool | None = None,
        can_transfer_stars: bool | None = None,
        can_manage_stories: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.can_reply: bool | None = can_reply
        self.can_read_messages: bool | None = can_read_messages
        self.can_delete_sent_messages: bool | None = can_delete_sent_messages
        self.can_delete_all_messages: bool | None = can_delete_all_messages
        self.can_edit_name: bool | None = can_edit_name
        self.can_edit_bio: bool | None = can_edit_bio
        self.can_edit_profile_photo: bool | None = can_edit_profile_photo
        self.can_edit_username: bool | None = can_edit_username
        self.can_change_gift_settings: bool | None = can_change_gift_settings
        self.can_view_gifts_and_stars: bool | None = can_view_gifts_and_stars
        self.can_convert_gifts_to_stars: bool | None = can_convert_gifts_to_stars
        self.can_transfer_and_upgrade_gifts: bool | None = can_transfer_and_upgrade_gifts
        self.can_transfer_stars: bool | None = can_transfer_stars
        self.can_manage_stories: bool | None = can_manage_stories

        self._id_attrs = (
            self.can_reply,
            self.can_read_messages,
            self.can_delete_sent_messages,
            self.can_delete_all_messages,
            self.can_edit_name,
            self.can_edit_bio,
            self.can_edit_profile_photo,
            self.can_edit_username,
            self.can_change_gift_settings,
            self.can_view_gifts_and_stars,
            self.can_convert_gifts_to_stars,
            self.can_transfer_and_upgrade_gifts,
            self.can_transfer_stars,
            self.can_manage_stories,
        )

        self._freeze()


class BusinessConnection(TelegramObject):
    """
    Describes the connection of the bot with a business account.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`id`, :attr:`user`, :attr:`user_chat_id`, :attr:`date`,
    :attr:`rights`, and :attr:`is_enabled` are equal.

    .. versionadded:: 21.1
    .. versionchanged:: 22.1
        Equality comparison now considers :attr:`rights` instead of ``can_reply``.

    .. versionremoved:: 22.3
       Removed argument and attribute ``can_reply`` deprecated  by API 9.0.

    Args:
        id (:obj:`str`): Unique identifier of the business connection.
        user (:class:`telegram.User`): Business account user that created the business connection.
        user_chat_id (:obj:`int`): Identifier of a private chat with the user who created the
            business connection.
        date (:obj:`datetime.datetime`): Date the connection was established in Unix time.
        is_enabled (:obj:`bool`): True, if the connection is active.
        rights (:class:`BusinessBotRights`, optional): Rights of the business bot.

            .. versionadded:: 22.1

    Attributes:
        id (:obj:`str`): Unique identifier of the business connection.
        user (:class:`telegram.User`): Business account user that created the business connection.
        user_chat_id (:obj:`int`): Identifier of a private chat with the user who created the
            business connection.
        date (:obj:`datetime.datetime`): Date the connection was established in Unix time.
        is_enabled (:obj:`bool`): True, if the connection is active.
        rights (:class:`BusinessBotRights`): Optional. Rights of the business bot.

            .. versionadded:: 22.1
    """

    __slots__ = (
        "date",
        "id",
        "is_enabled",
        "rights",
        "user",
        "user_chat_id",
    )

    def __init__(
        self,
        id: str,
        user: "User",
        user_chat_id: int,
        date: dtm.datetime,
        is_enabled: bool,
        rights: BusinessBotRights | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.id: str = id
        self.user: User = user
        self.user_chat_id: int = user_chat_id
        self.date: dtm.datetime = date
        self.is_enabled: bool = is_enabled
        self.rights: BusinessBotRights | None = rights

        self._id_attrs = (
            self.id,
            self.user,
            self.user_chat_id,
            self.date,
            self.rights,
            self.is_enabled,
        )

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "BusinessConnection":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["date"] = from_timestamp(data.get("date"), tzinfo=loc_tzinfo)
        data["user"] = de_json_optional(data.get("user"), User, bot)
        data["rights"] = de_json_optional(data.get("rights"), BusinessBotRights, bot)

        return super().de_json(data=data, bot=bot)


class BusinessMessagesDeleted(TelegramObject):
    """
    This object is received when messages are deleted from a connected business account.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`business_connection_id`, :attr:`message_ids`, and
    :attr:`chat` are equal.

    .. versionadded:: 21.1

    Args:
        business_connection_id (:obj:`str`): Unique identifier of the business connection.
        chat (:class:`telegram.Chat`): Information about a chat in the business account. The bot
            may not have access to the chat or the corresponding user.
        message_ids (Sequence[:obj:`int`]): A list of identifiers of the deleted messages in the
            chat of the business account.

    Attributes:
        business_connection_id (:obj:`str`): Unique identifier of the business connection.
        chat (:class:`telegram.Chat`): Information about a chat in the business account. The bot
            may not have access to the chat or the corresponding user.
        message_ids (tuple[:obj:`int`]): A list of identifiers of the deleted messages in the
            chat of the business account.
    """

    __slots__ = (
        "business_connection_id",
        "chat",
        "message_ids",
    )

    def __init__(
        self,
        business_connection_id: str,
        chat: Chat,
        message_ids: Sequence[int],
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.business_connection_id: str = business_connection_id
        self.chat: Chat = chat
        self.message_ids: tuple[int, ...] = parse_sequence_arg(message_ids)

        self._id_attrs = (
            self.business_connection_id,
            self.chat,
            self.message_ids,
        )

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "BusinessMessagesDeleted":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["chat"] = de_json_optional(data.get("chat"), Chat, bot)

        return super().de_json(data=data, bot=bot)


class BusinessIntro(TelegramObject):
    """
    This object contains information about the start page settings of a Telegram Business account.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if their
    :attr:`title`, :attr:`message` and :attr:`sticker` are equal.

    .. versionadded:: 21.1

    Args:
        title (:obj:`str`, optional): Title text of the business intro.
        message (:obj:`str`, optional): Message text of the business intro.
        sticker (:class:`telegram.Sticker`, optional): Sticker of the business intro.

    Attributes:
        title (:obj:`str`): Optional. Title text of the business intro.
        message (:obj:`str`): Optional. Message text of the business intro.
        sticker (:class:`telegram.Sticker`): Optional. Sticker of the business intro.
    """

    __slots__ = (
        "message",
        "sticker",
        "title",
    )

    def __init__(
        self,
        title: str | None = None,
        message: str | None = None,
        sticker: Sticker | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.title: str | None = title
        self.message: str | None = message
        self.sticker: Sticker | None = sticker

        self._id_attrs = (self.title, self.message, self.sticker)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "BusinessIntro":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["sticker"] = de_json_optional(data.get("sticker"), Sticker, bot)

        return super().de_json(data=data, bot=bot)


class BusinessLocation(TelegramObject):
    """
    This object contains information about the location of a Telegram Business account.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if their
    :attr:`address` is equal.

    .. versionadded:: 21.1

    Args:
        address (:obj:`str`): Address of the business.
        location (:class:`telegram.Location`, optional): Location of the business.

    Attributes:
        address (:obj:`str`): Address of the business.
        location (:class:`telegram.Location`): Optional. Location of the business.
    """

    __slots__ = (
        "address",
        "location",
    )

    def __init__(
        self,
        address: str,
        location: "Location | None" = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.address: str = address
        self.location: Location | None = location

        self._id_attrs = (self.address,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "BusinessLocation":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["location"] = de_json_optional(data.get("location"), Location, bot)

        return super().de_json(data=data, bot=bot)


class BusinessOpeningHoursInterval(TelegramObject):
    """
    This object describes an interval of time during which a business is open.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if their
    :attr:`opening_minute` and :attr:`closing_minute` are equal.

    .. versionadded:: 21.1

    Examples:
        A day has (24 * 60 =) 1440 minutes, a week has (7 * 1440 =) 10080 minutes.
        Starting the minute's sequence from Monday, example values of
        :attr:`opening_minute`, :attr:`closing_minute` will map to the following day times:

        * Monday - 8am to 8:30pm:
            - ``opening_minute = 480`` :guilabel:`8 * 60`
            - ``closing_minute = 1230`` :guilabel:`20 * 60 + 30`
        * Tuesday - 24 hours:
            - ``opening_minute = 1440`` :guilabel:`24 * 60`
            - ``closing_minute = 2879`` :guilabel:`2 * 24 * 60 - 1`
        * Sunday - 12am - 11:58pm:
            - ``opening_minute = 8640`` :guilabel:`6 * 24 * 60`
            - ``closing_minute = 10078`` :guilabel:`7 * 24 * 60 - 2`

    Args:
        opening_minute (:obj:`int`): The minute's sequence number in a week, starting on Monday,
            marking the start of the time interval during which the business is open;
            0 - 7 * 24 * 60.
        closing_minute (:obj:`int`): The minute's
            sequence number in a week, starting on Monday, marking the end of the time interval
            during which the business is open; 0 - 8 * 24 * 60

    Attributes:
        opening_minute (:obj:`int`): The minute's sequence number in a week, starting on Monday,
            marking the start of the time interval during which the business is open;
            0 - 7 * 24 * 60.
        closing_minute (:obj:`int`): The minute's
            sequence number in a week, starting on Monday, marking the end of the time interval
            during which the business is open; 0 - 8 * 24 * 60
    """

    __slots__ = ("_closing_time", "_opening_time", "closing_minute", "opening_minute")

    def __init__(
        self,
        opening_minute: int,
        closing_minute: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.opening_minute: int = opening_minute
        self.closing_minute: int = closing_minute

        self._opening_time: tuple[int, int, int] | None = None
        self._closing_time: tuple[int, int, int] | None = None

        self._id_attrs = (self.opening_minute, self.closing_minute)

        self._freeze()

    def _parse_minute(self, minute: int) -> tuple[int, int, int]:
        return (minute // 1440, minute % 1440 // 60, minute % 1440 % 60)

    @property
    def opening_time(self) -> tuple[int, int, int]:
        """Convenience attribute. A :obj:`tuple` parsed from :attr:`opening_minute`. It contains
        the `weekday`, `hour` and `minute` in the same ranges as :attr:`datetime.datetime.weekday`,
        :attr:`datetime.datetime.hour` and :attr:`datetime.datetime.minute`

        Returns:
            tuple[:obj:`int`, :obj:`int`, :obj:`int`]:
        """
        if self._opening_time is None:
            self._opening_time = self._parse_minute(self.opening_minute)
        return self._opening_time

    @property
    def closing_time(self) -> tuple[int, int, int]:
        """Convenience attribute. A :obj:`tuple` parsed from :attr:`closing_minute`. It contains
        the `weekday`, `hour` and `minute` in the same ranges as :attr:`datetime.datetime.weekday`,
        :attr:`datetime.datetime.hour` and :attr:`datetime.datetime.minute`

        Returns:
            tuple[:obj:`int`, :obj:`int`, :obj:`int`]:
        """
        if self._closing_time is None:
            self._closing_time = self._parse_minute(self.closing_minute)
        return self._closing_time


class BusinessOpeningHours(TelegramObject):
    """
    This object describes the opening hours of a business.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if their
    :attr:`time_zone_name` and :attr:`opening_hours` are equal.

    .. versionadded:: 21.1

    Args:
        time_zone_name (:obj:`str`): Unique name of the time zone for which the opening
            hours are defined.
        opening_hours (Sequence[:class:`telegram.BusinessOpeningHoursInterval`]): List of
            time intervals describing business opening hours.

    Attributes:
        time_zone_name (:obj:`str`): Unique name of the time zone for which the opening
            hours are defined.
        opening_hours (Sequence[:class:`telegram.BusinessOpeningHoursInterval`]): List of
            time intervals describing business opening hours.
    """

    __slots__ = ("_cached_zone_info", "opening_hours", "time_zone_name")

    def __init__(
        self,
        time_zone_name: str,
        opening_hours: Sequence[BusinessOpeningHoursInterval],
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.time_zone_name: str = time_zone_name
        self.opening_hours: Sequence[BusinessOpeningHoursInterval] = parse_sequence_arg(
            opening_hours
        )

        self._cached_zone_info: ZoneInfo | None = None

        self._id_attrs = (self.time_zone_name, self.opening_hours)

        self._freeze()

    @property
    def _zone_info(self) -> ZoneInfo:
        if self._cached_zone_info is None:
            self._cached_zone_info = get_zone_info(self.time_zone_name)
        return self._cached_zone_info

    def get_opening_hours_for_day(
        self, date: dtm.date, time_zone: dtm.tzinfo | str | None = None
    ) -> tuple[tuple[dtm.datetime, dtm.datetime], ...]:
        """Returns the opening hours intervals for a specific day as datetime objects.

        .. versionadded:: 22.5

        Args:
            date (:obj:`datetime.date`): The date to get opening hours for.
            time_zone (:obj:`datetime.tzinfo` | :obj:`str`, optional): Timezone to use for the
                returned datetime objects. If not specified, then :attr:`time_zone_name` be used.

        Returns:
            tuple[tuple[:obj:`datetime.datetime`, :obj:`datetime.datetime`], ...]:
            A tuple of datetime pairs representing opening and closing times for the specified day.
            Each pair consists of ``(opening_time, closing_time)``.
            Returns an empty tuple if there are no opening hours for the given day.
        """

        week_day = date.weekday()
        res = []
        if isinstance(time_zone, str):
            tz_target: dtm.tzinfo = get_zone_info(time_zone)
        elif time_zone is None:
            tz_target = self._zone_info
        else:
            tz_target = time_zone

        for interval in self.opening_hours:
            int_open = interval.opening_time
            int_close = interval.closing_time

            if int_open[0] != week_day:
                continue

            # To get the correct localization, we first need to create the dtm object in
            # self.time_zone_name, then convert it to the target timezone. We could check if
            # self._zone_info == tz_target and skip the conversion, but it's not worth the added
            # complexity.
            result_int_open = dtm.datetime(
                year=date.year,
                month=date.month,
                day=date.day,
                hour=int_open[1],
                minute=int_open[2],
                tzinfo=self._zone_info,
            ).astimezone(tz_target)

            result_int_close = dtm.datetime(
                year=date.year,
                month=date.month,
                day=date.day,
                hour=int_close[1],
                minute=int_close[2],
                tzinfo=self._zone_info,
            ).astimezone(tz_target)

            res.append((result_int_open, result_int_close))

        # The sorting is currently an implementation detail
        return tuple(sorted(res, key=lambda x: x[0]))

    def is_open(self, datetime: dtm.datetime) -> bool:
        """Check if the business is open at the specified datetime.

        .. versionadded:: 22.5

        Args:
            datetime (:obj:`datetime.datetime`): The datetime to check.
                If the object is timezone-naive, it is assumed to be in the
                timezone specified by :attr:`time_zone_name`.

        Returns:
            :obj:`bool`: True if the business is open at the specified time, False otherwise.
        """

        datetime_in_native_tz = (
            datetime.replace(tzinfo=self._zone_info) if datetime.tzinfo is None else datetime
        ).astimezone(self._zone_info)
        minute_of_week = (
            datetime_in_native_tz.weekday() * 1440
            + datetime_in_native_tz.hour * 60
            + datetime_in_native_tz.minute
        )

        for interval in self.opening_hours:
            if interval.opening_minute <= minute_of_week < interval.closing_minute:
                return True

        return False

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "BusinessOpeningHours":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["opening_hours"] = de_list_optional(
            data.get("opening_hours"), BusinessOpeningHoursInterval, bot
        )

        return super().de_json(data=data, bot=bot)
