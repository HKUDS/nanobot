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
# pylint: disable=redefined-builtin
"""This module contains the classes for Telegram Stars Revenue Withdrawals."""

import datetime as dtm
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class RevenueWithdrawalState(TelegramObject):
    """This object describes the state of a revenue withdrawal operation. Currently, it can be one
    of:

    * :class:`telegram.RevenueWithdrawalStatePending`
    * :class:`telegram.RevenueWithdrawalStateSucceeded`
    * :class:`telegram.RevenueWithdrawalStateFailed`

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is equal.

    .. versionadded:: 21.4

    Args:
        type (:obj:`str`): The type of the state.

    Attributes:
        type (:obj:`str`): The type of the state.
    """

    __slots__ = ("type",)

    PENDING: Final[str] = constants.RevenueWithdrawalStateType.PENDING
    """:const:`telegram.constants.RevenueWithdrawalStateType.PENDING`"""
    SUCCEEDED: Final[str] = constants.RevenueWithdrawalStateType.SUCCEEDED
    """:const:`telegram.constants.RevenueWithdrawalStateType.SUCCEEDED`"""
    FAILED: Final[str] = constants.RevenueWithdrawalStateType.FAILED
    """:const:`telegram.constants.RevenueWithdrawalStateType.FAILED`"""

    def __init__(self, type: str, *, api_kwargs: JSONDict | None = None) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.type: str = enum.get_member(constants.RevenueWithdrawalStateType, type, type)

        self._id_attrs = (self.type,)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "RevenueWithdrawalState":
        """Converts JSON data to the appropriate :class:`RevenueWithdrawalState` object, i.e. takes
        care of selecting the correct subclass.

        Args:
            data (dict[:obj:`str`, ...]): The JSON data.
            bot (:class:`telegram.Bot`): The bot associated with this object.

        Returns:
            The Telegram object.

        """
        data = cls._parse_data(data)

        _class_mapping: dict[str, type[RevenueWithdrawalState]] = {
            cls.PENDING: RevenueWithdrawalStatePending,
            cls.SUCCEEDED: RevenueWithdrawalStateSucceeded,
            cls.FAILED: RevenueWithdrawalStateFailed,
        }

        if cls is RevenueWithdrawalState and data.get("type") in _class_mapping:
            return _class_mapping[data.pop("type")].de_json(data=data, bot=bot)

        return super().de_json(data=data, bot=bot)


class RevenueWithdrawalStatePending(RevenueWithdrawalState):
    """The withdrawal is in progress.

    .. versionadded:: 21.4

    Attributes:
        type (:obj:`str`): The type of the state, always
            :tg-const:`telegram.RevenueWithdrawalState.PENDING`.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None) -> None:
        super().__init__(type=RevenueWithdrawalState.PENDING, api_kwargs=api_kwargs)
        self._freeze()


class RevenueWithdrawalStateSucceeded(RevenueWithdrawalState):
    """The withdrawal succeeded.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`date` are equal.

    .. versionadded:: 21.4

    Args:
        date (:obj:`datetime.datetime`): Date the withdrawal was completed as a datetime object.
        url (:obj:`str`): An HTTPS URL that can be used to see transaction details.

    Attributes:
        type (:obj:`str`): The type of the state, always
            :tg-const:`telegram.RevenueWithdrawalState.SUCCEEDED`.
        date (:obj:`datetime.datetime`): Date the withdrawal was completed as a datetime object.
        url (:obj:`str`): An HTTPS URL that can be used to see transaction details.
    """

    __slots__ = ("date", "url")

    def __init__(
        self,
        date: dtm.datetime,
        url: str,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=RevenueWithdrawalState.SUCCEEDED, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.date: dtm.datetime = date
            self.url: str = url
            self._id_attrs = (
                self.type,
                self.date,
            )

    @classmethod
    def de_json(
        cls, data: JSONDict, bot: "Bot | None" = None
    ) -> "RevenueWithdrawalStateSucceeded":
        """See :meth:`telegram.RevenueWithdrawalState.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)
        data["date"] = from_timestamp(data.get("date", None), tzinfo=loc_tzinfo)

        return super().de_json(data=data, bot=bot)  # type: ignore[return-value]


class RevenueWithdrawalStateFailed(RevenueWithdrawalState):
    """The withdrawal failed and the transaction was refunded.

    .. versionadded:: 21.4

    Attributes:
        type (:obj:`str`): The type of the state, always
            :tg-const:`telegram.RevenueWithdrawalState.FAILED`.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None) -> None:
        super().__init__(type=RevenueWithdrawalState.FAILED, api_kwargs=api_kwargs)
        self._freeze()
