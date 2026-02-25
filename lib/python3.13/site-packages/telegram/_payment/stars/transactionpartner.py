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
"""This module contains the classes for Telegram Stars transaction partners."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._chat import Chat
from telegram._gifts import Gift
from telegram._paidmedia import PaidMedia
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils import enum
from telegram._utils.argumentparsing import (
    de_json_optional,
    de_list_optional,
    parse_sequence_arg,
    to_timedelta,
)
from telegram._utils.types import JSONDict, TimePeriod

from .affiliateinfo import AffiliateInfo
from .revenuewithdrawalstate import RevenueWithdrawalState

if TYPE_CHECKING:
    import datetime as dtm

    from telegram import Bot


class TransactionPartner(TelegramObject):
    """This object describes the source of a transaction, or its recipient for outgoing
    transactions. Currently, it can be one of:

    * :class:`TransactionPartnerUser`
    * :class:`TransactionPartnerChat`
    * :class:`TransactionPartnerAffiliateProgram`
    * :class:`TransactionPartnerFragment`
    * :class:`TransactionPartnerTelegramAds`
    * :class:`TransactionPartnerTelegramApi`
    * :class:`TransactionPartnerOther`

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is equal.

    .. versionadded:: 21.4

    .. versionchanged:: 21.11
        Added :class:`TransactionPartnerChat`

    Args:
        type (:obj:`str`): The type of the transaction partner.

    Attributes:
        type (:obj:`str`): The type of the transaction partner.
    """

    __slots__ = ("type",)

    AFFILIATE_PROGRAM: Final[str] = constants.TransactionPartnerType.AFFILIATE_PROGRAM
    """:const:`telegram.constants.TransactionPartnerType.AFFILIATE_PROGRAM`

    .. versionadded:: 21.9
    """
    CHAT: Final[str] = constants.TransactionPartnerType.CHAT
    """:const:`telegram.constants.TransactionPartnerType.CHAT`

    .. versionadded:: 21.11
    """
    FRAGMENT: Final[str] = constants.TransactionPartnerType.FRAGMENT
    """:const:`telegram.constants.TransactionPartnerType.FRAGMENT`"""
    OTHER: Final[str] = constants.TransactionPartnerType.OTHER
    """:const:`telegram.constants.TransactionPartnerType.OTHER`"""
    TELEGRAM_ADS: Final[str] = constants.TransactionPartnerType.TELEGRAM_ADS
    """:const:`telegram.constants.TransactionPartnerType.TELEGRAM_ADS`"""
    TELEGRAM_API: Final[str] = constants.TransactionPartnerType.TELEGRAM_API
    """:const:`telegram.constants.TransactionPartnerType.TELEGRAM_API`"""
    USER: Final[str] = constants.TransactionPartnerType.USER
    """:const:`telegram.constants.TransactionPartnerType.USER`"""

    def __init__(self, type: str, *, api_kwargs: JSONDict | None = None) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.type: str = enum.get_member(constants.TransactionPartnerType, type, type)

        self._id_attrs = (self.type,)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "TransactionPartner":
        """Converts JSON data to the appropriate :class:`TransactionPartner` object, i.e. takes
        care of selecting the correct subclass.

        Args:
            data (dict[:obj:`str`, ...]): The JSON data.
            bot (:class:`telegram.Bot`): The bot associated with this object.

        Returns:
            The Telegram object.

        """
        data = cls._parse_data(data)

        _class_mapping: dict[str, type[TransactionPartner]] = {
            cls.AFFILIATE_PROGRAM: TransactionPartnerAffiliateProgram,
            cls.CHAT: TransactionPartnerChat,
            cls.FRAGMENT: TransactionPartnerFragment,
            cls.USER: TransactionPartnerUser,
            cls.TELEGRAM_ADS: TransactionPartnerTelegramAds,
            cls.TELEGRAM_API: TransactionPartnerTelegramApi,
            cls.OTHER: TransactionPartnerOther,
        }

        if cls is TransactionPartner and data.get("type") in _class_mapping:
            return _class_mapping[data.pop("type")].de_json(data=data, bot=bot)

        return super().de_json(data=data, bot=bot)


class TransactionPartnerAffiliateProgram(TransactionPartner):
    """Describes the affiliate program that issued the affiliate commission received via this
    transaction.

    This object is comparable in terms of equality. Two objects of this class are considered equal,
    if their :attr:`commission_per_mille` are equal.

    .. versionadded:: 21.9

    Args:
        sponsor_user (:class:`telegram.User`, optional): Information about the bot that sponsored
            the affiliate program
        commission_per_mille (:obj:`int`): The number of Telegram Stars received by the bot for
            each 1000 Telegram Stars received by the affiliate program sponsor from referred users.

    Attributes:
        type (:obj:`str`): The type of the transaction partner,
            always :tg-const:`telegram.TransactionPartner.AFFILIATE_PROGRAM`.
        sponsor_user (:class:`telegram.User`): Optional. Information about the bot that sponsored
            the affiliate program
        commission_per_mille (:obj:`int`): The number of Telegram Stars received by the bot for
            each 1000 Telegram Stars received by the affiliate program sponsor from referred users.
    """

    __slots__ = ("commission_per_mille", "sponsor_user")

    def __init__(
        self,
        commission_per_mille: int,
        sponsor_user: "User | None" = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=TransactionPartner.AFFILIATE_PROGRAM, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.sponsor_user: User | None = sponsor_user
            self.commission_per_mille: int = commission_per_mille
            self._id_attrs = (
                self.type,
                self.commission_per_mille,
            )

    @classmethod
    def de_json(
        cls, data: JSONDict, bot: "Bot | None" = None
    ) -> "TransactionPartnerAffiliateProgram":
        """See :meth:`telegram.TransactionPartner.de_json`."""
        data = cls._parse_data(data)

        data["sponsor_user"] = de_json_optional(data.get("sponsor_user"), User, bot)

        return super().de_json(data=data, bot=bot)  # type: ignore[return-value]


class TransactionPartnerChat(TransactionPartner):
    """Describes a transaction with a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`chat` are equal.

    .. versionadded:: 21.11

    Args:
        chat (:class:`telegram.Chat`): Information about the chat.
        gift (:class:`telegram.Gift`, optional): The gift sent to the chat by the bot.

    Attributes:
        type (:obj:`str`): The type of the transaction partner,
            always :tg-const:`telegram.TransactionPartner.CHAT`.
        chat (:class:`telegram.Chat`): Information about the chat.
        gift (:class:`telegram.Gift`): Optional. The gift sent to the user by the bot.

    """

    __slots__ = (
        "chat",
        "gift",
    )

    def __init__(
        self,
        chat: Chat,
        gift: Gift | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=TransactionPartner.CHAT, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.chat: Chat = chat
            self.gift: Gift | None = gift

            self._id_attrs = (
                self.type,
                self.chat,
            )

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "TransactionPartnerChat":
        """See :meth:`telegram.TransactionPartner.de_json`."""
        data = cls._parse_data(data)

        data["chat"] = de_json_optional(data.get("chat"), Chat, bot)
        data["gift"] = de_json_optional(data.get("gift"), Gift, bot)

        return super().de_json(data=data, bot=bot)  # type: ignore[return-value]


class TransactionPartnerFragment(TransactionPartner):
    """Describes a withdrawal transaction with Fragment.

    .. versionadded:: 21.4

    Args:
        withdrawal_state (:class:`telegram.RevenueWithdrawalState`, optional): State of the
            transaction if the transaction is outgoing.

    Attributes:
        type (:obj:`str`): The type of the transaction partner,
            always :tg-const:`telegram.TransactionPartner.FRAGMENT`.
        withdrawal_state (:class:`telegram.RevenueWithdrawalState`): Optional. State of the
            transaction if the transaction is outgoing.
    """

    __slots__ = ("withdrawal_state",)

    def __init__(
        self,
        withdrawal_state: "RevenueWithdrawalState | None" = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=TransactionPartner.FRAGMENT, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.withdrawal_state: RevenueWithdrawalState | None = withdrawal_state

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "TransactionPartnerFragment":
        """See :meth:`telegram.TransactionPartner.de_json`."""
        data = cls._parse_data(data)

        data["withdrawal_state"] = de_json_optional(
            data.get("withdrawal_state"), RevenueWithdrawalState, bot
        )

        return super().de_json(data=data, bot=bot)  # type: ignore[return-value]


class TransactionPartnerUser(TransactionPartner):
    """Describes a transaction with a user.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`user` and :attr:`transaction_type` are equal.

    .. versionadded:: 21.4

    .. versionchanged:: 22.1
       Equality comparison now includes the new required argument :paramref:`transaction_type`,
       introduced in Bot API 9.0.

    Args:
        transaction_type (:obj:`str`): Type of the transaction, currently one of
            :tg-const:`telegram.constants.TransactionPartnerUser.INVOICE_PAYMENT` for payments via
            invoices, :tg-const:`telegram.constants.TransactionPartnerUser.PAID_MEDIA_PAYMENT`
            for payments for paid media,
            :tg-const:`telegram.constants.TransactionPartnerUser.GIFT_PURCHASE` for gifts sent by
            the bot, :tg-const:`telegram.constants.TransactionPartnerUser.PREMIUM_PURCHASE`
            for Telegram Premium subscriptions gifted by the bot,
            :tg-const:`telegram.constants.TransactionPartnerUser.BUSINESS_ACCOUNT_TRANSFER` for
            direct transfers from managed business accounts.

            .. versionadded:: 22.1
        user (:class:`telegram.User`): Information about the user.
        affiliate (:class:`telegram.AffiliateInfo`, optional): Information about the affiliate that
            received a commission via this transaction. Can be available only for
            :tg-const:`telegram.constants.TransactionPartnerUser.INVOICE_PAYMENT`
            and :tg-const:`telegram.constants.TransactionPartnerUser.PAID_MEDIA_PAYMENT`
            transactions.

            .. versionadded:: 21.9
        invoice_payload (:obj:`str`, optional): Bot-specified invoice payload. Can be available
            only for :tg-const:`telegram.constants.TransactionPartnerUser.INVOICE_PAYMENT`
            transactions.
        subscription_period (:obj:`int` | :class:`datetime.timedelta`, optional): The duration of
            the paid subscription. Can be available only for
            :tg-const:`telegram.constants.TransactionPartnerUser.INVOICE_PAYMENT` transactions.

            .. versionadded:: 21.8

            .. versionchanged:: v22.2
                Accepts :obj:`int` objects as well as :class:`datetime.timedelta`.
        paid_media (Sequence[:class:`telegram.PaidMedia`], optional): Information about the paid
            media bought by the user. for
            :tg-const:`telegram.constants.TransactionPartnerUser.PAID_MEDIA_PAYMENT`
            transactions only.

            .. versionadded:: 21.5
        paid_media_payload (:obj:`str`, optional): Bot-specified paid media payload. Can be
            available only for
            :tg-const:`telegram.constants.TransactionPartnerUser.PAID_MEDIA_PAYMENT` transactions.

            .. versionadded:: 21.6
        gift (:class:`telegram.Gift`, optional): The gift sent to the user by the bot; for
            :tg-const:`telegram.constants.TransactionPartnerUser.GIFT_PURCHASE` transactions only.

            .. versionadded:: 21.8
        premium_subscription_duration (:obj:`int`, optional): Number of months the gifted Telegram
            Premium subscription will be active for; for
            :tg-const:`telegram.constants.TransactionPartnerUser.PREMIUM_PURCHASE`
            transactions only.

            .. versionadded:: 22.1

    Attributes:
        type (:obj:`str`): The type of the transaction partner,
            always :tg-const:`telegram.TransactionPartner.USER`.
        transaction_type (:obj:`str`): Type of the transaction, currently one of
            :tg-const:`telegram.constants.TransactionPartnerUser.INVOICE_PAYMENT` for payments via
            invoices, :tg-const:`telegram.constants.TransactionPartnerUser.PAID_MEDIA_PAYMENT`
            for payments for paid media,
            :tg-const:`telegram.constants.TransactionPartnerUser.GIFT_PURCHASE` for gifts sent by
            the bot, :tg-const:`telegram.constants.TransactionPartnerUser.PREMIUM_PURCHASE`
            for Telegram Premium subscriptions gifted by the bot,
            :tg-const:`telegram.constants.TransactionPartnerUser.BUSINESS_ACCOUNT_TRANSFER` for
            direct transfers from managed business accounts.

            .. versionadded:: 22.1
        user (:class:`telegram.User`): Information about the user.
        affiliate (:class:`telegram.AffiliateInfo`): Optional. Information about the affiliate that
            received a commission via this transaction. Can be available only for
            :tg-const:`telegram.constants.TransactionPartnerUser.INVOICE_PAYMENT`
            and :tg-const:`telegram.constants.TransactionPartnerUser.PAID_MEDIA_PAYMENT`
            transactions.

            .. versionadded:: 21.9
        invoice_payload (:obj:`str`): Optional. Bot-specified invoice payload. Can be available
            only for :tg-const:`telegram.constants.TransactionPartnerUser.INVOICE_PAYMENT`
            transactions.
        subscription_period (:class:`datetime.timedelta`): Optional. The duration of the paid
            subscription. Can be available only for
            :tg-const:`telegram.constants.TransactionPartnerUser.INVOICE_PAYMENT` transactions.

            .. versionadded:: 21.8
        paid_media (tuple[:class:`telegram.PaidMedia`]): Optional. Information about the paid
            media bought by the user. for
            :tg-const:`telegram.constants.TransactionPartnerUser.PAID_MEDIA_PAYMENT`
            transactions only.

            .. versionadded:: 21.5
        paid_media_payload (:obj:`str`): Optional. Bot-specified paid media payload. Can be
            available only for
            :tg-const:`telegram.constants.TransactionPartnerUser.PAID_MEDIA_PAYMENT` transactions.

            .. versionadded:: 21.6
        gift (:class:`telegram.Gift`): Optional. The gift sent to the user by the bot; for
            :tg-const:`telegram.constants.TransactionPartnerUser.GIFT_PURCHASE` transactions only.

            .. versionadded:: 21.8
        premium_subscription_duration (:obj:`int`): Optional. Number of months the gifted Telegram
            Premium subscription will be active for; for
            :tg-const:`telegram.constants.TransactionPartnerUser.PREMIUM_PURCHASE`
            transactions only.

            .. versionadded:: 22.1

    """

    __slots__ = (
        "affiliate",
        "gift",
        "invoice_payload",
        "paid_media",
        "paid_media_payload",
        "premium_subscription_duration",
        "subscription_period",
        "transaction_type",
        "user",
    )

    def __init__(
        self,
        transaction_type: str,
        user: "User",
        invoice_payload: str | None = None,
        paid_media: Sequence[PaidMedia] | None = None,
        paid_media_payload: str | None = None,
        subscription_period: TimePeriod | None = None,
        gift: Gift | None = None,
        affiliate: AffiliateInfo | None = None,
        premium_subscription_duration: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=TransactionPartner.USER, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.user: User = user
            self.affiliate: AffiliateInfo | None = affiliate
            self.invoice_payload: str | None = invoice_payload
            self.paid_media: tuple[PaidMedia, ...] | None = parse_sequence_arg(paid_media)
            self.paid_media_payload: str | None = paid_media_payload
            self.subscription_period: dtm.timedelta | None = to_timedelta(subscription_period)
            self.gift: Gift | None = gift
            self.premium_subscription_duration: int | None = premium_subscription_duration
            self.transaction_type: str = transaction_type

            self._id_attrs = (
                self.type,
                self.user,
                self.transaction_type,
            )

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "TransactionPartnerUser":
        """See :meth:`telegram.TransactionPartner.de_json`."""
        data = cls._parse_data(data)

        data["user"] = de_json_optional(data.get("user"), User, bot)
        data["affiliate"] = de_json_optional(data.get("affiliate"), AffiliateInfo, bot)
        data["paid_media"] = de_list_optional(data.get("paid_media"), PaidMedia, bot)
        data["gift"] = de_json_optional(data.get("gift"), Gift, bot)

        return super().de_json(data=data, bot=bot)  # type: ignore[return-value]


class TransactionPartnerOther(TransactionPartner):
    """Describes a transaction with an unknown partner.

    .. versionadded:: 21.4

    Attributes:
        type (:obj:`str`): The type of the transaction partner,
            always :tg-const:`telegram.TransactionPartner.OTHER`.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None) -> None:
        super().__init__(type=TransactionPartner.OTHER, api_kwargs=api_kwargs)
        self._freeze()


