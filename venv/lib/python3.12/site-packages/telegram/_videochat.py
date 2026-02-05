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
"""This module contains objects related to Telegram video chats."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils.argumentparsing import parse_sequence_arg, to_timedelta
from telegram._utils.datetime import (
    extract_tzinfo_from_defaults,
    from_timestamp,
    get_timedelta_value,
)
from telegram._utils.types import JSONDict, TimePeriod

if TYPE_CHECKING:
    from telegram import Bot


class VideoChatStarted(TelegramObject):
    """
    This object represents a service message about a video
    chat started in the chat. Currently holds no information.

    .. versionadded:: 13.4
    .. versionchanged:: 20.0
        This class was renamed from ``VoiceChatStarted`` in accordance to Bot API 6.0.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None) -> None:
        super().__init__(api_kwargs=api_kwargs)

        self._freeze()


class VideoChatEnded(TelegramObject):
    """
    This object represents a service message about a
    video chat ended in the chat.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if their
    :attr:`duration` are equal.

    .. versionadded:: 13.4
    .. versionchanged:: 20.0
        This class was renamed from ``VoiceChatEnded`` in accordance to Bot API 6.0.

    .. versionchanged:: v22.2
       As part of the migration to representing time periods using ``datetime.timedelta``,
       equality comparison now considers integer durations and equivalent timedeltas as equal.

    Args:
        duration (:obj:`int` | :class:`datetime.timedelta`): Voice chat duration
            in seconds.

            .. versionchanged:: v22.2
                |time-period-input|

    Attributes:
        duration (:obj:`int` | :class:`datetime.timedelta`): Voice chat duration in seconds.

            .. deprecated:: v22.2
                |time-period-int-deprecated|

    """

    __slots__ = ("_duration",)

    def __init__(
        self,
        duration: TimePeriod,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self._duration: dtm.timedelta = to_timedelta(duration)
        self._id_attrs = (self._duration,)

        self._freeze()

    @property
    def duration(self) -> int | dtm.timedelta:
        return get_timedelta_value(  # type: ignore[return-value]
            self._duration, attribute="duration"
        )


class VideoChatParticipantsInvited(TelegramObject):
    """
    This object represents a service message about new members invited to a video chat.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if their :attr:`users` are equal.

    .. versionadded:: 13.4
    .. versionchanged:: 20.0
        This class was renamed from ``VoiceChatParticipantsInvited`` in accordance to Bot API 6.0.

    Args:
        users (Sequence[:class:`telegram.User`]): New members that were invited to the video chat.

            .. versionchanged:: 20.0
                |sequenceclassargs|

    Attributes:
        users (tuple[:class:`telegram.User`]): New members that were invited to the video chat.

            .. versionchanged:: 20.0
                |tupleclassattrs|

    """

    __slots__ = ("users",)

    def __init__(
        self,
        users: Sequence[User],
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.users: tuple[User, ...] = parse_sequence_arg(users)
        self._id_attrs = (self.users,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "VideoChatParticipantsInvited":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["users"] = User.de_list(data.get("users", []), bot)
        return super().de_json(data=data, bot=bot)


class VideoChatScheduled(TelegramObject):
    """This object represents a service message about a video chat scheduled in the chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`start_date` are equal.

    .. versionchanged:: 20.0
        This class was renamed from ``VoiceChatScheduled`` in accordance to Bot API 6.0.

    Args:
        start_date (:obj:`datetime.datetime`): Point in time (Unix timestamp) when the video
            chat is supposed to be started by a chat administrator

            .. versionchanged:: 20.3
                |datetime_localization|
    Attributes:
        start_date (:obj:`datetime.datetime`): Point in time (Unix timestamp) when the video
            chat is supposed to be started by a chat administrator

            .. versionchanged:: 20.3
                |datetime_localization|

    """

    __slots__ = ("start_date",)

    def __init__(
        self,
        start_date: dtm.datetime,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.start_date: dtm.datetime = start_date

        self._id_attrs = (self.start_date,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "VideoChatScheduled":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["start_date"] = from_timestamp(data.get("start_date"), tzinfo=loc_tzinfo)

        return super().de_json(data=data, bot=bot)
