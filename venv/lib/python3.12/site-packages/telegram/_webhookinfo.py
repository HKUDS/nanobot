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
"""This module contains an object that represents a Telegram WebhookInfo."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import parse_sequence_arg
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class WebhookInfo(TelegramObject):
    """This object represents a Telegram WebhookInfo.

    Contains information about the current status of a webhook.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`url`, :attr:`has_custom_certificate`,
    :attr:`pending_update_count`, :attr:`ip_address`, :attr:`last_error_date`,
    :attr:`last_error_message`, :attr:`max_connections`, :attr:`allowed_updates` and
    :attr:`last_synchronization_error_date` are equal.

    .. versionchanged:: 20.0
       :attr:`last_synchronization_error_date` is considered as well when comparing objects of
       this type in terms of equality.

    Args:
        url (:obj:`str`): Webhook URL, may be empty if webhook is not set up.
        has_custom_certificate (:obj:`bool`): :obj:`True`, if a custom certificate was provided for
            webhook certificate checks.
        pending_update_count (:obj:`int`): Number of updates awaiting delivery.
        ip_address (:obj:`str`, optional): Currently used webhook IP address.
        last_error_date (:class:`datetime.datetime`): Optional. Datetime for the most recent
            error that happened when trying to deliver an update via webhook.

            .. versionchanged:: 20.3
                |datetime_localization|
        last_error_message (:obj:`str`, optional): Error message in human-readable format for the
            most recent error that happened when trying to deliver an update via webhook.
        max_connections (:obj:`int`, optional): Maximum allowed number of simultaneous HTTPS
            connections to the webhook for update delivery.
        allowed_updates (Sequence[:obj:`str`], optional): A sequence of update types the bot is
            subscribed to. Defaults to all update types, except
            :attr:`telegram.Update.chat_member`.

            .. versionchanged:: 20.0
                |sequenceclassargs|

        last_synchronization_error_date (:class:`datetime.datetime`, optional): Datetime of the
            most recent error that happened when trying to synchronize available updates with
            Telegram datacenters.

            .. versionadded:: 20.0

            .. versionchanged:: 20.3
                |datetime_localization|
    Attributes:
        url (:obj:`str`): Webhook URL, may be empty if webhook is not set up.
        has_custom_certificate (:obj:`bool`): :obj:`True`, if a custom certificate was provided for
            webhook certificate checks.
        pending_update_count (:obj:`int`): Number of updates awaiting delivery.
        ip_address (:obj:`str`): Optional. Currently used webhook IP address.
        last_error_date (:class:`datetime.datetime`): Optional. Datetime for the most recent
            error that happened when trying to deliver an update via webhook.

            .. versionchanged:: 20.3
                |datetime_localization|
        last_error_message (:obj:`str`): Optional. Error message in human-readable format for the
            most recent error that happened when trying to deliver an update via webhook.
        max_connections (:obj:`int`): Optional. Maximum allowed number of simultaneous HTTPS
            connections to the webhook for update delivery.
        allowed_updates (tuple[:obj:`str`]): Optional. A tuple of update types the bot is
            subscribed to. Defaults to all update types, except
            :attr:`telegram.Update.chat_member`.

            .. versionchanged:: 20.0

                * |tupleclassattrs|
                * |alwaystuple|
        last_synchronization_error_date (:class:`datetime.datetime`, optional): Datetime of the
            most recent error that happened when trying to synchronize available updates with
            Telegram datacenters.

            .. versionadded:: 20.0

            .. versionchanged:: 20.3
                |datetime_localization|
    """

    __slots__ = (
        "allowed_updates",
        "has_custom_certificate",
        "ip_address",
        "last_error_date",
        "last_error_message",
        "last_synchronization_error_date",
        "max_connections",
        "pending_update_count",
        "url",
    )

    def __init__(
        self,
        url: str,
        has_custom_certificate: bool,
        pending_update_count: int,
        last_error_date: dtm.datetime | None = None,
        last_error_message: str | None = None,
        max_connections: int | None = None,
        allowed_updates: Sequence[str] | None = None,
        ip_address: str | None = None,
        last_synchronization_error_date: dtm.datetime | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.url: str = url
        self.has_custom_certificate: bool = has_custom_certificate
        self.pending_update_count: int = pending_update_count

        # Optional
        self.ip_address: str | None = ip_address
        self.last_error_date: dtm.datetime | None = last_error_date
        self.last_error_message: str | None = last_error_message
        self.max_connections: int | None = max_connections
        self.allowed_updates: tuple[str, ...] = parse_sequence_arg(allowed_updates)
        self.last_synchronization_error_date: dtm.datetime | None = last_synchronization_error_date

        self._id_attrs = (
            self.url,
            self.has_custom_certificate,
            self.pending_update_count,
            self.ip_address,
            self.last_error_date,
            self.last_error_message,
            self.max_connections,
            self.allowed_updates,
            self.last_synchronization_error_date,
        )

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "WebhookInfo":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["last_error_date"] = from_timestamp(data.get("last_error_date"), tzinfo=loc_tzinfo)
        data["last_synchronization_error_date"] = from_timestamp(
            data.get("last_synchronization_error_date"), tzinfo=loc_tzinfo
        )

        return super().de_json(data=data, bot=bot)