class TransactionPartnerTelegramAds(TransactionPartner):
    """Describes a withdrawal transaction to the Telegram Ads platform.

    .. versionadded:: 21.4

    Attributes:
        type (:obj:`str`): The type of the transaction partner,
            always :tg-const:`telegram.TransactionPartner.TELEGRAM_ADS`.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None) -> None:
        super().__init__(type=TransactionPartner.TELEGRAM_ADS, api_kwargs=api_kwargs)
        self._freeze()


class TransactionPartnerTelegramApi(TransactionPartner):
    """Describes a transaction with payment for
    `paid broadcasting <https://core.telegram.org/bots/api#paid-broadcasts>`_.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`request_count` is equal.

    .. versionadded:: 21.7

    Args:
        request_count (:obj:`int`): The number of successful requests that exceeded regular limits
            and were therefore billed.

    Attributes:
        type (:obj:`str`): The type of the transaction partner,
            always :tg-const:`telegram.TransactionPartner.TELEGRAM_API`.
        request_count (:obj:`int`): The number of successful requests that exceeded regular limits
            and were therefore billed.
    """

    __slots__ = ("request_count",)

    def __init__(self, request_count: int, *, api_kwargs: JSONDict | None = None) -> None:
        super().__init__(type=TransactionPartner.TELEGRAM_API, api_kwargs=api_kwargs)
        with self._unfrozen():
            self.request_count: int = request_count
            self._id_attrs = (self.request_count,)
