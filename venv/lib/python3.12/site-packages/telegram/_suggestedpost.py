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
"""This module contains objects related to Telegram suggested posts."""

import datetime as dtm
from typing import TYPE_CHECKING, Final, Optional

from telegram import constants
from telegram._message import Message
from telegram._payment.stars.staramount import StarAmount
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class SuggestedPostPrice(TelegramObject):
    """
    Desribes the price of a suggested post.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`currency` and :attr:`amount` are equal.

    .. versionadded:: 22.4

    Args:
        currency (:obj:`str`):
            Currency in which the post will be paid. Currently, must be one of ``“XTR”`` for
            Telegram Stars or ``“TON”`` for toncoins.
        amount (:obj:`int`):
            The amount of the currency that will be paid for the post in the smallest units of the
            currency, i.e. Telegram Stars or nanotoncoins. Currently, price in Telegram Stars must
            be between :tg-const:`telegram.constants.SuggestedPost.MIN_PRICE_STARS`
            and :tg-const:`telegram.constants.SuggestedPost.MAX_PRICE_STARS`, and price in
            nanotoncoins must be between
            :tg-const:`telegram.constants.SuggestedPost.MIN_PRICE_NANOTONCOINS`
            and :tg-const:`telegram.constants.SuggestedPost.MAX_PRICE_NANOTONCOINS`.

    Attributes:
        currency (:obj:`str`):
            Currency in which the post will be paid. Currently, must be one of ``“XTR”`` for
            Telegram Stars or ``“TON”`` for toncoins.
        amount (:obj:`int`):
            The amount of the currency that will be paid for the post in the smallest units of the
            currency, i.e. Telegram Stars or nanotoncoins. Currently, price in Telegram Stars must
            be between :tg-const:`telegram.constants.SuggestedPost.MIN_PRICE_STARS`
            and :tg-const:`telegram.constants.SuggestedPost.MAX_PRICE_STARS`, and price in
            nanotoncoins must be between
            :tg-const:`telegram.constants.SuggestedPost.MIN_PRICE_NANOTONCOINS`
            and :tg-const:`telegram.constants.SuggestedPost.MAX_PRICE_NANOTONCOINS`.
    """

    __slots__ = ("amount", "currency")

    def __init__(
        self,
        currency: str,
        amount: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.currency: str = currency
        self.amount: int = amount

        self._id_attrs = (self.currency, self.amount)

        self._freeze()


class SuggestedPostParameters(TelegramObject):
    """
    Contains parameters of a post that is being suggested by the bot.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`price` and :attr:`send_date` are equal.

    .. versionadded:: 22.4

    Args:
        price (:class:`telegram.SuggestedPostPrice`, optional):
            Proposed price for the post. If the field is omitted, then the post is unpaid.
        send_date (:class:`datetime.datetime`, optional):
            Proposed send date of the post. If specified, then the date
            must be between :tg-const:`telegram.constants.SuggestedPost.MIN_SEND_DATE`
            second and :tg-const:`telegram.constants.SuggestedPost.MAX_SEND_DATE` seconds (30 days)
            in the future. If the field is omitted, then the post can be published at any time
            within :tg-const:`telegram.constants.SuggestedPost.MAX_SEND_DATE` seconds (30 days) at
            the sole discretion of the user who approves it.
            |datetime_localization|

    Attributes:
        price (:class:`telegram.SuggestedPostPrice`):
            Optional. Proposed price for the post. If the field is omitted, then the post
            is unpaid.
        send_date (:class:`datetime.datetime`):
            Optional. Proposed send date of the post. If specified, then the date
            must be between :tg-const:`telegram.constants.SuggestedPost.MIN_SEND_DATE`
            second and :tg-const:`telegram.constants.SuggestedPost.MAX_SEND_DATE` seconds (30 days)
            in the future. If the field is omitted, then the post can be published at any time
            within :tg-const:`telegram.constants.SuggestedPost.MAX_SEND_DATE` seconds (30 days) at
            the sole discretion of the user who approves it.
            |datetime_localization|

    """

    __slots__ = ("price", "send_date")

    def __init__(
        self,
        price: SuggestedPostPrice | None = None,
        send_date: dtm.datetime | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.price: SuggestedPostPrice | None = price
        self.send_date: dtm.datetime | None = send_date

        self._id_attrs = (self.price, self.send_date)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "SuggestedPostParameters":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["price"] = de_json_optional(data.get("price"), SuggestedPostPrice, bot)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["send_date"] = from_timestamp(data.get("send_date"), tzinfo=loc_tzinfo)

        return super().de_json(data=data, bot=bot)


class SuggestedPostInfo(TelegramObject):
    """
    Contains information about a suggested post.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`state` and :attr:`price` are equal.

    .. versionadded:: 22.4

    Args:
        state (:obj:`str`):
            State of the suggested post. Currently, it can be one of
            :tg-const:`~telegram.constants.SuggestedPostInfoState.PENDING`,
            :tg-const:`~telegram.constants.SuggestedPostInfoState.APPROVED`,
            :tg-const:`~telegram.constants.SuggestedPostInfoState.DECLINED`.
        price (:obj:`SuggestedPostPrice`, optional):
            Proposed price of the post. If the field is omitted, then the post is unpaid.
        send_date (:class:`datetime.datetime`, optional):
            Proposed send date of the post. If the field is omitted, then the post can be published
            at any time within 30 days at the sole discretion of the user or administrator who
            approves it.
            |datetime_localization|

    Attributes:
        state (:obj:`str`):
            State of the suggested post. Currently, it can be one of
            :tg-const:`~telegram.constants.SuggestedPostInfoState.PENDING`,
            :tg-const:`~telegram.constants.SuggestedPostInfoState.APPROVED`,
            :tg-const:`~telegram.constants.SuggestedPostInfoState.DECLINED`.
        price (:obj:`SuggestedPostPrice`):
            Optional. Proposed price of the post. If the field is omitted, then the post is unpaid.
        send_date (:class:`datetime.datetime`):
            Optional. Proposed send date of the post. If the field is omitted, then the post can be
            published at any time within 30 days at the sole discretion of the user or
            administrator who approves it.
            |datetime_localization|

    """

    __slots__ = ("price", "send_date", "state")

    PENDING: Final[str] = constants.SuggestedPostInfoState.PENDING
    """:const:`telegram.constants.SuggestedPostInfoState.PENDING`"""
    APPROVED: Final[str] = constants.SuggestedPostInfoState.APPROVED
    """:const:`telegram.constants.SuggestedPostInfoState.APPROVED`"""
    DECLINED: Final[str] = constants.SuggestedPostInfoState.DECLINED
    """:const:`telegram.constants.SuggestedPostInfoState.DECLINED`"""

    def __init__(
        self,
        state: str,
        price: SuggestedPostPrice | None = None,
        send_date: dtm.datetime | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.state: str = enum.get_member(constants.SuggestedPostInfoState, state, state)
        # Optionals
        self.price: SuggestedPostPrice | None = price
        self.send_date: dtm.datetime | None = send_date

        self._id_attrs = (self.state, self.price)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "SuggestedPostInfo":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["price"] = de_json_optional(data.get("price"), SuggestedPostPrice, bot)
        data["send_date"] = from_timestamp(data.get("send_date"), tzinfo=loc_tzinfo)

        return super().de_json(data=data, bot=bot)


class SuggestedPostDeclined(TelegramObject):
    """
    Describes a service message about the rejection of a suggested post.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`suggested_post_message` and :attr:`comment` are equal.

    .. versionadded:: 22.4

    Args:
        suggested_post_message (:class:`telegram.Message`, optional):
            Message containing the suggested post. Note that the :class:`~telegram.Message` object
            in this field will not contain the :attr:`~telegram.Message.reply_to_message` field
            even if it itself is a reply.
        comment (:obj:`str`, optional):
            Comment with which the post was declined.

    Attributes:
        suggested_post_message (:class:`telegram.Message`):
            Optional. Message containing the suggested post. Note that the
            :class:`~telegram.Message` object in this field will not contain
            the :attr:`~telegram.Message.reply_to_message` field even if it itself is a reply.
        comment (:obj:`str`):
            Optional. Comment with which the post was declined.

    """

    __slots__ = ("comment", "suggested_post_message")

    def __init__(
        self,
        suggested_post_message: Message | None = None,
        comment: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.suggested_post_message: Message | None = suggested_post_message
        self.comment: str | None = comment

        self._id_attrs = (self.suggested_post_message, self.comment)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "SuggestedPostDeclined":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["suggested_post_message"] = de_json_optional(
            data.get("suggested_post_message"), Message, bot
        )

        return super().de_json(data=data, bot=bot)


class SuggestedPostPaid(TelegramObject):
    """
    Describes a service message about a successful payment for a suggested post.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if all of their attributes are equal.

    .. versionadded:: 22.4

    Args:
        suggested_post_message (:class:`telegram.Message`, optional):
            Message containing the suggested post. Note that the :class:`~telegram.Message` object
            in this field will not contain the :attr:`~telegram.Message.reply_to_message` field
            even if it itself is a reply.
        currency (:obj:`str`):
            Currency in which the payment was made. Currently, one of ``“XTR”`` for Telegram Stars
            or ``“TON”`` for toncoins.
        amount (:obj:`int`, optional):
            The amount of the currency that was received by the channel in nanotoncoins; for
            payments in toncoins only.
        star_amount (:class:`telegram.StarAmount`, optional):
            The amount of Telegram Stars that was received by the channel; for payments in Telegram
            Stars only.


    Attributes:
        suggested_post_message (:class:`telegram.Message`):
            Optional. Message containing the suggested post. Note that the
            :class:`~telegram.Message` object in this field will not contain
            the :attr:`~telegram.Message.reply_to_message` field even if it itself is a reply.
        currency (:obj:`str`):
            Currency in which the payment was made. Currently, one of ``“XTR”`` for Telegram Stars
            or ``“TON”`` for toncoins.
        amount (:obj:`int`):
            Optional. The amount of the currency that was received by the channel in nanotoncoins;
            for payments in toncoins only.
        star_amount (:class:`telegram.StarAmount`):
            Optional. The amount of Telegram Stars that was received by the channel; for payments
            in Telegram Stars only.

    """

    __slots__ = ("amount", "currency", "star_amount", "suggested_post_message")

    def __init__(
        self,
        currency: str,
        suggested_post_message: Message | None = None,
        amount: int | None = None,
        star_amount: StarAmount | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.currency: str = currency
        # Optionals
        self.suggested_post_message: Message | None = suggested_post_message
        self.amount: int | None = amount
        self.star_amount: StarAmount | None = star_amount

        self._id_attrs = (
            self.currency,
            self.suggested_post_message,
            self.amount,
            self.star_amount,
        )

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "SuggestedPostPaid":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["suggested_post_message"] = de_json_optional(
            data.get("suggested_post_message"), Message, bot
        )
        data["star_amount"] = de_json_optional(data.get("star_amount"), StarAmount, bot)

        return super().de_json(data=data, bot=bot)


class SuggestedPostRefunded(TelegramObject):
    """
    Describes a service message about a payment refund for a suggested post.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`suggested_post_message` and :attr:`reason` are equal.

    .. versionadded:: 22.4

    Args:
        suggested_post_message (:class:`telegram.Message`, optional):
            Message containing the suggested post. Note that the :class:`~telegram.Message` object
            in this field will not contain the :attr:`~telegram.Message.reply_to_message` field
            even if it itself is a reply.
        reason (:obj:`str`):
            Reason for the refund. Currently,
            one of :tg-const:`telegram.constants.SuggestedPostRefunded.POST_DELETED` if the post
            was deleted within 24 hours of being posted or removed from scheduled messages without
            being posted, or :tg-const:`telegram.constants.SuggestedPostRefunded.PAYMENT_REFUNDED`
            if the payer refunded their payment.

    Attributes:
        suggested_post_message (:class:`telegram.Message`):
            Optional. Message containing the suggested post. Note that the
            :class:`~telegram.Message` object in this field will not contain
            the :attr:`~telegram.Message.reply_to_message` field even if it itself is a reply.
        reason (:obj:`str`):
            Reason for the refund. Currently,
            one of :tg-const:`telegram.constants.SuggestedPostRefunded.POST_DELETED` if the post
            was deleted within 24 hours of being posted or removed from scheduled messages without
            being posted, or :tg-const:`telegram.constants.SuggestedPostRefunded.PAYMENT_REFUNDED`
            if the payer refunded their payment.

    """

    __slots__ = ("reason", "suggested_post_message")

    def __init__(
        self,
        reason: str,
        suggested_post_message: Message | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.reason: str = reason
        # Optionals
        self.suggested_post_message: Message | None = suggested_post_message

        self._id_attrs = (self.reason, self.suggested_post_message)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "SuggestedPostRefunded":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["suggested_post_message"] = de_json_optional(
            data.get("suggested_post_message"), Message, bot
        )

        return super().de_json(data=data, bot=bot)


class SuggestedPostApproved(TelegramObject):
    """
    Describes a service message about the approval of a suggested post.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if all of their attributes are equal.

    .. versionadded:: 22.4

    Args:
        suggested_post_message (:class:`telegram.Message`, optional):
            Message containing the suggested post. Note that the :class:`~telegram.Message` object
            in this field will not contain the :attr:`~telegram.Message.reply_to_message` field
            even if it itself is a reply.
        price (:obj:`SuggestedPostPrice`, optional):
            Amount paid for the post.
        send_date (:class:`datetime.datetime`):
            Date when the post will be published.
            |datetime_localization|

    Attributes:
        suggested_post_message (:class:`telegram.Message`):
            Optional. Message containing the suggested post. Note that the
            :class:`~telegram.Message` object in this field will not contain
            the :attr:`~telegram.Message.reply_to_message` field even if it itself is a reply.
        price (:obj:`SuggestedPostPrice`):
            Optional. Amount paid for the post.
        send_date (:class:`datetime.datetime`):
            Date when the post will be published.
            |datetime_localization|

    """

    __slots__ = ("price", "send_date", "suggested_post_message")

    def __init__(
        self,
        send_date: dtm.datetime,
        suggested_post_message: Message | None = None,
        price: SuggestedPostPrice | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.send_date: dtm.datetime = send_date
        # Optionals
        self.suggested_post_message: Message | None = suggested_post_message
        self.price: SuggestedPostPrice | None = price

        self._id_attrs = (self.send_date, self.suggested_post_message, self.price)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "SuggestedPostApproved":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["send_date"] = from_timestamp(data.get("send_date"), tzinfo=loc_tzinfo)
        data["price"] = de_json_optional(data.get("price"), SuggestedPostPrice, bot)
        data["suggested_post_message"] = de_json_optional(
            data.get("suggested_post_message"), Message, bot
        )

        return super().de_json(data=data, bot=bot)


class SuggestedPostApprovalFailed(TelegramObject):
    """
    Describes a service message about the failed approval of a suggested post. Currently, only
    caused by insufficient user funds at the time of approval.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`suggested_post_message` and :attr:`price` are equal.

    .. versionadded:: 22.4

    Args:
        suggested_post_message (:class:`telegram.Message`, optional):
            Message containing the suggested post. Note that the :class:`~telegram.Message` object
            in this field will not contain the :attr:`~telegram.Message.reply_to_message` field
            even if it itself is a reply.
        price (:obj:`SuggestedPostPrice`):
            Expected price of the post.

    Attributes:
        suggested_post_message (:class:`telegram.Message`):
            Optional. Message containing the suggested post. Note that the
            :class:`~telegram.Message` object in this field will not contain
            the :attr:`~telegram.Message.reply_to_message` field even if it itself is a reply.
        price (:obj:`SuggestedPostPrice`):
            Expected price of the post.

    """

    __slots__ = ("price", "suggested_post_message")

    def __init__(
        self,
        price: SuggestedPostPrice,
        suggested_post_message: Message | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.price: SuggestedPostPrice = price
        # Optionals
        self.suggested_post_message: Message | None = suggested_post_message

        self._id_attrs = (self.price, self.suggested_post_message)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "SuggestedPostApprovalFailed":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["price"] = de_json_optional(data.get("price"), SuggestedPostPrice, bot)
        data["suggested_post_message"] = de_json_optional(
            data.get("suggested_post_message"), Message, bot
        )

        return super().de_json(data=data, bot=bot)
