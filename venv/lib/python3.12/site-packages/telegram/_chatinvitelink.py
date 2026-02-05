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
"""This module contains an object that represents an invite link for a chat."""

import datetime as dtm
from typing import TYPE_CHECKING

from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils.argumentparsing import de_json_optional, to_timedelta
from telegram._utils.datetime import (
    extract_tzinfo_from_defaults,
    from_timestamp,
    get_timedelta_value,
)
from telegram._utils.types import JSONDict, TimePeriod

if TYPE_CHECKING:
    from telegram import Bot


class ChatInviteLink(TelegramObject):
    """This object represents an invite link for a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`invite_link`, :attr:`creator`, :attr:`creates_join_request`,
    :attr:`is_primary` and :attr:`is_revoked` are equal.

    .. versionadded:: 13.4
    .. versionchanged:: 20.0

       * The argument & attribute :attr:`creates_join_request` is now required to comply with the
         Bot API.
       * Comparing objects of this class now also takes :attr:`creates_join_request` into account.

    Args:
        invite_link (:obj:`str`): The invite link.
        creator (:class:`telegram.User`): Creator of the link.
        creates_join_request (:obj:`bool`): :obj:`True`, if users joining the chat via
            the link need to be approved by chat administrators.

            .. versionadded:: 13.8
        is_primary (:obj:`bool`): :obj:`True`, if the link is primary.
        is_revoked (:obj:`bool`): :obj:`True`, if the link is revoked.
        expire_date (:class:`datetime.datetime`, optional): Date when the link will expire or
            has been expired.

            .. versionchanged:: 20.3
                |datetime_localization|
        member_limit (:obj:`int`, optional): Maximum number of users that can be members of the
            chat simultaneously after joining the chat via this invite link;
            :tg-const:`telegram.constants.ChatInviteLinkLimit.MIN_MEMBER_LIMIT`-
            :tg-const:`telegram.constants.ChatInviteLinkLimit.MAX_MEMBER_LIMIT`.
        name (:obj:`str`, optional): Invite link name.
            0-:tg-const:`telegram.constants.ChatInviteLinkLimit.NAME_LENGTH` characters.

            .. versionadded:: 13.8
        pending_join_request_count (:obj:`int`, optional): Number of pending join requests
            created using this link.

            .. versionadded:: 13.8
        subscription_period (:obj:`int` | :class:`datetime.timedelta`, optional): The number of
            seconds the subscription will be active for before the next payment.

            .. versionadded:: 21.5

            .. versionchanged:: v22.2
                |time-period-input|
        subscription_price (:obj:`int`, optional): The amount of Telegram Stars a user must pay
            initially and after each subsequent subscription period to be a member of the chat
            using the link.

            .. versionadded:: 21.5

    Attributes:
        invite_link (:obj:`str`): The invite link. If the link was created by another chat
            administrator, then the second part of the link will be replaced with ``'…'``.
        creator (:class:`telegram.User`): Creator of the link.
        creates_join_request (:obj:`bool`): :obj:`True`, if users joining the chat via
            the link need to be approved by chat administrators.

            .. versionadded:: 13.8
        is_primary (:obj:`bool`): :obj:`True`, if the link is primary.
        is_revoked (:obj:`bool`): :obj:`True`, if the link is revoked.
        expire_date (:class:`datetime.datetime`): Optional. Date when the link will expire or
            has been expired.

            .. versionchanged:: 20.3
                |datetime_localization|
        member_limit (:obj:`int`): Optional. Maximum number of users that can be members
            of the chat simultaneously after joining the chat via this invite link;
            :tg-const:`telegram.constants.ChatInviteLinkLimit.MIN_MEMBER_LIMIT`-
            :tg-const:`telegram.constants.ChatInviteLinkLimit.MAX_MEMBER_LIMIT`.
        name (:obj:`str`): Optional. Invite link name.
            0-:tg-const:`telegram.constants.ChatInviteLinkLimit.NAME_LENGTH` characters.

            .. versionadded:: 13.8
        pending_join_request_count (:obj:`int`): Optional. Number of pending join requests
            created using this link.

            .. versionadded:: 13.8
        subscription_period (:obj:`int` | :class:`datetime.timedelta`): Optional. The number of
            seconds the subscription will be active for before the next payment.

            .. versionadded:: 21.5

            .. deprecated:: v22.2
                |time-period-int-deprecated|
        subscription_price (:obj:`int`): Optional. The amount of Telegram Stars a user must pay
            initially and after each subsequent subscription period to be a member of the chat
            using the link.

            .. versionadded:: 21.5

    """

    __slots__ = (
        "_subscription_period",
        "creates_join_request",
        "creator",
        "expire_date",
        "invite_link",
        "is_primary",
        "is_revoked",
        "member_limit",
        "name",
        "pending_join_request_count",
        "subscription_price",
    )

    def __init__(
        self,
        invite_link: str,
        creator: User,
        creates_join_request: bool,
        is_primary: bool,
        is_revoked: bool,
        expire_date: dtm.datetime | None = None,
        member_limit: int | None = None,
        name: str | None = None,
        pending_join_request_count: int | None = None,
        subscription_period: TimePeriod | None = None,
        subscription_price: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.invite_link: str = invite_link
        self.creator: User = creator
        self.creates_join_request: bool = creates_join_request
        self.is_primary: bool = is_primary
        self.is_revoked: bool = is_revoked

        # Optionals
        self.expire_date: dtm.datetime | None = expire_date
        self.member_limit: int | None = member_limit
        self.name: str | None = name
        self.pending_join_request_count: int | None = (
            int(pending_join_request_count) if pending_join_request_count is not None else None
        )
        self._subscription_period: dtm.timedelta | None = to_timedelta(subscription_period)
        self.subscription_price: int | None = subscription_price

        self._id_attrs = (
            self.invite_link,
            self.creates_join_request,
            self.creator,
            self.is_primary,
            self.is_revoked,
        )

        self._freeze()

    @property
    def subscription_period(self) -> int | dtm.timedelta | None:
        return get_timedelta_value(self._subscription_period, attribute="subscription_period")

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChatInviteLink":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["creator"] = de_json_optional(data.get("creator"), User, bot)
        data["expire_date"] = from_timestamp(data.get("expire_date", None), tzinfo=loc_tzinfo)

        return super().de_json(data=data, bot=bot)
