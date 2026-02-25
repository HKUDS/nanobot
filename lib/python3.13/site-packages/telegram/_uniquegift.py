#!/usr/bin/env python
#
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
"""This module contains classes related to unique gifs."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._chat import Chat
from telegram._files.sticker import Sticker
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.argumentparsing import de_json_optional, parse_sequence_arg
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.types import JSONDict
from telegram._utils.warnings import warn
from telegram._utils.warnings_transition import (
    build_deprecation_warning_message,
    warn_about_deprecated_attr_in_property,
)
from telegram.warnings import PTBDeprecationWarning

if TYPE_CHECKING:
    from telegram import Bot


class UniqueGiftColors(TelegramObject):
    """This object contains information about the color scheme for a user's name, message replies
    and link previews based on a unique gift.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`model_custom_emoji_id`, :attr:`symbol_custom_emoji_id`,
    :attr:`light_theme_main_color`, :attr:`light_theme_other_colors`,
    :attr:`dark_theme_main_color`, and :attr:`dark_theme_other_colors` are equal.

    .. versionadded:: 22.6

    Args:
        model_custom_emoji_id (:obj:`str`): Custom emoji identifier of the unique gift's model.
        symbol_custom_emoji_id (:obj:`str`): Custom emoji identifier of the unique gift's symbol.
        light_theme_main_color (:obj:`int`): Main color used in light themes; RGB format.
        light_theme_other_colors (Sequence[:obj:`int`]): List of 1-3 additional colors used in
            light themes; RGB format. |sequenceclassargs|
        dark_theme_main_color (:obj:`int`): Main color used in dark themes; RGB format.
        dark_theme_other_colors (Sequence[:obj:`int`]): List of 1-3 additional colors used in dark
            themes; RGB format. |sequenceclassargs|

    Attributes:
        model_custom_emoji_id (:obj:`str`): Custom emoji identifier of the unique gift's model.
        symbol_custom_emoji_id (:obj:`str`): Custom emoji identifier of the unique gift's symbol.
        light_theme_main_color (:obj:`int`): Main color used in light themes; RGB format.
        light_theme_other_colors (Tuple[:obj:`int`]): Tuple of 1-3 additional colors used in
            light themes; RGB format.
        dark_theme_main_color (:obj:`int`): Main color used in dark themes; RGB format.
        dark_theme_other_colors (Tuple[:obj:`int`]): Tuple of 1-3 additional colors used in dark
            themes; RGB format.
    """

    __slots__ = (
        "dark_theme_main_color",
        "dark_theme_other_colors",
        "light_theme_main_color",
        "light_theme_other_colors",
        "model_custom_emoji_id",
        "symbol_custom_emoji_id",
    )

    def __init__(
        self,
        model_custom_emoji_id: str,
        symbol_custom_emoji_id: str,
        light_theme_main_color: int,
        light_theme_other_colors: Sequence[int],
        dark_theme_main_color: int,
        dark_theme_other_colors: Sequence[int],
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.model_custom_emoji_id: str = model_custom_emoji_id
        self.symbol_custom_emoji_id: str = symbol_custom_emoji_id
        self.light_theme_main_color: int = light_theme_main_color
        self.light_theme_other_colors: tuple[int, ...] = parse_sequence_arg(
            light_theme_other_colors
        )
        self.dark_theme_main_color: int = dark_theme_main_color
        self.dark_theme_other_colors: tuple[int, ...] = parse_sequence_arg(dark_theme_other_colors)

        self._id_attrs = (
            self.model_custom_emoji_id,
            self.symbol_custom_emoji_id,
            self.light_theme_main_color,
            self.light_theme_other_colors,
            self.dark_theme_main_color,
            self.dark_theme_other_colors,
        )

        self._freeze()


class UniqueGiftModel(TelegramObject):
    """This object describes the model of a unique gift.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`name`, :attr:`sticker` and :attr:`rarity_per_mille` are equal.

    .. versionadded:: 22.1

    Args:
        name (:obj:`str`): Name of the model.
        sticker (:class:`telegram.Sticker`): The sticker that represents the unique gift.
        rarity_per_mille (:obj:`int`): The number of unique gifts that receive this
            model for every ``1000`` gifts upgraded.

    Attributes:
        name (:obj:`str`): Name of the model.
        sticker (:class:`telegram.Sticker`): The sticker that represents the unique gift.
        rarity_per_mille (:obj:`int`): The number of unique gifts that receive this
            model for every ``1000`` gifts upgraded.

    """

    __slots__ = (
        "name",
        "rarity_per_mille",
        "sticker",
    )

    def __init__(
        self,
        name: str,
        sticker: Sticker,
        rarity_per_mille: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.name: str = name
        self.sticker: Sticker = sticker
        self.rarity_per_mille: int = rarity_per_mille

        self._id_attrs = (self.name, self.sticker, self.rarity_per_mille)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "UniqueGiftModel":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["sticker"] = de_json_optional(data.get("sticker"), Sticker, bot)

        return super().de_json(data=data, bot=bot)


class UniqueGiftSymbol(TelegramObject):
    """This object describes the symbol shown on the pattern of a unique gift.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`name`, :attr:`sticker` and :attr:`rarity_per_mille` are equal.

    .. versionadded:: 22.1

    Args:
        name (:obj:`str`): Name of the symbol.
        sticker (:class:`telegram.Sticker`): The sticker that represents the unique gift.
        rarity_per_mille (:obj:`int`): The number of unique gifts that receive this
            model for every ``1000`` gifts upgraded.

    Attributes:
        name (:obj:`str`): Name of the symbol.
        sticker (:class:`telegram.Sticker`): The sticker that represents the unique gift.
        rarity_per_mille (:obj:`int`): The number of unique gifts that receive this
            model for every ``1000`` gifts upgraded.

    """

    __slots__ = (
        "name",
        "rarity_per_mille",
        "sticker",
    )

    def __init__(
        self,
        name: str,
        sticker: Sticker,
        rarity_per_mille: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.name: str = name
        self.sticker: Sticker = sticker
        self.rarity_per_mille: int = rarity_per_mille

        self._id_attrs = (self.name, self.sticker, self.rarity_per_mille)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "UniqueGiftSymbol":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["sticker"] = de_json_optional(data.get("sticker"), Sticker, bot)

        return super().de_json(data=data, bot=bot)


class UniqueGiftBackdropColors(TelegramObject):
    """This object describes the colors of the backdrop of a unique gift.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`center_color`, :attr:`edge_color`, :attr:`symbol_color`,
    and :attr:`text_color` are equal.

    .. versionadded:: 22.1

    Args:
        center_color (:obj:`int`): The color in the center of the backdrop in RGB format.
        edge_color (:obj:`int`): The color on the edges of the backdrop in RGB format.
        symbol_color (:obj:`int`): The color to be applied to the symbol in RGB format.
        text_color (:obj:`int`): The color for the text on the backdrop in RGB format.

    Attributes:
        center_color (:obj:`int`): The color in the center of the backdrop in RGB format.
        edge_color (:obj:`int`): The color on the edges of the backdrop in RGB format.
        symbol_color (:obj:`int`): The color to be applied to the symbol in RGB format.
        text_color (:obj:`int`): The color for the text on the backdrop in RGB format.

    """

    __slots__ = (
        "center_color",
        "edge_color",
        "symbol_color",
        "text_color",
    )

    def __init__(
        self,
        center_color: int,
        edge_color: int,
        symbol_color: int,
        text_color: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.center_color: int = center_color
        self.edge_color: int = edge_color
        self.symbol_color: int = symbol_color
        self.text_color: int = text_color

        self._id_attrs = (self.center_color, self.edge_color, self.symbol_color, self.text_color)

        self._freeze()


class UniqueGiftBackdrop(TelegramObject):
    """This object describes the backdrop of a unique gift.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`name`, :attr:`colors`, and :attr:`rarity_per_mille` are equal.

    .. versionadded:: 22.1

    Args:
        name (:obj:`str`): Name of the backdrop.
        colors (:class:`telegram.UniqueGiftBackdropColors`): Colors of the backdrop.
        rarity_per_mille (:obj:`int`): The number of unique gifts that receive this backdrop
            for every ``1000`` gifts upgraded.

    Attributes:
        name (:obj:`str`): Name of the backdrop.
        colors (:class:`telegram.UniqueGiftBackdropColors`): Colors of the backdrop.
        rarity_per_mille (:obj:`int`): The number of unique gifts that receive this backdrop
            for every ``1000`` gifts upgraded.

    """

    __slots__ = (
        "colors",
        "name",
        "rarity_per_mille",
    )

    def __init__(
        self,
        name: str,
        colors: UniqueGiftBackdropColors,
        rarity_per_mille: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.name: str = name
        self.colors: UniqueGiftBackdropColors = colors
        self.rarity_per_mille: int = rarity_per_mille

        self._id_attrs = (self.name, self.colors, self.rarity_per_mille)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "UniqueGiftBackdrop":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["colors"] = de_json_optional(data.get("colors"), UniqueGiftBackdropColors, bot)

        return super().de_json(data=data, bot=bot)


class UniqueGift(TelegramObject):
    """This object describes a unique gift that was upgraded from a regular gift.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`base_name`, :attr:`name`, :attr:`number`, :class:`model`,
    :attr:`symbol`, and :attr:`backdrop` are equal.

    .. versionadded:: 22.1

    Args:
        gift_id (:obj:`str`): Identifier of the regular gift from which the gift was upgraded.

            .. versionadded:: 22.6
        base_name (:obj:`str`): Human-readable name of the regular gift from which this unique
            gift was upgraded.
        name (:obj:`str`): Unique name of the gift. This name can be used
            in ``https://t.me/nft/...`` links and story areas.
        number (:obj:`int`): Unique number of the upgraded gift among gifts upgraded from the
            same regular gift.
        model (:class:`UniqueGiftModel`): Model of the gift.
        symbol (:class:`UniqueGiftSymbol`): Symbol of the gift.
        backdrop (:class:`UniqueGiftBackdrop`): Backdrop of the gift.
        publisher_chat (:class:`telegram.Chat`, optional): Information about the chat that
            published the gift.

            .. versionadded:: 22.4
        is_premium (:obj:`bool`, optional): :obj:`True`, if the original regular gift was
            exclusively purchaseable by Telegram Premium subscribers.

            .. versionadded:: 22.6
        is_from_blockchain (:obj:`bool`, optional): :obj:`True`, if the gift is assigned from the
            TON blockchain and can't be resold or transferred in Telegram.

            .. versionadded:: 22.6
        colors (:class:`telegram.UniqueGiftColors`, optional): The color scheme that can be used
            by the gift's owner for the chat's name, replies to messages and link previews; for
            business account gifts and gifts that are currently on sale only.

            .. versionadded:: 22.6

    Attributes:
        gift_id (:obj:`str`): Identifier of the regular gift from which the gift was upgraded.

            .. versionadded:: 22.6
        base_name (:obj:`str`): Human-readable name of the regular gift from which this unique
            gift was upgraded.
        name (:obj:`str`): Unique name of the gift. This name can be used
            in ``https://t.me/nft/...`` links and story areas.
        number (:obj:`int`): Unique number of the upgraded gift among gifts upgraded from the
            same regular gift.
        model (:class:`telegram.UniqueGiftModel`): Model of the gift.
        symbol (:class:`telegram.UniqueGiftSymbol`): Symbol of the gift.
        backdrop (:class:`telegram.UniqueGiftBackdrop`): Backdrop of the gift.
        publisher_chat (:class:`telegram.Chat`): Optional. Information about the chat that
            published the gift.

            .. versionadded:: 22.4
        is_premium (:obj:`bool`): Optional. :obj:`True`, if the original regular gift was
            exclusively purchaseable by Telegram Premium subscribers.

            .. versionadded:: 22.6
        is_from_blockchain (:obj:`bool`): Optional. :obj:`True`, if the gift is assigned from the
            TON blockchain and can't be resold or transferred in Telegram.

            .. versionadded:: 22.6
        colors (:class:`telegram.UniqueGiftColors`): Optional. The color scheme that can be used
            by the gift's owner for the chat's name, replies to messages and link previews; for
            business account gifts and gifts that are currently on sale only.

            .. versionadded:: 22.6

    """

    __slots__ = (
        "backdrop",
        "base_name",
        "colors",
        "gift_id",
        "is_from_blockchain",
        "is_premium",
        "model",
        "name",
        "number",
        "publisher_chat",
        "symbol",
    )

    def __init__(
        self,
        base_name: str,
        name: str,
        number: int,
        model: UniqueGiftModel,
        symbol: UniqueGiftSymbol,
        backdrop: UniqueGiftBackdrop,
        publisher_chat: Chat | None = None,
        # tags: deprecated 22.6, bot api 9.3
        # temporarily optional to account for changed signature
        gift_id: str | None = None,
        is_from_blockchain: bool | None = None,
        is_premium: bool | None = None,
        colors: UniqueGiftColors | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        # tags: deprecated 22.6, bot api 9.3
        if gift_id is None:
            raise TypeError("`gift_id` is a required argument since Bot API 9.3")

        super().__init__(api_kwargs=api_kwargs)
        self.gift_id: str = gift_id
        self.base_name: str = base_name
        self.name: str = name
        self.number: int = number
        self.model: UniqueGiftModel = model
        self.symbol: UniqueGiftSymbol = symbol
        self.backdrop: UniqueGiftBackdrop = backdrop
        self.publisher_chat: Chat | None = publisher_chat
        self.is_from_blockchain: bool | None = is_from_blockchain
        self.is_premium: bool | None = is_premium
        self.colors: UniqueGiftColors | None = colors

        self._id_attrs = (
            self.base_name,
            self.name,
            self.number,
            self.model,
            self.symbol,
            self.backdrop,
        )

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "UniqueGift":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["model"] = de_json_optional(data.get("model"), UniqueGiftModel, bot)
        data["symbol"] = de_json_optional(data.get("symbol"), UniqueGiftSymbol, bot)
        data["backdrop"] = de_json_optional(data.get("backdrop"), UniqueGiftBackdrop, bot)
        data["publisher_chat"] = de_json_optional(data.get("publisher_chat"), Chat, bot)
        data["colors"] = de_json_optional(data.get("colors"), UniqueGiftColors, bot)

        return super().de_json(data=data, bot=bot)


class UniqueGiftInfo(TelegramObject):
    """Describes a service message about a unique gift that was sent or received.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`gift`, and :attr:`origin` are equal.

    .. versionadded:: 22.1

    Args:
        gift (:class:`UniqueGift`): Information about the gift.
        origin (:obj:`str`): Origin of the gift. Currently, either :attr:`UPGRADE` for gifts
            upgraded from regular gifts, :attr:`TRANSFER` for gifts transferred from other users
            or channels, :attr:`RESALE` for gifts bought from other users,
            :attr:`GIFTED_UPGRADE` for upgrades purchased after the gift was sent, or :attr:`OFFER`
            for gifts bought or sold through gift purchase offers

            .. versionchanged:: 22.3
                The :attr:`RESALE` origin was added.
            .. versionchanged:: 22.6
                Bot API 9.3 added the :attr:`GIFTED_UPGRADE` and :attr:`OFFER` origins.
        owned_gift_id (:obj:`str`, optional) Unique identifier of the received gift for the
            bot; only present for gifts received on behalf of business accounts.
        transfer_star_count (:obj:`int`, optional): Number of Telegram Stars that must be paid
            to transfer the gift; omitted if the bot cannot transfer the gift.
        last_resale_star_count (:obj:`int`, optional): For gifts bought from other users, the price
            paid for the gift.

            .. versionadded:: 22.3
            .. deprecated:: 22.6
                Bot API 9.3 deprecated this field. Use :attr:`last_resale_currency` and
                :attr:`last_resale_amount` instead.
        last_resale_currency (:obj:`str`, optional): For gifts bought from other users, the
            currency in which the payment for the gift was done. Currently, one of ``XTR`` for
            Telegram Stars or ``TON`` for toncoins.

            .. versionadded:: 22.6
        last_resale_amount (:obj:`int`, optional): For gifts bought from other users, the price
            paid for the gift in either Telegram Stars or nanotoncoins.

            .. versionadded:: 22.6
        next_transfer_date (:obj:`datetime.datetime`, optional): Date when the gift can be
            transferred. If it's in the past, then the gift can be transferred now.
            |datetime_localization|

            .. versionadded:: 22.3

    Attributes:
        gift (:class:`UniqueGift`): Information about the gift.
        origin (:obj:`str`): Origin of the gift. Currently, either :attr:`UPGRADE` for gifts
            upgraded from regular gifts, :attr:`TRANSFER` for gifts transferred from other users
            or channels, :attr:`RESALE` for gifts bought from other users,
            :attr:`GIFTED_UPGRADE` for upgrades purchased after the gift was sent, or :attr:`OFFER`
            for gifts bought or sold through gift purchase offers

            .. versionchanged:: 22.3
                The :attr:`RESALE` origin was added.
            .. versionchanged:: 22.6
                Bot API 9.3 added the :attr:`GIFTED_UPGRADE` and :attr:`OFFER` origins.
        owned_gift_id (:obj:`str`) Optional. Unique identifier of the received gift for the
            bot; only present for gifts received on behalf of business accounts.
        transfer_star_count (:obj:`int`): Optional. Number of Telegram Stars that must be paid
            to transfer the gift; omitted if the bot cannot transfer the gift.
        last_resale_currency (:obj:`str`): Optional. For gifts bought from other users, the
            currency in which the payment for the gift was done. Currently, one of ``XTR`` for
            Telegram Stars or ``TON`` for toncoins.

            .. versionadded:: 22.6
        last_resale_amount (:obj:`int`): Optional. For gifts bought from other users, the price
            paid for the gift in either Telegram Stars or nanotoncoins.

            .. versionadded:: 22.6
        next_transfer_date (:obj:`datetime.datetime`): Optional. Date when the gift can be
            transferred. If it's in the past, then the gift can be transferred now.
            |datetime_localization|

            .. versionadded:: 22.3
    """

    GIFTED_UPGRADE: Final[str] = constants.UniqueGiftInfoOrigin.GIFTED_UPGRADE
    """:const:`telegram.constants.UniqueGiftInfoOrigin.GIFTED_UPGRADE`

    .. versionadded:: 22.6
    """
    OFFER: Final[str] = constants.UniqueGiftInfoOrigin.OFFER
    """:const:`telegram.constants.UniqueGiftInfoOrigin.OFFER`

    .. versionadded:: 22.6
    """
    RESALE: Final[str] = constants.UniqueGiftInfoOrigin.RESALE
    """:const:`telegram.constants.UniqueGiftInfoOrigin.RESALE`

    .. versionadded:: 22.3
    """
    TRANSFER: Final[str] = constants.UniqueGiftInfoOrigin.TRANSFER
    """:const:`telegram.constants.UniqueGiftInfoOrigin.TRANSFER`"""
    UPGRADE: Final[str] = constants.UniqueGiftInfoOrigin.UPGRADE
    """:const:`telegram.constants.UniqueGiftInfoOrigin.UPGRADE`"""

    __slots__ = (
        "_last_resale_star_count",
        "gift",
        "last_resale_amount",
        "last_resale_currency",
        "next_transfer_date",
        "origin",
        "owned_gift_id",
        "transfer_star_count",
    )

    def __init__(
        self,
        gift: UniqueGift,
        origin: str,
        owned_gift_id: str | None = None,
        transfer_star_count: int | None = None,
        # tags: deprecated 22.6; bot api 9.3
        last_resale_star_count: int | None = None,
        next_transfer_date: dtm.datetime | None = None,
        last_resale_currency: str | None = None,
        last_resale_amount: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        if last_resale_star_count is not None:
            warn(
                PTBDeprecationWarning(
                    version="22.6",
                    message=build_deprecation_warning_message(
                        deprecated_name="last_resale_star_count",
                        new_name="last_resale_currency/amount",
                        bot_api_version="9.3",
                        object_type="parameter",
                    ),
                ),
                stacklevel=2,
            )

        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.gift: UniqueGift = gift
        self.origin: str = enum.get_member(constants.UniqueGiftInfoOrigin, origin, origin)
        # Optional
        self.owned_gift_id: str | None = owned_gift_id
        self.transfer_star_count: int | None = transfer_star_count
        self._last_resale_star_count: int | None = last_resale_star_count
        self.next_transfer_date: dtm.datetime | None = next_transfer_date
        self.last_resale_currency: str | None = last_resale_currency
        self.last_resale_amount: int | None = last_resale_amount

        self._id_attrs = (self.gift, self.origin)

        self._freeze()

    # tags: deprecated 22.6; bot api 9.3
    @property
    def last_resale_star_count(self) -> int | None:
        """:obj:`int`: Optional. For gifts bought from other users, the price
        paid for the gift.

        .. versionadded:: 22.3
        .. deprecated:: 22.6
            Bot API 9.3 deprecated this field. Use :attr:`last_resale_currency` and
            :attr:`last_resale_amount` instead.
        """
        warn_about_deprecated_attr_in_property(
            deprecated_attr_name="last_resale_star_count",
            new_attr_name="last_resale_currency/amount",
            bot_api_version="9.3",
            ptb_version="22.6",
        )
        return self._last_resale_star_count

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "UniqueGiftInfo":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        loc_tzinfo = extract_tzinfo_from_defaults(bot)
        data["gift"] = de_json_optional(data.get("gift"), UniqueGift, bot)
        data["next_transfer_date"] = from_timestamp(
            data.get("next_transfer_date"), tzinfo=loc_tzinfo
        )

        return super().de_json(data=data, bot=bot)
