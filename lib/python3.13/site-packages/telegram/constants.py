# python-telegram-bot - a Python interface to the Telegram Bot API
# Copyright (C) 2015-2026
# by the python-telegram-bot contributors <devs@python-telegram-bot.org>
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
"""This module contains several constants that are relevant for working with the Bot API.

Unless noted otherwise, all constants in this module were extracted from the
`Telegram Bots FAQ <https://core.telegram.org/bots/faq>`_ and
`Telegram Bots API <https://core.telegram.org/bots/api>`_.

Most of the following constants are related to specific classes or topics and are grouped into
enums. If they are related to a specific class, then they are also available as attributes of
those classes.

.. versionchanged:: 20.0

    * Most of the constants in this module are grouped into enums.

.. versionremoved:: 22.3
    Removed deprecated class ``StarTransactions``. Please instead use
    :attr:`telegram.constants.Nanostar.VALUE`.
"""
# TODO: Remove this when https://github.com/PyCQA/pylint/issues/6887 is resolved.
# pylint: disable=invalid-enum-extension,invalid-slots

__all__ = [
    "BOT_API_VERSION",
    "BOT_API_VERSION_INFO",
    "SUPPORTED_WEBHOOK_PORTS",
    "ZERO_DATE",
    "AccentColor",
    "BackgroundFillLimit",
    "BackgroundFillType",
    "BackgroundTypeLimit",
    "BackgroundTypeType",
    "BotCommandLimit",
    "BotCommandScopeType",
    "BotDescriptionLimit",
    "BotNameLimit",
    "BulkRequestLimit",
    "BusinessLimit",
    "CallbackQueryLimit",
    "ChatAction",
    "ChatBoostSources",
    "ChatID",
    "ChatInviteLinkLimit",
    "ChatLimit",
    "ChatMemberStatus",
    "ChatPhotoSize",
    "ChatSubscriptionLimit",
    "ChatType",
    "ContactLimit",
    "CustomEmojiStickerLimit",
    "DiceEmoji",
    "DiceLimit",
    "FileSizeLimit",
    "FloodLimit",
    "ForumIconColor",
    "ForumTopicLimit",
    "GiftLimit",
    "GiveawayLimit",
    "InlineKeyboardButtonLimit",
    "InlineKeyboardMarkupLimit",
    "InlineQueryLimit",
    "InlineQueryResultLimit",
    "InlineQueryResultType",
    "InlineQueryResultsButtonLimit",
    "InputChecklistLimit",
    "InputMediaType",
    "InputPaidMediaType",
    "InputProfilePhotoType",
    "InputStoryContentLimit",
    "InputStoryContentType",
    "InvoiceLimit",
    "KeyboardButtonRequestUsersLimit",
    "LocationLimit",
    "MaskPosition",
    "MediaGroupLimit",
    "MenuButtonType",
    "MessageAttachmentType",
    "MessageEntityType",
    "MessageLimit",
    "MessageOriginType",
    "MessageType",
    "Nanostar",
    "NanostarLimit",
    "OwnedGiftType",
    "PaidMediaType",
    "ParseMode",
    "PollLimit",
    "PollType",
    "PollingLimit",
    "PremiumSubscription",
    "ProfileAccentColor",
    "ReactionEmoji",
    "ReactionType",
    "ReplyLimit",
    "RevenueWithdrawalStateType",
    "StarTransactionsLimit",
    "StickerFormat",
    "StickerLimit",
    "StickerSetLimit",
    "StickerType",
    "StoryAreaPositionLimit",
    "StoryAreaTypeLimit",
    "StoryAreaTypeType",
    "StoryLimit",
    "SuggestedPost",
    "SuggestedPostInfoState",
    "SuggestedPostRefunded",
    "TransactionPartnerType",
    "TransactionPartnerUser",
    "UniqueGiftInfoOrigin",
    "UpdateType",
    "UserProfilePhotosLimit",
    "VerifyLimit",
    "WebhookLimit",
]

import datetime as dtm
import sys
from enum import Enum
from typing import Final, NamedTuple

from telegram._utils.datetime import UTC
from telegram._utils.enum import FloatEnum, IntEnum, StringEnum


class _BotAPIVersion(NamedTuple):
    """Similar behavior to sys.version_info.
    So far TG has only published X.Y releases. We can add X.Y.Z(a(S)) if needed.
    """

    major: int
    minor: int

    def __repr__(self) -> str:
        """Unfortunately calling super().__repr__ doesn't work with typing.NamedTuple, so we
        do this manually.
        """
        return f"BotAPIVersion(major={self.major}, minor={self.minor})"

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


class _AccentColor(NamedTuple):
    """A helper class for (profile) accent colors. Since TG doesn't define a class for this and
    the behavior is quite different for the different accent colors, we don't make this a public
    class. This gives us more flexibility to change the implementation if necessary for future
    versions.
    """

    identifier: int
    name: str | None = None
    light_colors: tuple[int, ...] = ()
    dark_colors: tuple[int, ...] = ()


#: :class:`typing.NamedTuple`: A tuple containing the two components of the version number:
# ``major`` and ``minor``. Both values are integers.
#: The components can also be accessed by name, so ``BOT_API_VERSION_INFO[0]`` is equivalent
#: to ``BOT_API_VERSION_INFO.major`` and so on. Also available as
#: :data:`telegram.__bot_api_version_info__`.
#:
#: .. versionadded:: 20.0
BOT_API_VERSION_INFO: Final[_BotAPIVersion] = _BotAPIVersion(major=9, minor=3)
#: :obj:`str`: Telegram Bot API
#: version supported by this version of `python-telegram-bot`. Also available as
#: :data:`telegram.__bot_api_version__`.
#:
#: .. versionadded:: 13.4
BOT_API_VERSION: Final[str] = str(BOT_API_VERSION_INFO)

# constants above this line are tested

#: list[:obj:`int`]: Ports supported by
#:  :paramref:`telegram.Bot.set_webhook.url`.
SUPPORTED_WEBHOOK_PORTS: Final[list[int]] = [443, 80, 88, 8443]

#: :obj:`datetime.datetime`, value of unix 0.
#: This date literal is used in :class:`telegram.InaccessibleMessage`
#  and :class:`telegram.ChecklistTask`.
#:
#: .. versionadded:: 20.8
ZERO_DATE: Final[dtm.datetime] = dtm.datetime(1970, 1, 1, tzinfo=UTC)


class AccentColor(Enum):
    """This enum contains the available accent colors for
    :class:`telegram.ChatFullInfo.accent_color_id`.
    The members of this enum are named tuples with the following attributes:

    - ``identifier`` (:obj:`int`): The identifier of the accent color.
    - ``name`` (:obj:`str`): Optional. The name of the accent color.
    - ``light_colors`` (tuple[:obj:`str`]): Optional. The light colors of the accent color as HEX
      value.
    - ``dark_colors`` (tuple[:obj:`str`]): Optional. The dark colors of the accent color as HEX
      value.

    Since Telegram gives no exact specification for the accent colors, future accent colors might
    have a different data type.

    .. versionadded:: 20.8
    """

    __slots__ = ()

    COLOR_000 = _AccentColor(identifier=0, name="red")
    """Accent color 0. This color can be customized by app themes."""
    COLOR_001 = _AccentColor(identifier=1, name="orange")
    """Accent color 1. This color can be customized by app themes."""
    COLOR_002 = _AccentColor(identifier=2, name="purple/violet")
    """Accent color 2. This color can be customized by app themes."""
    COLOR_003 = _AccentColor(identifier=3, name="green")
    """Accent color 3. This color can be customized by app themes."""
    COLOR_004 = _AccentColor(identifier=4, name="cyan")
    """Accent color 4. This color can be customized by app themes."""
    COLOR_005 = _AccentColor(identifier=5, name="blue")
    """Accent color 5. This color can be customized by app themes."""
    COLOR_006 = _AccentColor(identifier=6, name="pink")
    """Accent color 6. This color can be customized by app themes."""
    COLOR_007 = _AccentColor(
        identifier=7, light_colors=(0xE15052, 0xF9AE63), dark_colors=(0xFF9380, 0x992F37)
    )
    """Accent color 7. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#E15052;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#F9AE63;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#FF9380;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#992F37;">
        </div><br>
    """
    COLOR_008 = _AccentColor(
        identifier=8, light_colors=(0xE0802B, 0xFAC534), dark_colors=(0xECB04E, 0xC35714)
    )
    """Accent color 8. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#E0802B;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FAC534;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#ECB04E;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#C35714;">
        </div><br>
    """
    COLOR_009 = _AccentColor(
        identifier=9, light_colors=(0xA05FF3, 0xF48FFF), dark_colors=(0xC697FF, 0x5E31C8)
    )
    """Accent color 9. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#A05FF3;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#F48FFF;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#C697FF;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#5E31C8;">
        </div><br>
    """
    COLOR_010 = _AccentColor(
        identifier=10, light_colors=(0x27A910, 0xA7DC57), dark_colors=(0xA7EB6E, 0x167E2D)
    )
    """Accent color 10. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#27A910;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#A7DC57;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#A7EB6E;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#167E2D;">
        </div><br>
    """
    COLOR_011 = _AccentColor(
        identifier=11, light_colors=(0x27ACCE, 0x82E8D6), dark_colors=(0x40D8D0, 0x045C7F)
    )
    """Accent color 11. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#27ACCE;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#82E8D6;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#40D8D0;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#045C7F;">
        </div><br>
    """

    COLOR_012 = _AccentColor(
        identifier=12, light_colors=(0x3391D4, 0x7DD3F0), dark_colors=(0x52BFFF, 0x0B5494)
    )
    """Accent color 12. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#3391D4;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#7DD3F0;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#52BFFF;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#0B5494;">
        </div><br>
    """
    COLOR_013 = _AccentColor(
        identifier=13, light_colors=(0xDD4371, 0xFFBE9F), dark_colors=(0xFF86A6, 0x8E366E)
    )
    """Accent color 13. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#DD4371;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFBE9F;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#FF86A6;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#8E366E;">
        </div><br>
    """
    COLOR_014 = _AccentColor(
        identifier=14,
        light_colors=(0x247BED, 0xF04856, 0xFFFFFF),
        dark_colors=(0x3FA2FE, 0xE5424F, 0xFFFFFF),
    )
    """Accent color 14. This contains three light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#247BED;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#F04856;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFFFFF;">
        </div><br>

    and three dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#3FA2FE;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#E5424F;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFFFFF;">
        </div><br>
    """

    COLOR_015 = _AccentColor(
        identifier=15,
        light_colors=(0xD67722, 0x1EA011, 0xFFFFFF),
        dark_colors=(0xFF905E, 0x32A527, 0xFFFFFF),
    )
    """Accent color 15. This contains three light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#D67722;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#1EA011;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFFFFF;">
        </div><br>

    and three dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#FF905E;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#32A527;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFFFFF;">
        </div><br>
    """

    COLOR_016 = _AccentColor(
        identifier=16,
        light_colors=(0x179E42, 0xE84A3F, 0xFFFFFF),
        dark_colors=(0x66D364, 0xD5444F, 0xFFFFFF),
    )
    """Accent color 16. This contains three light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#179E42;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#E84A3F;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFFFFF;">
        </div><br>

    and three dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#66D364;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#D5444F;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFFFFF;">
        </div><br>
    """

    COLOR_017 = _AccentColor(
        identifier=17,
        light_colors=(0x2894AF, 0x6FC456, 0xFFFFFF),
        dark_colors=(0x22BCE2, 0x3DA240, 0xFFFFFF),
    )
    """Accent color 17. This contains three light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#2894AF;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#6FC456;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFFFFF;">
        </div><br>

    and three dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#22BCE2;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#3DA240;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFFFFF;">
        </div><br>
    """

    COLOR_018 = _AccentColor(
        identifier=18,
        light_colors=(0x0C9AB3, 0xFFAD95, 0xFFE6B5),
        dark_colors=(0x22BCE2, 0xFF9778, 0xFFDA6B),
    )
    """Accent color 18. This contains three light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#0C9AB3;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFAD95;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFE6B5;">
        </div><br>

    and three dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#22BCE2;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FF9778;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFDA6B;">
        </div><br>
    """

    COLOR_019 = _AccentColor(
        identifier=19,
        light_colors=(0x7757D6, 0xF79610, 0xFFDE8E),
        dark_colors=(0x9791FF, 0xF2731D, 0xFFDB59),
    )
    """Accent color 19. This contains three light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#7757D6;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#F79610;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFDE8E;">
        </div><br>

    and three dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#9791FF;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#F2731D;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFDB59;">
        </div><br>
    """

    COLOR_020 = _AccentColor(
        identifier=20,
        light_colors=(0x1585CF, 0xF2AB1D, 0xFFFFFF),
        dark_colors=(0x3DA6EB, 0xEEA51D, 0xFFFFFF),
    )
    """Accent color 20. This contains three light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#1585CF;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#F2AB1D;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFFFFF;">
        </div><br>

    and three dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#3DA6EB;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#EEA51D;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#FFFFFF;">
        </div><br>
    """


class BackgroundTypeType(StringEnum):
    """This enum contains the available types of :class:`telegram.BackgroundType`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 21.2
    """

    __slots__ = ()

    FILL = "fill"
    """:obj:`str`: A :class:`telegram.BackgroundType` with fill background."""
    WALLPAPER = "wallpaper"
    """:obj:`str`: A :class:`telegram.BackgroundType` with wallpaper background."""
    PATTERN = "pattern"
    """:obj:`str`: A :class:`telegram.BackgroundType` with pattern background."""
    CHAT_THEME = "chat_theme"
    """:obj:`str`: A :class:`telegram.BackgroundType` with chat_theme background."""


class BackgroundFillType(StringEnum):
    """This enum contains the available types of :class:`telegram.BackgroundFill`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 21.2
    """

    __slots__ = ()

    SOLID = "solid"
    """:obj:`str`: A :class:`telegram.BackgroundFill` with solid fill."""
    GRADIENT = "gradient"
    """:obj:`str`: A :class:`telegram.BackgroundFill` with gradient fill."""
    FREEFORM_GRADIENT = "freeform_gradient"
    """:obj:`str`: A :class:`telegram.BackgroundFill` with freeform_gradient fill."""


class BotCommandLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.BotCommand` and
    :meth:`telegram.Bot.set_my_commands`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_COMMAND = 1
    """:obj:`int`: Minimum value allowed for :paramref:`~telegram.BotCommand.command` parameter of
    :class:`telegram.BotCommand`.
    """
    MAX_COMMAND = 32
    """:obj:`int`: Maximum value allowed for :paramref:`~telegram.BotCommand.command` parameter of
    :class:`telegram.BotCommand`.
    """
    MIN_DESCRIPTION = 1
    """:obj:`int`: Minimum value allowed for :paramref:`~telegram.BotCommand.description`
    parameter of :class:`telegram.BotCommand`.
    """
    MAX_DESCRIPTION = 256
    """:obj:`int`: Maximum value allowed for :paramref:`~telegram.BotCommand.description`
    parameter of :class:`telegram.BotCommand`.
    """
    MAX_COMMAND_NUMBER = 100
    """:obj:`int`: Maximum number of bot commands passed in a :obj:`list` to the
    :paramref:`~telegram.Bot.set_my_commands.commands`
    parameter of :meth:`telegram.Bot.set_my_commands`.
    """


class BotCommandScopeType(StringEnum):
    """This enum contains the available types of :class:`telegram.BotCommandScope`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    DEFAULT = "default"
    """:obj:`str`: The type of :class:`telegram.BotCommandScopeDefault`."""
    ALL_PRIVATE_CHATS = "all_private_chats"
    """:obj:`str`: The type of :class:`telegram.BotCommandScopeAllPrivateChats`."""
    ALL_GROUP_CHATS = "all_group_chats"
    """:obj:`str`: The type of :class:`telegram.BotCommandScopeAllGroupChats`."""
    ALL_CHAT_ADMINISTRATORS = "all_chat_administrators"
    """:obj:`str`: The type of :class:`telegram.BotCommandScopeAllChatAdministrators`."""
    CHAT = "chat"
    """:obj:`str`: The type of :class:`telegram.BotCommandScopeChat`."""
    CHAT_ADMINISTRATORS = "chat_administrators"
    """:obj:`str`: The type of :class:`telegram.BotCommandScopeChatAdministrators`."""
    CHAT_MEMBER = "chat_member"
    """:obj:`str`: The type of :class:`telegram.BotCommandScopeChatMember`."""


class BotDescriptionLimit(IntEnum):
    """This enum contains limitations for the methods :meth:`telegram.Bot.set_my_description` and
    :meth:`telegram.Bot.set_my_short_description`. The enum members of this enumeration are
    instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.2
    """

    __slots__ = ()

    MAX_DESCRIPTION_LENGTH = 512
    """:obj:`int`: Maximum length for the parameter
    :paramref:`~telegram.Bot.set_my_description.description` of
    :meth:`telegram.Bot.set_my_description`
    """
    MAX_SHORT_DESCRIPTION_LENGTH = 120
    """:obj:`int`: Maximum length for the parameter
    :paramref:`~telegram.Bot.set_my_short_description.short_description` of
    :meth:`telegram.Bot.set_my_short_description`
    """


class BotNameLimit(IntEnum):
    """This enum contains limitations for the methods :meth:`telegram.Bot.set_my_name`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.3
    """

    __slots__ = ()

    MAX_NAME_LENGTH = 64
    """:obj:`int`: Maximum length for the parameter :paramref:`~telegram.Bot.set_my_name.name` of
    :meth:`telegram.Bot.set_my_name`
    """


class BulkRequestLimit(IntEnum):
    """This enum contains limitations for :meth:`telegram.Bot.delete_messages`,
    :meth:`telegram.Bot.forward_messages` and :meth:`telegram.Bot.copy_messages`. The enum members
    of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.8
    """

    __slots__ = ()

    MIN_LIMIT = 1
    """:obj:`int`: Minimum number of messages required for bulk actions."""
    MAX_LIMIT = 100
    """:obj:`int`: Maximum number of messages required for bulk actions."""


class BusinessLimit(IntEnum):
    """This enum contains limitations related to handling business accounts. The enum members
    of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    CHAT_ACTIVITY_TIMEOUT = int(dtm.timedelta(hours=24).total_seconds())
    """:obj:`int`: Time in seconds in which the chat must have been active for. Relevant for
    :paramref:`~telegram.Bot.read_business_message.chat_id`
    of :meth:`~telegram.Bot.read_business_message` and
    :paramref:`~telegram.Bot.transfer_gift.new_owner_chat_id`
    of :meth:`~telegram.Bot.transfer_gift`.
    """
    MIN_NAME_LENGTH = 1
    """:obj:`int`: Minimum length of the name of a business account. Relevant only for
    :paramref:`~telegram.Bot.set_business_account_name.first_name` of
    :meth:`telegram.Bot.set_business_account_name`.
    """
    MAX_NAME_LENGTH = 64
    """:obj:`int`: Maximum length of the name of a business account. Relevant for the parameters
    of :meth:`telegram.Bot.set_business_account_name`.
    """
    MAX_USERNAME_LENGTH = 32
    """::obj:`int`: Maximum length of the username of a business account. Relevant for
    :paramref:`~telegram.Bot.set_business_account_username.username` of
    :meth:`telegram.Bot.set_business_account_username`.
    """
    MAX_BIO_LENGTH = 140
    """:obj:`int`: Maximum length of the bio of a business account. Relevant for
    :paramref:`~telegram.Bot.set_business_account_bio.bio` of
    :meth:`telegram.Bot.set_business_account_bio`.
    """
    MIN_GIFT_RESULTS = 1
    """:obj:`int`: Minimum number of gifts to be returned. Relevant for

    * :paramref:`~telegram.Bot.get_business_account_gifts.limit` of
      :meth:`telegram.Bot.get_business_account_gifts`.
    * :paramref:`~telegram.Bot.get_chat_gifts.limit` of
      :meth:`telegram.Bot.get_chat_gifts`.
    * :paramref:`~telegram.Bot.get_user_gifts.limit` of
      :meth:`telegram.Bot.get_user_gifts`.
    """
    MAX_GIFT_RESULTS = 100
    """:obj:`int`: Maximum number of gifts to be returned. Relevant for

    * :paramref:`~telegram.Bot.get_business_account_gifts.limit` of
      :meth:`telegram.Bot.get_business_account_gifts`.
    * :paramref:`~telegram.Bot.get_chat_gifts.limit` of
      :meth:`telegram.Bot.get_chat_gifts`.
    * :paramref:`~telegram.Bot.get_user_gifts.limit` of
      :meth:`telegram.Bot.get_user_gifts`.
    """
    MIN_STAR_COUNT = 1
    """:obj:`int`: Minimum number of Telegram Stars to be transfered. Relevant for
    :paramref:`~telegram.Bot.transfer_business_account_stars.star_count` of
    :meth:`telegram.Bot.transfer_business_account_stars`.
    """
    MAX_STAR_COUNT = 10000
    """:obj:`int`: Maximum number of Telegram Stars to be transfered. Relevant for
    :paramref:`~telegram.Bot.transfer_business_account_stars.star_count` of
    :meth:`telegram.Bot.transfer_business_account_stars`.
    """


class CallbackQueryLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.CallbackQuery`/
    :meth:`telegram.Bot.answer_callback_query`. The enum members of this enumeration are instances
    of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    ANSWER_CALLBACK_QUERY_TEXT_LENGTH = 200
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.Bot.answer_callback_query.text` parameter of
    :meth:`telegram.Bot.answer_callback_query`."""


class ChatAction(StringEnum):
    """This enum contains the available chat actions for :meth:`telegram.Bot.send_chat_action`.
    The enum members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    CHOOSE_STICKER = "choose_sticker"
    """:obj:`str`: Chat action indicating that the bot is selecting a sticker."""
    FIND_LOCATION = "find_location"
    """:obj:`str`: Chat action indicating that the bot is selecting a location."""
    RECORD_VOICE = "record_voice"
    """:obj:`str`: Chat action indicating that the bot is recording a voice message."""
    RECORD_VIDEO = "record_video"
    """:obj:`str`: Chat action indicating that the bot is recording a video."""
    RECORD_VIDEO_NOTE = "record_video_note"
    """:obj:`str`: Chat action indicating that the bot is recording a video note."""
    TYPING = "typing"
    """:obj:`str`: A chat indicating the bot is typing."""
    UPLOAD_VOICE = "upload_voice"
    """:obj:`str`: Chat action indicating that the bot is uploading a voice message."""
    UPLOAD_DOCUMENT = "upload_document"
    """:obj:`str`: Chat action indicating that the bot is uploading a document."""
    UPLOAD_PHOTO = "upload_photo"
    """:obj:`str`: Chat action indicating that the bot is uploading a photo."""
    UPLOAD_VIDEO = "upload_video"
    """:obj:`str`: Chat action indicating that the bot is uploading a video."""
    UPLOAD_VIDEO_NOTE = "upload_video_note"
    """:obj:`str`: Chat action indicating that the bot is uploading a video note."""


class ChatBoostSources(StringEnum):
    """This enum contains the available sources for a
    :class:`Telegram chat boost <telegram.ChatBoostSource>`.
    The enum members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.8
    """

    __slots__ = ()

    GIFT_CODE = "gift_code"
    """:obj:`str`: The source of the chat boost was a Telegram Premium gift code."""
    GIVEAWAY = "giveaway"
    """:obj:`str`: The source of the chat boost was a Telegram Premium giveaway."""
    PREMIUM = "premium"
    """:obj:`str`: The source of the chat boost was a Telegram Premium subscription/gift."""


class ChatID(IntEnum):
    """This enum contains some special chat IDs. The enum
    members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    ANONYMOUS_ADMIN = 1087968824
    """:obj:`int`: User ID in groups for messages sent by anonymous admins. Telegram chat:
    `@GroupAnonymousBot <https://t.me/GroupAnonymousBot>`_.

    Note:
        :attr:`telegram.Message.from_user` will contain this ID for backwards compatibility only.
        It's recommended to use :attr:`telegram.Message.sender_chat` instead.
    """
    SERVICE_CHAT = 777000
    """:obj:`int`: Telegram service chat, that also acts as sender of channel posts forwarded to
    discussion groups. Telegram chat: `Telegram <https://t.me/+42777>`_.

    Note:
        :attr:`telegram.Message.from_user` will contain this ID for backwards compatibility only.
        It's recommended to use :attr:`telegram.Message.sender_chat` instead.
    """
    FAKE_CHANNEL = 136817688
    """:obj:`int`: User ID in groups when message is sent on behalf of a channel, or when a channel
    votes on a poll. Telegram chat: `@Channel_Bot <https://t.me/Channel_Bot>`_.

    Note:
        * :attr:`telegram.Message.from_user` will contain this ID for backwards compatibility only.
          It's recommended to use :attr:`telegram.Message.sender_chat` instead.
        * :attr:`telegram.PollAnswer.user` will contain this ID for backwards compatibility only.
          It's recommended to use :attr:`telegram.PollAnswer.voter_chat` instead.
    """


class ChatInviteLinkLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.ChatInviteLink`/
    :meth:`telegram.Bot.create_chat_invite_link`/:meth:`telegram.Bot.edit_chat_invite_link`. The
    enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_MEMBER_LIMIT = 1
    """:obj:`int`: Minimum value allowed for the
    :paramref:`~telegram.Bot.create_chat_invite_link.member_limit` parameter of
    :meth:`telegram.Bot.create_chat_invite_link` and
    :paramref:`~telegram.Bot.edit_chat_invite_link.member_limit` of
    :meth:`telegram.Bot.edit_chat_invite_link`.
    """
    MAX_MEMBER_LIMIT = 99999
    """:obj:`int`: Maximum value allowed for the
    :paramref:`~telegram.Bot.create_chat_invite_link.member_limit` parameter of
    :meth:`telegram.Bot.create_chat_invite_link` and
    :paramref:`~telegram.Bot.edit_chat_invite_link.member_limit` of
    :meth:`telegram.Bot.edit_chat_invite_link`.
    """
    NAME_LENGTH = 32
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.Bot.create_chat_invite_link.name` parameter of
    :meth:`telegram.Bot.create_chat_invite_link` and
    :paramref:`~telegram.Bot.edit_chat_invite_link.name` of
    :meth:`telegram.Bot.edit_chat_invite_link`.
    """


class ChatLimit(IntEnum):
    """This enum contains limitations for
    :meth:`telegram.Bot.set_chat_administrator_custom_title`,
    :meth:`telegram.Bot.set_chat_description`, and :meth:`telegram.Bot.set_chat_title`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    CHAT_ADMINISTRATOR_CUSTOM_TITLE_LENGTH = 16
    """:obj:`int`: Maximum length of a :obj:`str` passed as the
    :paramref:`~telegram.Bot.set_chat_administrator_custom_title.custom_title` parameter of
    :meth:`telegram.Bot.set_chat_administrator_custom_title`.
    """
    CHAT_DESCRIPTION_LENGTH = 255
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.Bot.set_chat_description.description` parameter of
    :meth:`telegram.Bot.set_chat_description`.
    """
    MIN_CHAT_TITLE_LENGTH = 1
    """:obj:`int`: Minimum length of a :obj:`str` passed as the
    :paramref:`~telegram.Bot.set_chat_title.title` parameter of
    :meth:`telegram.Bot.set_chat_title`.
    """
    MAX_CHAT_TITLE_LENGTH = 128
    """:obj:`int`: Maximum length of a :obj:`str` passed as the
    :paramref:`~telegram.Bot.set_chat_title.title` parameter of
    :meth:`telegram.Bot.set_chat_title`.
    """


class ChatSubscriptionLimit(IntEnum):
    """This enum contains limitations for
    :paramref:`telegram.Bot.create_chat_subscription_invite_link.subscription_period` and
    :paramref:`telegram.Bot.create_chat_subscription_invite_link.subscription_price`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 21.5
    """

    __slots__ = ()

    SUBSCRIPTION_PERIOD = 2592000
    """:obj:`int`: The number of seconds the subscription will be active."""
    MIN_PRICE = 1
    """:obj:`int`: Amount of stars a user pays, minimum amount the subscription can be set to."""
    MAX_PRICE = 10000
    """:obj:`int`: Amount of stars a user pays, maximum amount the subscription can be set to.

    .. versionchanged:: 22.1
        Bot API 9.0 changed the value to 10000.
    """


class BackgroundTypeLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.BackgroundTypeFill`,
    :class:`telegram.BackgroundTypeWallpaper` and :class:`telegram.BackgroundTypePattern`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 21.2
    """

    __slots__ = ()

    MAX_DIMMING = 100
    """:obj:`int`: Maximum value allowed for:

    * :paramref:`~telegram.BackgroundTypeFill.dark_theme_dimming` parameter of
        :class:`telegram.BackgroundTypeFill`
    * :paramref:`~telegram.BackgroundTypeWallpaper.dark_theme_dimming` parameter of
        :class:`telegram.BackgroundTypeWallpaper`
    """
    MAX_INTENSITY = 100
    """:obj:`int`: Maximum value allowed for :paramref:`~telegram.BackgroundTypePattern.intensity`
    parameter of :class:`telegram.BackgroundTypePattern`
    """


class BackgroundFillLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.BackgroundFillGradient`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 21.2
    """

    __slots__ = ()

    MAX_ROTATION_ANGLE = 359
    """:obj:`int`: Maximum value allowed for:
        :paramref:`~telegram.BackgroundFillGradient.rotation_angle` parameter of
        :class:`telegram.BackgroundFillGradient`
    """


class ChatMemberStatus(StringEnum):
    """This enum contains the available states for :class:`telegram.ChatMember`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    ADMINISTRATOR = "administrator"
    """:obj:`str`: A :class:`telegram.ChatMember` who is administrator of the chat."""
    OWNER = "creator"
    """:obj:`str`: A :class:`telegram.ChatMember` who is the owner of the chat."""
    BANNED = "kicked"
    """:obj:`str`: A :class:`telegram.ChatMember` who was banned in the chat."""
    LEFT = "left"
    """:obj:`str`: A :class:`telegram.ChatMember` who has left the chat."""
    MEMBER = "member"
    """:obj:`str`: A :class:`telegram.ChatMember` who is a member of the chat."""
    RESTRICTED = "restricted"
    """:obj:`str`: A :class:`telegram.ChatMember` who was restricted in this chat."""


class ChatPhotoSize(IntEnum):
    """This enum contains limitations for :class:`telegram.ChatPhoto`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    SMALL = 160
    """:obj:`int`: Width and height of a small chat photo, ID of which is passed in
    :paramref:`~telegram.ChatPhoto.small_file_id` and
    :paramref:`~telegram.ChatPhoto.small_file_unique_id` parameters of
    :class:`telegram.ChatPhoto`.
    """
    BIG = 640
    """:obj:`int`: Width and height of a big chat photo, ID of which is passed in
    :paramref:`~telegram.ChatPhoto.big_file_id` and
    :paramref:`~telegram.ChatPhoto.big_file_unique_id` parameters of
    :class:`telegram.ChatPhoto`.
    """


class ChatType(StringEnum):
    """This enum contains the available types of :class:`telegram.Chat`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    SENDER = "sender"
    """:obj:`str`: A :class:`telegram.Chat` that represents the chat of a :class:`telegram.User`
    sending an :class:`telegram.InlineQuery`. """
    PRIVATE = "private"
    """:obj:`str`: A :class:`telegram.Chat` that is private."""
    GROUP = "group"
    """:obj:`str`: A :class:`telegram.Chat` that is a group."""
    SUPERGROUP = "supergroup"
    """:obj:`str`: A :class:`telegram.Chat` that is a supergroup."""
    CHANNEL = "channel"
    """:obj:`str`: A :class:`telegram.Chat` that is a channel."""


class ContactLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.InlineQueryResultContact`,
    :class:`telegram.InputContactMessageContent`, and :meth:`telegram.Bot.send_contact`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    VCARD = 2048
    """:obj:`int`: Maximum value allowed for:

    * :paramref:`~telegram.Bot.send_contact.vcard` parameter of :meth:`~telegram.Bot.send_contact`
    * :paramref:`~telegram.InlineQueryResultContact.vcard` parameter of
      :class:`~telegram.InlineQueryResultContact`
    * :paramref:`~telegram.InputContactMessageContent.vcard` parameter of
      :class:`~telegram.InputContactMessageContent`
    """


class CustomEmojiStickerLimit(IntEnum):
    """This enum contains limitations for :meth:`telegram.Bot.get_custom_emoji_stickers`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    CUSTOM_EMOJI_IDENTIFIER_LIMIT = 200
    """:obj:`int`: Maximum amount of custom emoji identifiers which can be specified for the
    :paramref:`~telegram.Bot.get_custom_emoji_stickers.custom_emoji_ids` parameter of
    :meth:`telegram.Bot.get_custom_emoji_stickers`.
    """


class DiceEmoji(StringEnum):
    """This enum contains the available emoji for :class:`telegram.Dice`/
    :meth:`telegram.Bot.send_dice`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    DICE = "🎲"
    """:obj:`str`: A :class:`telegram.Dice` with the emoji ``🎲``."""
    DARTS = "🎯"
    """:obj:`str`: A :class:`telegram.Dice` with the emoji ``🎯``."""
    BASKETBALL = "🏀"
    """:obj:`str`: A :class:`telegram.Dice` with the emoji ``🏀``."""
    FOOTBALL = "⚽"
    """:obj:`str`: A :class:`telegram.Dice` with the emoji ``⚽``."""
    SLOT_MACHINE = "🎰"
    """:obj:`str`: A :class:`telegram.Dice` with the emoji ``🎰``."""
    BOWLING = "🎳"
    """:obj:`str`: A :class:`telegram.Dice` with the emoji ``🎳``."""


class DiceLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.Dice`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_VALUE = 1
    """:obj:`int`: Minimum value allowed for :paramref:`~telegram.Dice.value` parameter of
    :class:`telegram.Dice` (any emoji).
    """

    MAX_VALUE_BASKETBALL = 5
    """:obj:`int`: Maximum value allowed for :paramref:`~telegram.Dice.value` parameter of
    :class:`telegram.Dice` if :paramref:`~telegram.Dice.emoji` is
    :tg-const:`telegram.constants.DiceEmoji.BASKETBALL`.
    """
    MAX_VALUE_BOWLING = 6
    """:obj:`int`: Maximum value allowed for :paramref:`~telegram.Dice.value` parameter of
    :class:`telegram.Dice` if :paramref:`~telegram.Dice.emoji` is
    :tg-const:`telegram.constants.DiceEmoji.BOWLING`.
    """
    MAX_VALUE_DARTS = 6
    """:obj:`int`: Maximum value allowed for :paramref:`~telegram.Dice.value` parameter of
    :class:`telegram.Dice` if :paramref:`~telegram.Dice.emoji` is
    :tg-const:`telegram.constants.DiceEmoji.DARTS`.
    """
    MAX_VALUE_DICE = 6
    """:obj:`int`: Maximum value allowed for :paramref:`~telegram.Dice.value` parameter of
    :class:`telegram.Dice` if :paramref:`~telegram.Dice.emoji` is
    :tg-const:`telegram.constants.DiceEmoji.DICE`.
    """
    MAX_VALUE_FOOTBALL = 5
    """:obj:`int`: Maximum value allowed for :paramref:`~telegram.Dice.value` parameter of
    :class:`telegram.Dice` if :paramref:`~telegram.Dice.emoji` is
    :tg-const:`telegram.constants.DiceEmoji.FOOTBALL`.
    """
    MAX_VALUE_SLOT_MACHINE = 64
    """:obj:`int`: Maximum value allowed for :paramref:`~telegram.Dice.value` parameter of
    :class:`telegram.Dice` if :paramref:`~telegram.Dice.emoji` is
    :tg-const:`telegram.constants.DiceEmoji.SLOT_MACHINE`.
    """


class FileSizeLimit(IntEnum):
    """This enum contains limitations regarding the upload and download of files. The enum
    members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    FILESIZE_DOWNLOAD = int(20e6)  # (20MB)
    """:obj:`int`: Bots can download files of up to 20MB in size."""
    FILESIZE_UPLOAD = int(50e6)  # (50MB)
    """:obj:`int`: Bots can upload non-photo files of up to 50MB in size."""
    FILESIZE_UPLOAD_LOCAL_MODE = int(2e9)  # (2000MB)
    """:obj:`int`: Bots can upload non-photo files of up to 2000MB in size when using a local bot
       API server.
    """
    FILESIZE_DOWNLOAD_LOCAL_MODE = sys.maxsize
    """:obj:`int`: Bots can download files without a size limit when using a local bot API server.
    """
    PHOTOSIZE_UPLOAD = int(10e6)  # (10MB)
    """:obj:`int`: Bots can upload photo files of up to 10MB in size."""
    VOICE_NOTE_FILE_SIZE = int(1e6)  # (1MB)
    """:obj:`int`: File size limit for the :meth:`~telegram.Bot.send_voice` method of
    :class:`telegram.Bot`. Bots can send :mimetype:`audio/ogg` files of up to 1MB in size as
    a voice note. Larger voice notes (up to 20MB) will be sent as files."""
    # It seems OK to link 20MB limit to FILESIZE_DOWNLOAD rather than creating a new constant


class FloodLimit(IntEnum):
    """This enum contains limitations regarding flood limits. The enum
    members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MESSAGES_PER_SECOND_PER_CHAT = 1
    """:obj:`int`: The number of messages that can be sent per second in a particular chat.
    Telegram may allow short bursts that go over this limit, but eventually you'll begin
    receiving 429 errors.
    """
    MESSAGES_PER_SECOND = 30
    """:obj:`int`: The number of messages that can roughly be sent in an interval of 30 seconds
    across all chats.
    """
    MESSAGES_PER_MINUTE_PER_GROUP = 20
    """:obj:`int`: The number of messages that can roughly be sent to a particular group within one
    minute.
    """
    PAID_MESSAGES_PER_SECOND = 1000
    """:obj:`int`: The number of messages that can be sent per second when paying with the bot's
    Telegram Star balance. See e.g. parameter
    :paramref:`~telegram.Bot.send_message.allow_paid_broadcast` of
    :meth:`~telegram.Bot.send_message`.

    .. versionadded:: 21.7
    """


class ForumIconColor(IntEnum):
    """This enum contains the available colors for use in
    :paramref:`telegram.Bot.create_forum_topic.icon_color`. The enum members of this enumeration
    are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    BLUE = 0x6FB9F0
    """:obj:`int`: An icon with a color which corresponds to blue (``0x6FB9F0``).

    .. raw:: html

        <div style="height:15px; width:15px; background-color:#6FB9F0;"></div>

    """
    YELLOW = 0xFFD67E
    """:obj:`int`: An icon with a color which corresponds to yellow (``0xFFD67E``).

    .. raw:: html

        <div style="height:15px; width:15px; background-color:#FFD67E;"></div>

    """
    PURPLE = 0xCB86DB
    """:obj:`int`: An icon with a color which corresponds to purple (``0xCB86DB``).

    .. raw:: html

        <div style="height:15px; width:15px; background-color:#CB86DB;"></div>

    """
    GREEN = 0x8EEE98
    """:obj:`int`: An icon with a color which corresponds to green (``0x8EEE98``).

    .. raw:: html

        <div style="height:15px; width:15px; background-color:#8EEE98;"></div>

    """
    PINK = 0xFF93B2
    """:obj:`int`: An icon with a color which corresponds to pink (``0xFF93B2``).

    .. raw:: html

        <div style="height:15px; width:15px; background-color:#FF93B2;"></div>

    """
    RED = 0xFB6F5F
    """:obj:`int`: An icon with a color which corresponds to red (``0xFB6F5F``).

    .. raw:: html

        <div style="height:15px; width:15px; background-color:#FB6F5F;"></div>

    """


class GiftLimit(IntEnum):
    """This enum contains limitations for :meth:`~telegram.Bot.send_gift`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 21.8
    """

    __slots__ = ()

    MAX_TEXT_LENGTH = 128
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.Bot.send_gift.text` parameter of :meth:`~telegram.Bot.send_gift`.

    .. versionchanged:: 21.11
       Updated Value to 128 based on Bot API 8.3
    """


class GiveawayLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.Giveaway` and related classes.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.8
    """

    __slots__ = ()

    MAX_WINNERS = 100
    """:obj:`int`: Maximum number of winners allowed for :class:`telegram.GiveawayWinners.winners`.
    """


class KeyboardButtonRequestUsersLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.KeyboardButtonRequestUsers`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.8
    """

    __slots__ = ()

    MIN_QUANTITY = 1
    """:obj:`int`: Minimum value allowed for
    :paramref:`~telegram.KeyboardButtonRequestUsers.max_quantity` parameter of
    :class:`telegram.KeyboardButtonRequestUsers`.
    """
    MAX_QUANTITY = 10
    """:obj:`int`: Maximum value allowed for
    :paramref:`~telegram.KeyboardButtonRequestUsers.max_quantity` parameter of
    :class:`telegram.KeyboardButtonRequestUsers`.
    """


class InlineKeyboardButtonLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.InlineKeyboardButton`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_CALLBACK_DATA = 1
    """:obj:`int`: Minimum length allowed for
    :paramref:`~telegram.InlineKeyboardButton.callback_data` parameter of
    :class:`telegram.InlineKeyboardButton`
    """
    MAX_CALLBACK_DATA = 64
    """:obj:`int`: Maximum length allowed for
    :paramref:`~telegram.InlineKeyboardButton.callback_data` parameter of
    :class:`telegram.InlineKeyboardButton`
    """
    MIN_COPY_TEXT = 1
    """:obj:`int`: Minimum length allowed for
    :paramref:`~telegram.CopyTextButton.text` parameter of :class:`telegram.CopyTextButton`
    """
    MAX_COPY_TEXT = 256
    """:obj:`int`: Maximum length allowed for
    :paramref:`~telegram.CopyTextButton.text` parameter of :class:`telegram.CopyTextButton`
    """


class InlineKeyboardMarkupLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.InlineKeyboardMarkup`/
    :meth:`telegram.Bot.send_message` & friends. The enum
    members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    TOTAL_BUTTON_NUMBER = 100
    """:obj:`int`: Maximum number of buttons that can be attached to a message.

    Note:
        This value is undocumented and might be changed by Telegram.
    """
    BUTTONS_PER_ROW = 8
    """:obj:`int`: Maximum number of buttons that can be attached to a message per row.

    Note:
        This value is undocumented and might be changed by Telegram.
    """


class InputChecklistLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.InputChecklist`/
    :class:`telegram.InputChecklistTask`. The enum
    members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 22.3
    """

    __slots__ = ()

    MIN_TITLE_LENGTH = 1
    """:obj:`int`: Minimum number of characters in a :obj:`str` passed as
    :paramref:`~telegram.InputChecklist.title` parameter of :class:`telegram.InputChecklist`
    """

    MAX_TITLE_LENGTH = 255
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as
    :paramref:`~telegram.InputChecklist.title` parameter of :class:`telegram.InputChecklist`
    """

    MIN_TEXT_LENGTH = 1
    """:obj:`int`: Minimum number of characters in a :obj:`str` passed as
    :paramref:`~telegram.InputChecklistTask.text` parameter of :class:`telegram.InputChecklistTask`
    """

    MAX_TEXT_LENGTH = 100
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as
    :paramref:`~telegram.InputChecklistTask.text` parameter of :class:`telegram.InputChecklistTask`
    """

    MIN_TASK_NUMBER = 1
    """:obj:`int`: Minimum number of tasks passed as :paramref:`~telegram.InputChecklist.tasks`
    parameter of :class:`telegram.InputChecklist`
    """

    MAX_TASK_NUMBER = 30
    """:obj:`int`: Maximum number of tasks passed as :paramref:`~telegram.InputChecklistTask.tasks`
    parameter of :class:`telegram.InputChecklistTask`
    """


class InputMediaType(StringEnum):
    """This enum contains the available types of :class:`telegram.InputMedia`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    ANIMATION = "animation"
    """:obj:`str`: Type of :class:`telegram.InputMediaAnimation`."""
    DOCUMENT = "document"
    """:obj:`str`: Type of :class:`telegram.InputMediaDocument`."""
    AUDIO = "audio"
    """:obj:`str`: Type of :class:`telegram.InputMediaAudio`."""
    PHOTO = "photo"
    """:obj:`str`: Type of :class:`telegram.InputMediaPhoto`."""
    VIDEO = "video"
    """:obj:`str`: Type of :class:`telegram.InputMediaVideo`."""


class InputPaidMediaType(StringEnum):
    """This enum contains the available types of :class:`telegram.InputPaidMedia`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 21.4
    """

    __slots__ = ()

    PHOTO = "photo"
    """:obj:`str`: Type of :class:`telegram.InputMediaPhoto`."""
    VIDEO = "video"
    """:obj:`str`: Type of :class:`telegram.InputMediaVideo`."""


class InputProfilePhotoType(StringEnum):
    """This enum contains the available types of :class:`telegram.InputProfilePhoto`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    STATIC = "static"
    """:obj:`str`: Type of :class:`telegram.InputProfilePhotoStatic`."""
    ANIMATED = "animated"
    """:obj:`str`: Type of :class:`telegram.InputProfilePhotoAnimated`."""


class InputStoryContentLimit(StringEnum):
    """This enum contains limitations for :class:`telegram.InputStoryContentPhoto`/
    :class:`telegram.InputStoryContentVideo`. The enum members of this enumeration are instances
    of :class:`int` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    PHOTOSIZE_UPLOAD = FileSizeLimit.PHOTOSIZE_UPLOAD  # (10MB)
    """:obj:`int`: Maximum file size of the photo to be passed to
    :paramref:`~telegram.InputStoryContentPhoto.photo` parameter of
    :class:`telegram.InputStoryContentPhoto` in Bytes.
    """
    PHOTO_WIDTH = 1080
    """:obj:`int`: Horizontal resolution of the photo to be passed to
    :paramref:`~telegram.InputStoryContentPhoto.photo` parameter of
    :class:`telegram.InputStoryContentPhoto`.
    """
    PHOTO_HEIGHT = 1920
    """:obj:`int`: Vertical resolution of the video to be passed to
    :paramref:`~telegram.InputStoryContentPhoto.photo` parameter of
    :class:`telegram.InputStoryContentPhoto`.
    """
    VIDEOSIZE_UPLOAD = int(30e6)  # (30MB)
    """:obj:`int`: Maximum file size of the video to be passed to
    :paramref:`~telegram.InputStoryContentVideo.video` parameter of
    :class:`telegram.InputStoryContentVideo` in Bytes.
    """
    VIDEO_WIDTH = 720
    """:obj:`int`: Horizontal resolution of the video to be passed to
    :paramref:`~telegram.InputStoryContentVideo.video` parameter of
    :class:`telegram.InputStoryContentVideo`.
    """
    VIDEO_HEIGHT = 1080
    """:obj:`int`: Vertical resolution of the video to be passed to
    :paramref:`~telegram.InputStoryContentVideo.video` parameter of
    :class:`telegram.InputStoryContentVideo`.
    """
    MAX_VIDEO_DURATION = int(dtm.timedelta(seconds=60).total_seconds())
    """:obj:`int`: Maximum duration of the video to be passed to
    :paramref:`~telegram.InputStoryContentVideo.duration` parameter of
    :class:`telegram.InputStoryContentVideo`.
    """


class InputStoryContentType(StringEnum):
    """This enum contains the available types of :class:`telegram.InputStoryContent`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    PHOTO = "photo"
    """:obj:`str`: Type of :class:`telegram.InputStoryContentPhoto`."""
    VIDEO = "video"
    """:obj:`str`: Type of :class:`telegram.InputStoryContentVideo`."""


class InlineQueryLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.InlineQuery`/
    :meth:`telegram.Bot.answer_inline_query`. The enum members of this enumeration are instances
    of :class:`int` and can be treated as such.

    .. versionadded:: 20.0

    .. versionchanged:: 22.0
        Removed deprecated attributes ``InlineQueryLimit.MIN_SWITCH_PM_TEXT_LENGTH`` and
        ``InlineQueryLimit.MAX_SWITCH_PM_TEXT_LENGTH``. Please instead use
        :attr:`InlineQueryResultsButtonLimit.MIN_START_PARAMETER_LENGTH` and
        :attr:`InlineQueryResultsButtonLimit.MAX_START_PARAMETER_LENGTH`.
    """

    __slots__ = ()

    RESULTS = 50
    """:obj:`int`: Maximum number of results that can be passed to
    :meth:`telegram.Bot.answer_inline_query`."""
    MAX_OFFSET_LENGTH = 64
    """:obj:`int`: Maximum number of bytes in a :obj:`str` passed as the
    :paramref:`~telegram.Bot.answer_inline_query.next_offset` parameter of
    :meth:`telegram.Bot.answer_inline_query`."""
    MAX_QUERY_LENGTH = 256
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.InlineQuery.query` parameter of :class:`telegram.InlineQuery`."""


class InlineQueryResultLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.InlineQueryResult` and its subclasses.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_ID_LENGTH = 1
    """:obj:`int`: Minimum number of bytes in a :obj:`str` passed as the
    :paramref:`~telegram.InlineQueryResult.id` parameter of
    :class:`telegram.InlineQueryResult` and its subclasses
    """
    MAX_ID_LENGTH = 64
    """:obj:`int`: Maximum number of bytes in a :obj:`str` passed as the
    :paramref:`~telegram.InlineQueryResult.id` parameter of
    :class:`telegram.InlineQueryResult` and its subclasses
    """


class InlineQueryResultsButtonLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.InlineQueryResultsButton`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.3
    """

    __slots__ = ()

    MIN_START_PARAMETER_LENGTH = 1
    """:obj:`int`: Minimum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.InlineQueryResultsButton.start_parameter` parameter of
    :meth:`telegram.InlineQueryResultsButton`."""

    MAX_START_PARAMETER_LENGTH = 64
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.InlineQueryResultsButton.start_parameter` parameter of
    :meth:`telegram.InlineQueryResultsButton`."""


class InlineQueryResultType(StringEnum):
    """This enum contains the available types of :class:`telegram.InlineQueryResult`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    AUDIO = "audio"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultAudio` and
    :class:`telegram.InlineQueryResultCachedAudio`.
    """
    DOCUMENT = "document"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultDocument` and
    :class:`telegram.InlineQueryResultCachedDocument`.
    """
    GIF = "gif"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultGif` and
    :class:`telegram.InlineQueryResultCachedGif`.
    """
    MPEG4GIF = "mpeg4_gif"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultMpeg4Gif` and
    :class:`telegram.InlineQueryResultCachedMpeg4Gif`.
    """
    PHOTO = "photo"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultPhoto` and
    :class:`telegram.InlineQueryResultCachedPhoto`.
    """
    STICKER = "sticker"
    """:obj:`str`: Type of and :class:`telegram.InlineQueryResultCachedSticker`."""
    VIDEO = "video"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultVideo` and
    :class:`telegram.InlineQueryResultCachedVideo`.
    """
    VOICE = "voice"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultVoice` and
    :class:`telegram.InlineQueryResultCachedVoice`.
    """
    ARTICLE = "article"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultArticle`."""
    CONTACT = "contact"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultContact`."""
    GAME = "game"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultGame`."""
    LOCATION = "location"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultLocation`."""
    VENUE = "venue"
    """:obj:`str`: Type of :class:`telegram.InlineQueryResultVenue`."""


class LocationLimit(IntEnum):
    """This enum contains limitations for
    :class:`telegram.Location`/:class:`telegram.ChatLocation`/
    :meth:`telegram.Bot.edit_message_live_location`/:meth:`telegram.Bot.send_location`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_CHAT_LOCATION_ADDRESS = 1
    """:obj:`int`: Minimum value allowed for :paramref:`~telegram.ChatLocation.address` parameter
    of :class:`telegram.ChatLocation`
    """
    MAX_CHAT_LOCATION_ADDRESS = 64
    """:obj:`int`: Minimum value allowed for :paramref:`~telegram.ChatLocation.address` parameter
    of :class:`telegram.ChatLocation`
    """

    HORIZONTAL_ACCURACY = 1500
    """:obj:`int`: Maximum value allowed for:

    * :paramref:`~telegram.Location.horizontal_accuracy` parameter of :class:`telegram.Location`
    * :paramref:`~telegram.InlineQueryResultLocation.horizontal_accuracy` parameter of
      :class:`telegram.InlineQueryResultLocation`
    * :paramref:`~telegram.InputLocationMessageContent.horizontal_accuracy` parameter of
      :class:`telegram.InputLocationMessageContent`
    * :paramref:`~telegram.Bot.edit_message_live_location.horizontal_accuracy` parameter of
      :meth:`telegram.Bot.edit_message_live_location`
    * :paramref:`~telegram.Bot.send_location.horizontal_accuracy` parameter of
      :meth:`telegram.Bot.send_location`
    """

    MIN_HEADING = 1
    """:obj:`int`: Minimum value allowed for:

    * :paramref:`~telegram.Location.heading` parameter of :class:`telegram.Location`
    * :paramref:`~telegram.InlineQueryResultLocation.heading` parameter of
      :class:`telegram.InlineQueryResultLocation`
    * :paramref:`~telegram.InputLocationMessageContent.heading` parameter of
      :class:`telegram.InputLocationMessageContent`
    * :paramref:`~telegram.Bot.edit_message_live_location.heading` parameter of
      :meth:`telegram.Bot.edit_message_live_location`
    * :paramref:`~telegram.Bot.send_location.heading` parameter of
      :meth:`telegram.Bot.send_location`
    """
    MAX_HEADING = 360
    """:obj:`int`: Maximum value allowed for:

    * :paramref:`~telegram.Location.heading` parameter of :class:`telegram.Location`
    * :paramref:`~telegram.InlineQueryResultLocation.heading` parameter of
      :class:`telegram.InlineQueryResultLocation`
    * :paramref:`~telegram.InputLocationMessageContent.heading` parameter of
      :class:`telegram.InputLocationMessageContent`
    * :paramref:`~telegram.Bot.edit_message_live_location.heading` parameter of
      :meth:`telegram.Bot.edit_message_live_location`
    * :paramref:`~telegram.Bot.send_location.heading` parameter of
      :meth:`telegram.Bot.send_location`
    """

    MIN_LIVE_PERIOD = 60
    """:obj:`int`: Minimum value allowed for:

    * :paramref:`~telegram.InlineQueryResultLocation.live_period` parameter of
      :class:`telegram.InlineQueryResultLocation`
    * :paramref:`~telegram.InputLocationMessageContent.live_period` parameter of
      :class:`telegram.InputLocationMessageContent`
    * :paramref:`~telegram.Bot.edit_message_live_location.live_period` parameter of
      :meth:`telegram.Bot.edit_message_live_location`
    * :paramref:`~telegram.Bot.send_location.live_period` parameter of
      :meth:`telegram.Bot.send_location`
    """
    MAX_LIVE_PERIOD = 86400
    """:obj:`int`: Maximum value allowed for:

    * :paramref:`~telegram.InlineQueryResultLocation.live_period` parameter of
      :class:`telegram.InlineQueryResultLocation`
    * :paramref:`~telegram.InputLocationMessageContent.live_period` parameter of
      :class:`telegram.InputLocationMessageContent`
    * :paramref:`~telegram.Bot.edit_message_live_location.live_period` parameter of
      :meth:`telegram.Bot.edit_message_live_location`
    * :paramref:`~telegram.Bot.send_location.live_period` parameter of
      :meth:`telegram.Bot.send_location`
    """

    LIVE_PERIOD_FOREVER = int(hex(0x7FFFFFFF), 16)
    """:obj:`int`: Value for live locations that can be edited indefinitely. Passed in:

    * :paramref:`~telegram.InlineQueryResultLocation.live_period` parameter of
      :class:`telegram.InlineQueryResultLocation`
    * :paramref:`~telegram.InputLocationMessageContent.live_period` parameter of
      :class:`telegram.InputLocationMessageContent`
    * :paramref:`~telegram.Bot.edit_message_live_location.live_period` parameter of
      :meth:`telegram.Bot.edit_message_live_location`
    * :paramref:`~telegram.Bot.send_location.live_period` parameter of
      :meth:`telegram.Bot.send_location`

    .. versionadded:: 21.2
    """

    MIN_PROXIMITY_ALERT_RADIUS = 1
    """:obj:`int`: Minimum value allowed for:

    * :paramref:`~telegram.InlineQueryResultLocation.proximity_alert_radius` parameter of
      :class:`telegram.InlineQueryResultLocation`
    * :paramref:`~telegram.InputLocationMessageContent.proximity_alert_radius` parameter of
      :class:`telegram.InputLocationMessageContent`
    * :paramref:`~telegram.Bot.edit_message_live_location.proximity_alert_radius` parameter of
      :meth:`telegram.Bot.edit_message_live_location`
    * :paramref:`~telegram.Bot.send_location.proximity_alert_radius` parameter of
      :meth:`telegram.Bot.send_location`
    """
    MAX_PROXIMITY_ALERT_RADIUS = 100000
    """:obj:`int`: Maximum value allowed for:

    * :paramref:`~telegram.InlineQueryResultLocation.proximity_alert_radius` parameter of
      :class:`telegram.InlineQueryResultLocation`
    * :paramref:`~telegram.InputLocationMessageContent.proximity_alert_radius` parameter of
      :class:`telegram.InputLocationMessageContent`
    * :paramref:`~telegram.Bot.edit_message_live_location.proximity_alert_radius` parameter of
      :meth:`telegram.Bot.edit_message_live_location`
    * :paramref:`~telegram.Bot.send_location.proximity_alert_radius` parameter of
      :meth:`telegram.Bot.send_location`
    """


class MaskPosition(StringEnum):
    """This enum contains the available positions for :class:`telegram.MaskPosition`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    FOREHEAD = "forehead"
    """:obj:`str`: Mask position for a sticker on the forehead."""
    EYES = "eyes"
    """:obj:`str`: Mask position for a sticker on the eyes."""
    MOUTH = "mouth"
    """:obj:`str`: Mask position for a sticker on the mouth."""
    CHIN = "chin"
    """:obj:`str`: Mask position for a sticker on the chin."""


class MediaGroupLimit(IntEnum):
    """This enum contains limitations for :meth:`telegram.Bot.send_media_group`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_MEDIA_LENGTH = 2
    """:obj:`int`: Minimum length of a :obj:`list` passed as the
    :paramref:`~telegram.Bot.send_media_group.media` parameter of
    :meth:`telegram.Bot.send_media_group`.
    """
    MAX_MEDIA_LENGTH = 10
    """:obj:`int`: Maximum length of a :obj:`list` passed as the
    :paramref:`~telegram.Bot.send_media_group.media` parameter of
    :meth:`telegram.Bot.send_media_group`.
    """


class MenuButtonType(StringEnum):
    """This enum contains the available types of :class:`telegram.MenuButton`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    COMMANDS = "commands"
    """:obj:`str`: The type of :class:`telegram.MenuButtonCommands`."""
    WEB_APP = "web_app"
    """:obj:`str`: The type of :class:`telegram.MenuButtonWebApp`."""
    DEFAULT = "default"
    """:obj:`str`: The type of :class:`telegram.MenuButtonDefault`."""


class MessageAttachmentType(StringEnum):
    """This enum contains the available types of :class:`telegram.Message` that can be seen
    as attachment. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    # Make sure that all constants here are also listed in the MessageType Enum!
    # (Enums are not extendable)

    ANIMATION = "animation"
    """:obj:`str`: Messages with :attr:`telegram.Message.animation`."""
    AUDIO = "audio"
    """:obj:`str`: Messages with :attr:`telegram.Message.audio`."""
    CONTACT = "contact"
    """:obj:`str`: Messages with :attr:`telegram.Message.contact`."""
    DICE = "dice"
    """:obj:`str`: Messages with :attr:`telegram.Message.dice`."""
    DOCUMENT = "document"
    """:obj:`str`: Messages with :attr:`telegram.Message.document`."""
    GAME = "game"
    """:obj:`str`: Messages with :attr:`telegram.Message.game`."""
    INVOICE = "invoice"
    """:obj:`str`: Messages with :attr:`telegram.Message.invoice`."""
    LOCATION = "location"
    """:obj:`str`: Messages with :attr:`telegram.Message.location`."""
    PAID_MEDIA = "paid_media"
    """:obj:`str`: Messages with :attr:`telegram.Message.paid_media`.

    .. versionadded:: 21.4
    """
    PASSPORT_DATA = "passport_data"
    """:obj:`str`: Messages with :attr:`telegram.Message.passport_data`."""
    PHOTO = "photo"
    """:obj:`str`: Messages with :attr:`telegram.Message.photo`."""
    POLL = "poll"
    """:obj:`str`: Messages with :attr:`telegram.Message.poll`."""
    STICKER = "sticker"
    """:obj:`str`: Messages with :attr:`telegram.Message.sticker`."""
    STORY = "story"
    """:obj:`str`: Messages with :attr:`telegram.Message.story`."""
    SUCCESSFUL_PAYMENT = "successful_payment"
    """:obj:`str`: Messages with :attr:`telegram.Message.successful_payment`."""
    VIDEO = "video"
    """:obj:`str`: Messages with :attr:`telegram.Message.video`."""
    VIDEO_NOTE = "video_note"
    """:obj:`str`: Messages with :attr:`telegram.Message.video_note`."""
    VOICE = "voice"
    """:obj:`str`: Messages with :attr:`telegram.Message.voice`."""
    VENUE = "venue"
    """:obj:`str`: Messages with :attr:`telegram.Message.venue`."""


class MessageEntityType(StringEnum):
    """This enum contains the available types of :class:`telegram.MessageEntity`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    BLOCKQUOTE = "blockquote"
    """:obj:`str`: Message entities representing a block quotation.

    .. versionadded:: 20.8
    """
    BOLD = "bold"
    """:obj:`str`: Message entities representing bold text."""
    BOT_COMMAND = "bot_command"
    """:obj:`str`: Message entities representing a bot command."""
    CASHTAG = "cashtag"
    """:obj:`str`: Message entities representing a cashtag."""
    CODE = "code"
    """:obj:`str`: Message entities representing monowidth string."""
    CUSTOM_EMOJI = "custom_emoji"
    """:obj:`str`: Message entities representing inline custom emoji stickers.

    .. versionadded:: 20.0
    """
    EMAIL = "email"
    """:obj:`str`: Message entities representing a email."""
    EXPANDABLE_BLOCKQUOTE = "expandable_blockquote"
    """:obj:`str`: Message entities representing collapsed-by-default block quotation.

    .. versionadded:: 21.3
    """
    HASHTAG = "hashtag"
    """:obj:`str`: Message entities representing a hashtag."""
    ITALIC = "italic"
    """:obj:`str`: Message entities representing italic text."""
    MENTION = "mention"
    """:obj:`str`: Message entities representing a mention."""
    PHONE_NUMBER = "phone_number"
    """:obj:`str`: Message entities representing a phone number."""
    PRE = "pre"
    """:obj:`str`: Message entities representing monowidth block."""
    SPOILER = "spoiler"
    """:obj:`str`: Message entities representing spoiler text."""
    STRIKETHROUGH = "strikethrough"
    """:obj:`str`: Message entities representing strikethrough text."""
    TEXT_LINK = "text_link"
    """:obj:`str`: Message entities representing clickable text URLs."""
    TEXT_MENTION = "text_mention"
    """:obj:`str`: Message entities representing text mention for users without usernames."""
    UNDERLINE = "underline"
    """:obj:`str`: Message entities representing underline text."""
    URL = "url"
    """:obj:`str`: Message entities representing a url."""


class MessageLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.Message`/
    :class:`telegram.InputTextMessageContent`/
    :meth:`telegram.Bot.send_message` & friends. The enum
    members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    # TODO add links to params?
    MAX_TEXT_LENGTH = 4096
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as:

    * :paramref:`~telegram.Game.text` parameter of :class:`telegram.Game`
    * :paramref:`~telegram.Message.text` parameter of :class:`telegram.Message`
    * :paramref:`~telegram.InputTextMessageContent.message_text` parameter of
      :class:`telegram.InputTextMessageContent`
    * :paramref:`~telegram.Bot.send_message.text` parameter of :meth:`telegram.Bot.send_message`
    * :paramref:`~telegram.Bot.edit_message_text.text` parameter of
      :meth:`telegram.Bot.edit_message_text`
    * :paramref:`~telegram.Bot.send_message_draft.text` parameter of
      :meth:`telegram.Bot.send_message_draft`
    """
    CAPTION_LENGTH = 1024
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as:

    * :paramref:`~telegram.Message.caption` parameter of :class:`telegram.Message`
    * :paramref:`~telegram.InputMedia.caption` parameter of :class:`telegram.InputMedia`
      and its subclasses
    * ``caption`` parameter of subclasses of :class:`telegram.InlineQueryResult`
    * ``caption`` parameter of :meth:`telegram.Bot.send_photo`, :meth:`telegram.Bot.send_audio`,
      :meth:`telegram.Bot.send_document`, :meth:`telegram.Bot.send_video`,
      :meth:`telegram.Bot.send_animation`, :meth:`telegram.Bot.send_voice`,
      :meth:`telegram.Bot.edit_message_caption`, :meth:`telegram.Bot.copy_message`
    """
    # constants above this line are tested
    MIN_TEXT_LENGTH = 1
    """:obj:`int`: Minimum number of characters in a :obj:`str` passed as:

    * :paramref:`~telegram.InputTextMessageContent.message_text` parameter of
      :class:`telegram.InputTextMessageContent`.
    * :paramref:`~telegram.Bot.edit_message_text.text` parameter of
      :meth:`telegram.Bot.edit_message_text`.
    * :paramref:`~telegram.Bot.send_message_draft.text` parameter of
      :meth:`telegram.Bot.send_message_draft`.
    """
    DEEP_LINK_LENGTH = 64
    """:obj:`int`: Maximum number of characters for a deep link."""
    # TODO this constant is not used anywhere
    MESSAGE_ENTITIES = 100
    """:obj:`int`: Maximum number of entities that can be displayed in a message. Further entities
    will simply be ignored by Telegram.

    Note:
        This value is undocumented and might be changed by Telegram.
    """


class MessageOriginType(StringEnum):
    """This enum contains the available types of :class:`telegram.MessageOrigin`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.8
    """

    __slots__ = ()

    USER = "user"
    """:obj:`str`: A :class:`telegram.MessageOrigin` who is sent by an user."""
    HIDDEN_USER = "hidden_user"
    """:obj:`str`: A :class:`telegram.MessageOrigin` who is sent by a hidden user."""
    CHAT = "chat"
    """:obj:`str`: A :class:`telegram.MessageOrigin` who is sent by a chat."""
    CHANNEL = "channel"
    """:obj:`str`: A :class:`telegram.MessageOrigin` who is sent by a channel."""


class MessageType(StringEnum):
    """This enum contains the available types of :class:`telegram.Message`. Here, a "type" means
    a kind of message that is visually distinct from other kinds of messages in the Telegram app.
    In particular, auxiliary attributes that can be present for multiple types of messages are
    not considered in this enumeration.

    The enum members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    # Make sure that all attachment type constants are also listed in the
    # MessageAttachmentType Enum! (Enums are not extendable)

    ANIMATION = "animation"
    """:obj:`str`: Messages with :attr:`telegram.Message.animation`."""
    AUDIO = "audio"
    """:obj:`str`: Messages with :attr:`telegram.Message.audio`."""
    BOOST_ADDED = "boost_added"
    """:obj:`str`: Messages with :attr:`telegram.Message.boost_added`.

    .. versionadded:: 21.0
    """
    BUSINESS_CONNECTION_ID = "business_connection_id"
    """:obj:`str`: Messages with :attr:`telegram.Message.business_connection_id`.

    .. versionadded:: 21.1
    """
    CHANNEL_CHAT_CREATED = "channel_chat_created"
    """:obj:`str`: Messages with :attr:`telegram.Message.channel_chat_created`."""
    CHAT_SHARED = "chat_shared"
    """:obj:`str`: Messages with :attr:`telegram.Message.chat_shared`.

    .. versionadded:: 20.8
    """
    CHAT_BACKGROUND_SET = "chat_background_set"
    """:obj:`str`: Messages with :attr:`telegram.Message.chat_background_set`.

    .. versionadded:: 21.2
    """
    CHECKLIST = "checklist"
    """:obj:`str`: Messages with :attr:`telegram.Message.checklist`.

    .. versionadded:: 22.3
    """
    CHECKLIST_TASKS_ADDED = "checklist_tasks_added"
    """:obj:`str`: Messages with :attr:`telegram.Message.checklist_tasks_added`.

    .. versionadded:: 22.3
    """
    CHECKLIST_TASKS_DONE = "checklist_tasks_done"
    """:obj:`str`: Messages with :attr:`telegram.Message.checklist_tasks_done`.

    .. versionadded:: 22.3
    """
    CONNECTED_WEBSITE = "connected_website"
    """:obj:`str`: Messages with :attr:`telegram.Message.connected_website`."""
    CONTACT = "contact"
    """:obj:`str`: Messages with :attr:`telegram.Message.contact`."""
    DELETE_CHAT_PHOTO = "delete_chat_photo"
    """:obj:`str`: Messages with :attr:`telegram.Message.delete_chat_photo`."""
    DICE = "dice"
    """:obj:`str`: Messages with :attr:`telegram.Message.dice`."""
    DIRECT_MESSAGE_PRICE_CHANGED = "direct_message_price_changed"
    """:obj:`str`: Messages with :attr:`telegram.Message.direct_message_price_changed`.

    .. versionadded:: 22.3
    """
    DOCUMENT = "document"
    """:obj:`str`: Messages with :attr:`telegram.Message.document`."""
    EFFECT_ID = "effect_id"
    """:obj:`str`: Messages with :attr:`telegram.Message.effect_id`.

    .. versionadded:: 21.3"""
    FORUM_TOPIC_CREATED = "forum_topic_created"
    """:obj:`str`: Messages with :attr:`telegram.Message.forum_topic_created`.

    .. versionadded:: 20.8
    """
    FORUM_TOPIC_CLOSED = "forum_topic_closed"
    """:obj:`str`: Messages with :attr:`telegram.Message.forum_topic_closed`.

    .. versionadded:: 20.8
    """
    FORUM_TOPIC_EDITED = "forum_topic_edited"
    """:obj:`str`: Messages with :attr:`telegram.Message.forum_topic_edited`.

    .. versionadded:: 20.8
    """
    FORUM_TOPIC_REOPENED = "forum_topic_reopened"
    """:obj:`str`: Messages with :attr:`telegram.Message.forum_topic_reopened`.

    .. versionadded:: 20.8
    """
    GAME = "game"
    """:obj:`str`: Messages with :attr:`telegram.Message.game`."""
    GENERAL_FORUM_TOPIC_HIDDEN = "general_forum_topic_hidden"
    """:obj:`str`: Messages with :attr:`telegram.Message.general_forum_topic_hidden`.

    .. versionadded:: 20.8
    """
    GENERAL_FORUM_TOPIC_UNHIDDEN = "general_forum_topic_unhidden"
    """:obj:`str`: Messages with :attr:`telegram.Message.general_forum_topic_unhidden`.

    .. versionadded:: 20.8
    """
    GIFT = "gift"
    """:obj:`str`: Messages with :attr:`telegram.Message.gift`.

    .. versionadded:: 22.1
    """
    GIFT_UPGRADE_SENT = "gift_upgrade_sent"
    """:obj:`str`: Messages with :attr:`telegram.Message.gift_upgrade_sent`.

    .. versionadded:: 22.6
    """
    GIVEAWAY = "giveaway"
    """:obj:`str`: Messages with :attr:`telegram.Message.giveaway`.

    .. versionadded:: 20.8
    """
    GIVEAWAY_CREATED = "giveaway_created"
    """:obj:`str`: Messages with :attr:`telegram.Message.giveaway_created`.

    .. versionadded:: 20.8
    """
    GIVEAWAY_WINNERS = "giveaway_winners"
    """:obj:`str`: Messages with :attr:`telegram.Message.giveaway_winners`.

    .. versionadded:: 20.8
    """
    GIVEAWAY_COMPLETED = "giveaway_completed"
    """:obj:`str`: Messages with :attr:`telegram.Message.giveaway_completed`.

    .. versionadded:: 20.8
    """
    GROUP_CHAT_CREATED = "group_chat_created"
    """:obj:`str`: Messages with :attr:`telegram.Message.group_chat_created`."""
    INVOICE = "invoice"
    """:obj:`str`: Messages with :attr:`telegram.Message.invoice`."""
    LEFT_CHAT_MEMBER = "left_chat_member"
    """:obj:`str`: Messages with :attr:`telegram.Message.left_chat_member`."""
    LOCATION = "location"
    """:obj:`str`: Messages with :attr:`telegram.Message.location`."""
    MESSAGE_AUTO_DELETE_TIMER_CHANGED = "message_auto_delete_timer_changed"
    """:obj:`str`: Messages with :attr:`telegram.Message.message_auto_delete_timer_changed`."""
    MIGRATE_TO_CHAT_ID = "migrate_to_chat_id"
    """:obj:`str`: Messages with :attr:`telegram.Message.migrate_to_chat_id`."""
    NEW_CHAT_MEMBERS = "new_chat_members"
    """:obj:`str`: Messages with :attr:`telegram.Message.new_chat_members`."""
    NEW_CHAT_TITLE = "new_chat_title"
    """:obj:`str`: Messages with :attr:`telegram.Message.new_chat_title`."""
    NEW_CHAT_PHOTO = "new_chat_photo"
    """:obj:`str`: Messages with :attr:`telegram.Message.new_chat_photo`."""
    PAID_MEDIA = "paid_media"
    """:obj:`str`: Messages with :attr:`telegram.Message.paid_media`.

    .. versionadded:: 21.4
    """
    PAID_MESSAGE_PRICE_CHANGED = "paid_message_price_changed"
    """:obj:`str`: Messages with :attr:`telegram.Message.paid_message_price_changed`.

    .. versionadded:: v22.2
    """
    SUGGESTED_POST_APPROVAL_FAILED = "suggested_post_approval_failed"
    """:obj:`str`: Messages with :attr:`telegram.Message.suggested_post_approval_failed`.

    .. versionadded:: 22.4
    """
    SUGGESTED_POST_APPROVED = "suggested_post_approved"
    """:obj:`str`: Messages with :attr:`telegram.Message.suggested_post_approved`.

    .. versionadded:: 22.4
    """
    SUGGESTED_POST_DECLINED = "suggested_post_declined"
    """:obj:`str`: Messages with :attr:`telegram.Message.suggested_post_declined`.

    .. versionadded:: 22.4
    """
    SUGGESTED_POST_INFO = "suggested_post_info"
    """:obj:`str`: Messages with :attr:`telegram.Message.suggested_post_info`.

    .. versionadded:: 22.4
    """
    SUGGESTED_POST_PAID = "suggested_post_paid"
    """:obj:`str`: Messages with :attr:`telegram.Message.suggested_post_paid`.

    .. versionadded:: 22.4
    """
    SUGGESTED_POST_REFUNDED = "suggested_post_refunded"
    """:obj:`str`: Messages with :attr:`telegram.Message.suggested_post_refunded`.

    .. versionadded:: 22.4
    """
    PASSPORT_DATA = "passport_data"
    """:obj:`str`: Messages with :attr:`telegram.Message.passport_data`."""
    PHOTO = "photo"
    """:obj:`str`: Messages with :attr:`telegram.Message.photo`."""
    PINNED_MESSAGE = "pinned_message"
    """:obj:`str`: Messages with :attr:`telegram.Message.pinned_message`."""
    POLL = "poll"
    """:obj:`str`: Messages with :attr:`telegram.Message.poll`."""
    PROXIMITY_ALERT_TRIGGERED = "proximity_alert_triggered"
    """:obj:`str`: Messages with :attr:`telegram.Message.proximity_alert_triggered`."""
    REFUNDED_PAYMENT = "refunded_payment"
    """:obj:`str`: Messages with :attr:`telegram.Message.refunded_payment`.

    .. versionadded:: 21.4
    """
    REPLY_TO_STORY = "reply_to_story"
    """:obj:`str`: Messages with :attr:`telegram.Message.reply_to_story`.

    .. versionadded:: 21.0
    """
    SENDER_BOOST_COUNT = "sender_boost_count"
    """:obj:`str`: Messages with :attr:`telegram.Message.sender_boost_count`.

    .. versionadded:: 21.0
    """
    SENDER_BUSINESS_BOT = "sender_business_bot"
    """:obj:`str`: Messages with :attr:`telegram.Message.sender_business_bot`.

    .. versionadded:: 21.1
    """
    STICKER = "sticker"
    """:obj:`str`: Messages with :attr:`telegram.Message.sticker`."""
    STORY = "story"
    """:obj:`str`: Messages with :attr:`telegram.Message.story`."""
    SUPERGROUP_CHAT_CREATED = "supergroup_chat_created"
    """:obj:`str`: Messages with :attr:`telegram.Message.supergroup_chat_created`."""
    SUCCESSFUL_PAYMENT = "successful_payment"
    """:obj:`str`: Messages with :attr:`telegram.Message.successful_payment`."""
    TEXT = "text"
    """:obj:`str`: Messages with :attr:`telegram.Message.text`."""
    UNIQUE_GIFT = "unique_gift"
    """:obj:`str`: Messages with :attr:`telegram.Message.unique_gift`.

    .. versionadded:: 22.1
    """
    USERS_SHARED = "users_shared"
    """:obj:`str`: Messages with :attr:`telegram.Message.users_shared`.

    .. versionadded:: 20.8
    """
    VENUE = "venue"
    """:obj:`str`: Messages with :attr:`telegram.Message.venue`."""
    VIDEO = "video"
    """:obj:`str`: Messages with :attr:`telegram.Message.video`."""
    VIDEO_CHAT_SCHEDULED = "video_chat_scheduled"
    """:obj:`str`: Messages with :attr:`telegram.Message.video_chat_scheduled`."""
    VIDEO_CHAT_STARTED = "video_chat_started"
    """:obj:`str`: Messages with :attr:`telegram.Message.video_chat_started`."""
    VIDEO_CHAT_ENDED = "video_chat_ended"
    """:obj:`str`: Messages with :attr:`telegram.Message.video_chat_ended`."""
    VIDEO_CHAT_PARTICIPANTS_INVITED = "video_chat_participants_invited"
    """:obj:`str`: Messages with :attr:`telegram.Message.video_chat_participants_invited`."""
    VIDEO_NOTE = "video_note"
    """:obj:`str`: Messages with :attr:`telegram.Message.video_note`."""
    VOICE = "voice"
    """:obj:`str`: Messages with :attr:`telegram.Message.voice`."""
    WEB_APP_DATA = "web_app_data"
    """:obj:`str`: Messages with :attr:`telegram.Message.web_app_data`.

    .. versionadded:: 20.8
    """
    WRITE_ACCESS_ALLOWED = "write_access_allowed"
    """:obj:`str`: Messages with :attr:`telegram.Message.write_access_allowed`.

    .. versionadded:: 20.8
    """


class Nanostar(FloatEnum):
    """This enum contains constants for ``nanostar_amount`` parameter of
    :class:`telegram.StarAmount`, :class:`telegram.StarTransaction`
    and :class:`telegram.AffiliateInfo`.
    The enum members of this enumeration are instances of :class:`float` and can be treated as
    such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    VALUE = 1 / 1000000000
    """:obj:`float`: The value of one nanostar as used in
    :paramref:`telegram.StarTransaction.nanostar_amount`
    parameter of :class:`telegram.StarTransaction`,
    :paramref:`telegram.StarAmount.nanostar_amount` parameter of :class:`telegram.StarAmount`
    and :paramref:`telegram.AffiliateInfo.nanostar_amount`
    parameter of :class:`telegram.AffiliateInfo`
    """


class NanostarLimit(IntEnum):
    """This enum contains limitations for ``nanostar_amount`` parameter of
    :class:`telegram.AffiliateInfo`, :class:`telegram.StarTransaction`
    and :class:`telegram.StarAmount`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    MIN_AMOUNT = -999999999
    """:obj:`int`: Minimum value allowed for :paramref:`~telegram.AffiliateInfo.nanostar_amount`
    parameter of :class:`telegram.AffiliateInfo`
    and :paramref:`~telegram.StarAmount.nanostar_amount`
    parameter of :class:`telegram.StarAmount`.
    """
    MAX_AMOUNT = 999999999
    """:obj:`int`: Maximum value allowed for :paramref:`~telegram.StarTransaction.nanostar_amount`
    parameter of :class:`telegram.StarTransaction`,
    :paramref:`~telegram.AffiliateInfo.nanostar_amount` parameter of
    :class:`telegram.AffiliateInfo` and :paramref:`~telegram.StarAmount.nanostar_amount`
    parameter of :class:`telegram.StarAmount`.
    """


class OwnedGiftType(StringEnum):
    """This enum contains the available types of :class:`telegram.OwnedGift`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    REGULAR = "regular"
    """:obj:`str`: a regular owned gift."""
    UNIQUE = "unique"
    """:obj:`str`: a unique owned gift."""


class PaidMediaType(StringEnum):
    """
    This enum contains the available types of :class:`telegram.PaidMedia`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 21.4
    """

    __slots__ = ()

    PREVIEW = "preview"
    """:obj:`str`: The type of :class:`telegram.PaidMediaPreview`."""
    VIDEO = "video"
    """:obj:`str`: The type of :class:`telegram.PaidMediaVideo`."""
    PHOTO = "photo"
    """:obj:`str`: The type of :class:`telegram.PaidMediaPhoto`."""


class PollingLimit(IntEnum):
    """This enum contains limitations for :paramref:`telegram.Bot.get_updates.limit`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_LIMIT = 1
    """:obj:`int`: Minimum value allowed for the :paramref:`~telegram.Bot.get_updates.limit`
    parameter of :meth:`telegram.Bot.get_updates`.
    """
    MAX_LIMIT = 100
    """:obj:`int`: Maximum value allowed for the :paramref:`~telegram.Bot.get_updates.limit`
    parameter of :meth:`telegram.Bot.get_updates`.
    """


class PremiumSubscription(IntEnum):
    """This enum contains limitations for :meth:`~telegram.Bot.gift_premium_subscription`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    MAX_TEXT_LENGTH = 128
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.Bot.gift_premium_subscription.text`
    parameter of :meth:`~telegram.Bot.gift_premium_subscription`.
    """
    MONTH_COUNT_THREE = 3
    """:obj:`int`: Possible value for
    :paramref:`~telegram.Bot.gift_premium_subscription.month_count` parameter
    of :meth:`~telegram.Bot.gift_premium_subscription`; number of months the Premium
    subscription will be active for.
    """
    MONTH_COUNT_SIX = 6
    """:obj:`int`: Possible value for
    :paramref:`~telegram.Bot.gift_premium_subscription.month_count` parameter
    of :meth:`~telegram.Bot.gift_premium_subscription`; number of months the Premium
    subscription will be active for.
    """
    MONTH_COUNT_TWELVE = 12
    """:obj:`int`: Possible value for
    :paramref:`~telegram.Bot.gift_premium_subscription.month_count` parameter
    of :meth:`~telegram.Bot.gift_premium_subscription`; number of months the Premium
    subscription will be active for.
    """
    STARS_THREE_MONTHS = 1000
    """:obj:`int`: Number of Telegram Stars to pay for a Premium subscription of
    :tg-const:`telegram.constants.PremiumSubscription.MONTH_COUNT_THREE` months period.
    Relevant for :paramref:`~telegram.Bot.gift_premium_subscription.star_count` parameter
    of :meth:`~telegram.Bot.gift_premium_subscription`.
    """
    STARS_SIX_MONTHS = 1500
    """:obj:`int`: Number of Telegram Stars to pay for a Premium subscription of
    :tg-const:`telegram.constants.PremiumSubscription.MONTH_COUNT_SIX` months period.
    Relevant for :paramref:`~telegram.Bot.gift_premium_subscription.star_count` parameter
    of :meth:`~telegram.Bot.gift_premium_subscription`.
    """
    STARS_TWELVE_MONTHS = 2500
    """:obj:`int`: Number of Telegram Stars to pay for a Premium subscription of
    :tg-const:`telegram.constants.PremiumSubscription.MONTH_COUNT_TWELVE` months period.
    Relevant for :paramref:`~telegram.Bot.gift_premium_subscription.star_count` parameter
    of :meth:`~telegram.Bot.gift_premium_subscription`.
    """


class ProfileAccentColor(Enum):
    """This enum contains the available accent colors for
    :class:`telegram.ChatFullInfo.profile_accent_color_id`.
    The members of this enum are named tuples with the following attributes:

    - ``identifier`` (:obj:`int`): The identifier of the accent color.
    - ``name`` (:obj:`str`): Optional. The name of the accent color.
    - ``light_colors`` (tuple[:obj:`str`]): Optional. The light colors of the accent color as HEX
      value.
    - ``dark_colors`` (tuple[:obj:`str`]): Optional. The dark colors of the accent color as HEX
      value.

    Since Telegram gives no exact specification for the accent colors, future accent colors might
    have a different data type.

    .. versionadded:: 20.8
    """

    __slots__ = ()

    COLOR_000 = _AccentColor(identifier=0, light_colors=(0xBA5650,), dark_colors=(0x9C4540,))
    """Accent color 0. This contains one light color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#BA5650;">
        </div>

    and one dark color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#9C4540;">
        </div>
    """
    COLOR_001 = _AccentColor(identifier=1, light_colors=(0xC27C3E,), dark_colors=(0x945E2C,))
    """Accent color 1. This contains one light color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#C27C3E;">
        </div>

    and one dark color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#945E2C;">
        </div>
    """
    COLOR_002 = _AccentColor(identifier=2, light_colors=(0x956AC8,), dark_colors=(0x715099,))
    """Accent color 2. This contains one light color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#956AC8;">
        </div>

    and one dark color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#715099;">
        </div>
    """
    COLOR_003 = _AccentColor(identifier=3, light_colors=(0x49A355,), dark_colors=(0x33713B,))
    """Accent color 3. This contains one light color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#49A355;">
        </div>

    and one dark color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#33713B;">
        </div>
    """
    COLOR_004 = _AccentColor(identifier=4, light_colors=(0x3E97AD,), dark_colors=(0x387E87,))
    """Accent color 4. This contains one light color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#3E97AD;">
        </div>

    and one dark color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#387E87;">
        </div>
    """
    COLOR_005 = _AccentColor(identifier=5, light_colors=(0x5A8FBB,), dark_colors=(0x477194,))
    """Accent color 5. This contains one light color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#5A8FBB;">
        </div>

    and one dark color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#477194;">
        </div>
    """
    COLOR_006 = _AccentColor(identifier=6, light_colors=(0xB85378,), dark_colors=(0x944763,))
    """Accent color 6. This contains one light color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#B85378;">
        </div>

    and one dark color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#944763;">
        </div>
    """
    COLOR_007 = _AccentColor(identifier=7, light_colors=(0x7F8B95,), dark_colors=(0x435261,))
    """Accent color 7. This contains one light color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#7F8B95;">
        </div>

    and one dark color

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#435261;">
        </div>
    """
    COLOR_008 = _AccentColor(
        identifier=8, light_colors=(0xC9565D, 0xD97C57), dark_colors=(0x994343, 0xAC583E)
    )
    """Accent color 8. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#C9565D;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#D97C57;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#994343;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#AC583E;">
        </div><br>
    """
    COLOR_009 = _AccentColor(
        identifier=9, light_colors=(0xCF7244, 0xCC9433), dark_colors=(0x8F552F, 0xA17232)
    )
    """Accent color 9. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#CF7244;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#CC9433;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#8F552F;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#A17232;">
        </div><br>
    """
    COLOR_010 = _AccentColor(
        identifier=10, light_colors=(0x9662D4, 0xB966B6), dark_colors=(0x634691, 0x9250A2)
    )
    """Accent color 10. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#9662D4;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#B966B6;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#634691;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#9250A2;">
        </div><br>
    """
    COLOR_011 = _AccentColor(
        identifier=11, light_colors=(0x3D9755, 0x89A650), dark_colors=(0x296A43, 0x5F8F44)
    )
    """Accent color 11. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#3D9755;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#89A650;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#296A43;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#5F8F44;">
        </div><br>
    """
    COLOR_012 = _AccentColor(
        identifier=12, light_colors=(0x3D95BA, 0x50AD98), dark_colors=(0x306C7C, 0x3E987E)
    )
    """Accent color 12. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#3D95BA;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#50AD98;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#306C7C;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#3E987E;">
        </div><br>
    """
    COLOR_013 = _AccentColor(
        identifier=13, light_colors=(0x538BC2, 0x4DA8BD), dark_colors=(0x38618C, 0x458BA1)
    )
    """Accent color 13. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#538BC2;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#4DA8BD;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#38618C;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#458BA1;">
        </div><br>
    """
    COLOR_014 = _AccentColor(
        identifier=14, light_colors=(0xB04F74, 0xD1666D), dark_colors=(0x884160, 0xA65259)
    )
    """Accent color 14. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#B04F74;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#D1666D;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color:#884160;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color:#A65259;">
        </div><br>
    """
    COLOR_015 = _AccentColor(
        identifier=15, light_colors=(0x637482, 0x7B8A97), dark_colors=(0x53606E, 0x384654)
    )
    """Accent color 15. This contains two light colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color: #637482;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color: #7B8A97;">
        </div><br>

    and two dark colors

    .. raw:: html

        <div style="height:15px; width:15px; display: inline-block; background-color: #53606E;">
        </div>
        <div style="height:15px; width:15px; display: inline-block; background-color: #384654;">
        </div><br>
    """


class ReplyLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.ForceReply`
    and :class:`telegram.ReplyKeyboardMarkup`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_INPUT_FIELD_PLACEHOLDER = 1
    """:obj:`int`: Minimum value allowed for
    :paramref:`~telegram.ForceReply.input_field_placeholder` parameter of
    :class:`telegram.ForceReply` and
    :paramref:`~telegram.ReplyKeyboardMarkup.input_field_placeholder` parameter of
    :class:`telegram.ReplyKeyboardMarkup`
    """
    MAX_INPUT_FIELD_PLACEHOLDER = 64
    """:obj:`int`: Maximum value allowed for
    :paramref:`~telegram.ForceReply.input_field_placeholder` parameter of
    :class:`telegram.ForceReply` and
    :paramref:`~telegram.ReplyKeyboardMarkup.input_field_placeholder` parameter of
    :class:`telegram.ReplyKeyboardMarkup`
    """


class RevenueWithdrawalStateType(StringEnum):
    """This enum contains the available types of :class:`telegram.RevenueWithdrawalState`.
    The enum members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 21.4
    """

    __slots__ = ()

    PENDING = "pending"
    """:obj:`str`: A withdrawal in progress."""
    SUCCEEDED = "succeeded"
    """:obj:`str`: A withdrawal succeeded."""
    FAILED = "failed"
    """:obj:`str`: A withdrawal failed and the transaction was refunded."""


class StarTransactionsLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.Bot.get_star_transactions` and
    :class:`telegram.StarTransaction`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 21.4

    .. versionremoved:: 22.3
        Removed deprecated attributes ``StarTransactionsLimit.NANOSTAR_MIN_AMOUNT``
        and ``StarTransactionsLimit.NANOSTAR_MAX_AMOUNT``. Please instead use
        :attr:`telegram.constants.NanostarLimit.MIN_AMOUNT`
        and :attr:`telegram.constants.NanostarLimit.MAX_AMOUNT`.
    """

    __slots__ = ()

    MIN_LIMIT = 1
    """:obj:`int`: Minimum value allowed for the
    :paramref:`~telegram.Bot.get_star_transactions.limit` parameter of
    :meth:`telegram.Bot.get_star_transactions`."""
    MAX_LIMIT = 100
    """:obj:`int`: Maximum value allowed for the
    :paramref:`~telegram.Bot.get_star_transactions.limit` parameter of
    :meth:`telegram.Bot.get_star_transactions`."""


class StickerFormat(StringEnum):
    """This enum contains the available formats of :class:`telegram.Sticker` in the set. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.2
    """

    __slots__ = ()

    STATIC = "static"
    """:obj:`str`: Static sticker."""
    ANIMATED = "animated"
    """:obj:`str`: Animated sticker."""
    VIDEO = "video"
    """:obj:`str`: Video sticker."""


class StickerLimit(IntEnum):
    """This enum contains limitations for various sticker methods, such as
    :meth:`telegram.Bot.create_new_sticker_set`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_NAME_AND_TITLE = 1
    """:obj:`int`: Minimum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.Bot.create_new_sticker_set.name` parameter or the
    :paramref:`~telegram.Bot.create_new_sticker_set.title` parameter of
    :meth:`telegram.Bot.create_new_sticker_set`.
    """
    MAX_NAME_AND_TITLE = 64
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.Bot.create_new_sticker_set.name` parameter or the
    :paramref:`~telegram.Bot.create_new_sticker_set.title` parameter of
    :meth:`telegram.Bot.create_new_sticker_set`.
    """
    MIN_STICKER_EMOJI = 1
    """:obj:`int`: Minimum number of emojis associated with a sticker, passed as the
    :paramref:`~telegram.Bot.setStickerEmojiList.emoji_list` parameter of
    :meth:`telegram.Bot.set_sticker_emoji_list`.

    .. versionadded:: 20.2
    """
    MAX_STICKER_EMOJI = 20
    """:obj:`int`: Maximum number of emojis associated with a sticker, passed as the
    :paramref:`~telegram.Bot.setStickerEmojiList.emoji_list` parameter of
    :meth:`telegram.Bot.set_sticker_emoji_list`.

    .. versionadded:: 20.2
    """
    MAX_SEARCH_KEYWORDS = 20
    """:obj:`int`: Maximum number of search keywords for a sticker, passed as the
    :paramref:`~telegram.Bot.set_sticker_keywords.keywords` parameter of
    :meth:`telegram.Bot.set_sticker_keywords`.

    .. versionadded:: 20.2
    """
    MAX_KEYWORD_LENGTH = 64
    """:obj:`int`: Maximum number of characters in a search keyword for a sticker, for each item in
    :paramref:`~telegram.Bot.set_sticker_keywords.keywords` sequence of
    :meth:`telegram.Bot.set_sticker_keywords`.

    .. versionadded:: 20.2
    """


class StickerSetLimit(IntEnum):
    """This enum contains limitations for various sticker set methods, such as
    :meth:`telegram.Bot.create_new_sticker_set` and :meth:`telegram.Bot.add_sticker_to_set`.

    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.2
    """

    __slots__ = ()

    MIN_INITIAL_STICKERS = 1
    """:obj:`int`: Minimum number of stickers needed to create a sticker set, passed as the
    :paramref:`~telegram.Bot.create_new_sticker_set.stickers` parameter of
    :meth:`telegram.Bot.create_new_sticker_set`.
    """
    MAX_INITIAL_STICKERS = 50
    """:obj:`int`: Maximum number of stickers allowed while creating a sticker set, passed as the
    :paramref:`~telegram.Bot.create_new_sticker_set.stickers` parameter of
    :meth:`telegram.Bot.create_new_sticker_set`.
    """
    MAX_EMOJI_STICKERS = 200
    """:obj:`int`: Maximum number of stickers allowed in an emoji sticker set, as given in
    :meth:`telegram.Bot.add_sticker_to_set`.
    """
    MAX_ANIMATED_STICKERS = 50
    """:obj:`int`: Maximum number of stickers allowed in an animated or video sticker set, as given
    in :meth:`telegram.Bot.add_sticker_to_set`.

    .. deprecated:: 21.1
        The animated sticker limit is now 120, the same as :attr:`MAX_STATIC_STICKERS`.
    """
    MAX_STATIC_STICKERS = 120
    """:obj:`int`: Maximum number of stickers allowed in a static sticker set, as given in
    :meth:`telegram.Bot.add_sticker_to_set`.
    """
    MAX_STATIC_THUMBNAIL_SIZE = 128
    """:obj:`int`: Maximum size of the thumbnail if it is a ``.WEBP`` or ``.PNG`` in kilobytes,
    as given in :meth:`telegram.Bot.set_sticker_set_thumbnail`."""
    MAX_ANIMATED_THUMBNAIL_SIZE = 32
    """:obj:`int`: Maximum size of the thumbnail if it is a ``.TGS`` or ``.WEBM`` in kilobytes,
    as given in :meth:`telegram.Bot.set_sticker_set_thumbnail`."""
    STATIC_THUMB_DIMENSIONS = 100
    """:obj:`int`: Exact height and width of the thumbnail if it is a ``.WEBP`` or ``.PNG`` in
    pixels, as given in :meth:`telegram.Bot.set_sticker_set_thumbnail`."""


class StickerType(StringEnum):
    """This enum contains the available types of :class:`telegram.Sticker`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    REGULAR = "regular"
    """:obj:`str`: Regular sticker."""
    MASK = "mask"
    """:obj:`str`: Mask sticker."""
    CUSTOM_EMOJI = "custom_emoji"
    """:obj:`str`: Custom emoji sticker."""


class StoryAreaPositionLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.StoryAreaPosition`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    MAX_ROTATION_ANGLE = 360
    """:obj:`int`: Maximum value allowed for:
        :paramref:`~telegram.StoryAreaPosition.rotation_angle` parameter of
        :class:`telegram.StoryAreaPosition`
    """


class StoryAreaTypeLimit(IntEnum):
    """This enum contains limitations for subclasses of :class:`telegram.StoryAreaType`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    MAX_LOCATION_AREAS = 10
    """:obj:`int`: Maximum number of location areas that a story can have.
    """
    MAX_SUGGESTED_REACTION_AREAS = 5
    """:obj:`int`: Maximum number of suggested reaction areas that a story can have.
    """
    MAX_LINK_AREAS = 3
    """:obj:`int`: Maximum number of link areas that a story can have.
    """
    MAX_WEATHER_AREAS = 3
    """:obj:`int`: Maximum number of weather areas that a story can have.
    """
    MAX_UNIQUE_GIFT_AREAS = 1
    """:obj:`int`: Maximum number of unique gift areas that a story can have.
    """


class StoryAreaTypeType(StringEnum):
    """This enum contains the available types of :class:`telegram.StoryAreaType`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    LOCATION = "location"
    """:obj:`str`: Type of :class:`telegram.StoryAreaTypeLocation`."""
    SUGGESTED_REACTION = "suggested_reaction"
    """:obj:`str`: Type of :class:`telegram.StoryAreaTypeSuggestedReaction`."""
    LINK = "link"
    """:obj:`str`: Type of :class:`telegram.StoryAreaTypeLink`."""
    WEATHER = "weather"
    """:obj:`str`: Type of :class:`telegram.StoryAreaTypeWeather`."""
    UNIQUE_GIFT = "unique_gift"
    """:obj:`str`: Type of :class:`telegram.StoryAreaTypeUniqueGift`."""


class StoryLimit(IntEnum):
    """This enum contains limitations for :meth:`~telegram.Bot.post_story` and
    :meth:`~telegram.Bot.edit_story`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    CAPTION_LENGTH = 2048
    """:obj:`int`: Maximum number of characters in :paramref:`telegram.Bot.post_story.caption`
    parameter of :meth:`telegram.Bot.post_story` and :paramref:`telegram.Bot.edit_story.caption` of
    :meth:`telegram.Bot.edit_story`.
    """
    ACTIVITY_SIX_HOURS = 6 * 3600
    """:obj:`int`: Possible value for :paramref:`~telegram.Bot.post_story.active_period`` parameter
    of :meth:`telegram.Bot.post_story`."""
    ACTIVITY_TWELVE_HOURS = 12 * 3600
    """:obj:`int`: Possible value for :paramref:`~telegram.Bot.post_story.active_period`` parameter
    of :meth:`telegram.Bot.post_story`."""
    ACTIVITY_ONE_DAY = 86400
    """:obj:`int`: Possible value for :paramref:`~telegram.Bot.post_story.active_period`` parameter
    of :meth:`telegram.Bot.post_story`."""
    ACTIVITY_TWO_DAYS = 2 * 86400
    """:obj:`int`: Possible value for :paramref:`~telegram.Bot.post_story.active_period`` parameter
    of :meth:`telegram.Bot.post_story`."""


class SuggestedPost(IntEnum):
    """This enum contains limitations for :class:`telegram.SuggestedPostPrice`\
/:class:`telegram.SuggestedPostParameters`/:meth:`telegram.Bot.decline_suggested_post`. The enum
    members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 22.4
    """

    __slots__ = ()

    MIN_PRICE_STARS = 5
    """:obj:`int`: Minimum number of Telegram Stars in
    :paramref:`~telegram.SuggestedPostPrice.amount`
    parameter of :class:`telegram.SuggestedPostPrice`.
    """
    MAX_PRICE_STARS = 100_000
    """:obj:`int`: Maximum number of Telegram Stars in
    :paramref:`~telegram.SuggestedPostPrice.amount`
    parameter of :class:`telegram.SuggestedPostPrice`.
    """
    MIN_PRICE_NANOTONCOINS = 10_000_000
    """:obj:`int`: Minimum number of nanotoncoins in
    :paramref:`~telegram.SuggestedPostPrice.amount`
    parameter of :class:`telegram.SuggestedPostPrice`.
    """
    MAX_PRICE_NANOTONCOINS = 10_000_000_000_000
    """:obj:`int`: Maximum number of nanotoncoins in
    :paramref:`~telegram.SuggestedPostPrice.amount`
    parameter of :class:`telegram.SuggestedPostPrice`.
    """
    MIN_SEND_DATE = 300
    """:obj:`int`: Minimum number of seconds in the future for
    the :paramref:`~telegram.SuggestedPostParameters.send_date` parameter of
    :class:`telegram.SuggestedPostParameters`."""
    MAX_SEND_DATE = 2_678_400
    """:obj:`int`: Maximum number of seconds in the future for
    the :paramref:`~telegram.SuggestedPostParameters.send_date` parameter of
    :class:`telegram.SuggestedPostParameters`."""
    MAX_COMMENT_LENGTH = 128
    """:obj:`int`: Maximum number of characters in the
    :paramref:`telegram.Bot.decline_suggested_post.comment` parameter.
    """


class SuggestedPostRefunded(StringEnum):
    """This enum contains available refund reasons for :class:`telegram.SuggestedPostRefunded`.
    The enum members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 22.4
    """

    __slots__ = ()

    POST_DELETED = "post_deleted"
    """:obj:`str`: The post was deleted within 24 hours of being posted or removed from
    scheduled messages without being posted."""
    PAYMENT_REFUNDED = "payment_refunded"
    """:obj:`str`: The payer refunded their payment."""


class TransactionPartnerType(StringEnum):
    """This enum contains the available types of :class:`telegram.TransactionPartner`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 21.4
    """

    __slots__ = ()

    AFFILIATE_PROGRAM = "affiliate_program"
    """:obj:`str`: Transaction with Affiliate Program.

    .. versionadded:: 21.9
    """
    CHAT = "chat"
    """:obj:`str`: Transaction with a chat.

    .. versionadded:: 21.11
    """
    FRAGMENT = "fragment"
    """:obj:`str`: Withdrawal transaction with Fragment."""
    OTHER = "other"
    """:obj:`str`: Transaction with unknown source or recipient."""
    TELEGRAM_ADS = "telegram_ads"
    """:obj:`str`: Transaction with Telegram Ads."""
    TELEGRAM_API = "telegram_api"
    """:obj:`str`: Transaction with with payment for
    `paid broadcasting <https://core.telegram.org/bots/api#paid-broadcasts>`_.

    .. versionadded:: 21.7
    """
    USER = "user"
    """:obj:`str`: Transaction with a user."""


class TransactionPartnerUser(StringEnum):
    """This enum contains constants for :class:`telegram.TransactionPartnerUser`.
    The enum members of this enumeration are instances of :class:`str` and can be treated as
    such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    INVOICE_PAYMENT = "invoice_payment"
    """:obj:`str`: Possible value for
    :paramref:`telegram.TransactionPartnerUser.transaction_type`.
    """
    PAID_MEDIA_PAYMENT = "paid_media_payment"
    """:obj:`str`: Possible value for
    :paramref:`telegram.TransactionPartnerUser.transaction_type`.
    """
    GIFT_PURCHASE = "gift_purchase"
    """:obj:`str`: Possible value for
    :paramref:`telegram.TransactionPartnerUser.transaction_type`.
    """
    PREMIUM_PURCHASE = "premium_purchase"
    """:obj:`str`: Possible value for
    :paramref:`telegram.TransactionPartnerUser.transaction_type`.
    """
    BUSINESS_ACCOUNT_TRANSFER = "business_account_transfer"
    """:obj:`str`: Possible value for
    :paramref:`telegram.TransactionPartnerUser.transaction_type`.
    """


class ParseMode(StringEnum):
    """This enum contains the available parse modes. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MARKDOWN = "Markdown"
    """:obj:`str`: Markdown parse mode.

    Note:
        :attr:`MARKDOWN` is a legacy mode, retained by Telegram for backward compatibility.
        You should use :attr:`MARKDOWN_V2` instead.
    """
    MARKDOWN_V2 = "MarkdownV2"
    """:obj:`str`: Markdown parse mode version 2."""
    HTML = "HTML"
    """:obj:`str`: HTML parse mode."""


class PollLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.Poll`/:class:`telegram.PollOption`/
    :meth:`telegram.Bot.send_poll`. The enum
    members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_QUESTION_LENGTH = 1
    """:obj:`int`: Minimum value allowed for the :paramref:`~telegram.Poll.question`
    parameter of :class:`telegram.Poll` and the :paramref:`~telegram.Bot.send_poll.question`
    parameter of :meth:`telegram.Bot.send_poll`.
    """
    MAX_QUESTION_LENGTH = 300
    """:obj:`int`: Maximum value allowed for the :paramref:`~telegram.Poll.question`
    parameter of :class:`telegram.Poll` and the :paramref:`~telegram.Bot.send_poll.question`
    parameter of :meth:`telegram.Bot.send_poll`.
    """
    MIN_OPTION_LENGTH = 1
    """:obj:`int`: Minimum length of each :obj:`str` passed in a :obj:`list`
    to the :paramref:`~telegram.Bot.send_poll.options` parameter of
    :meth:`telegram.Bot.send_poll`.
    """
    MAX_OPTION_LENGTH = 100
    """:obj:`int`: Maximum length of each :obj:`str` passed in a :obj:`list`
    to the :paramref:`~telegram.Bot.send_poll.options` parameter of
    :meth:`telegram.Bot.send_poll`.
    """
    MIN_OPTION_NUMBER = 2
    """:obj:`int`: Minimum number of strings passed in a :obj:`list`
    to the :paramref:`~telegram.Bot.send_poll.options` parameter of
    :meth:`telegram.Bot.send_poll`.
    """
    MAX_OPTION_NUMBER = 12
    """:obj:`int`: Maximum number of strings passed in a :obj:`list`
    to the :paramref:`~telegram.Bot.send_poll.options` parameter of
    :meth:`telegram.Bot.send_poll`.

    .. versionchanged:: 22.3
        This value was changed from ``10`` to ``12`` in accordance to Bot API 9.1.
    """
    MAX_EXPLANATION_LENGTH = 200
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.Poll.explanation` parameter of :class:`telegram.Poll` and the
    :paramref:`~telegram.Bot.send_poll.explanation` parameter of :meth:`telegram.Bot.send_poll`.
    """
    MAX_EXPLANATION_LINE_FEEDS = 2
    """:obj:`int`: Maximum number of line feeds in a :obj:`str` passed as the
    :paramref:`~telegram.Bot.send_poll.explanation` parameter of :meth:`telegram.Bot.send_poll`
    after entities parsing.
    """
    MIN_OPEN_PERIOD = 5
    """:obj:`int`: Minimum value allowed for the
    :paramref:`~telegram.Bot.send_poll.open_period` parameter of :meth:`telegram.Bot.send_poll`.
    Also used in the :paramref:`~telegram.Bot.send_poll.close_date` parameter of
    :meth:`telegram.Bot.send_poll`.
    """
    MAX_OPEN_PERIOD = 600
    """:obj:`int`: Maximum value allowed for the
    :paramref:`~telegram.Bot.send_poll.open_period` parameter of :meth:`telegram.Bot.send_poll`.
    Also used in the :paramref:`~telegram.Bot.send_poll.close_date` parameter of
    :meth:`telegram.Bot.send_poll`.
    """


class PollType(StringEnum):
    """This enum contains the available types for :class:`telegram.Poll`/
    :meth:`telegram.Bot.send_poll`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    REGULAR = "regular"
    """:obj:`str`: regular polls."""
    QUIZ = "quiz"
    """:obj:`str`: quiz polls."""


class UniqueGiftInfoOrigin(StringEnum):
    """This enum contains the available origins for :class:`telegram.UniqueGiftInfo`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 22.1
    """

    __slots__ = ()

    GIFTED_UPGRADE = "gifted_upgrade"
    """:obj:`str` upgrades purchased after the gift was sent

    .. versionadded:: 22.6
    """
    OFFER = "OFFER"
    """:obj:`str` gift bought or sold through gift purchase offers

    .. versionadded:: 22.6
    """
    RESALE = "resale"
    """:obj:`str` gift bought from other users

    .. versionadded:: 22.3
    """
    TRANSFER = "transfer"
    """:obj:`str` gift transfered"""
    UPGRADE = "upgrade"
    """:obj:`str` gift upgraded"""


class UpdateType(StringEnum):
    """This enum contains the available types of :class:`telegram.Update`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MESSAGE = "message"
    """:obj:`str`: Updates with :attr:`telegram.Update.message`."""
    EDITED_MESSAGE = "edited_message"
    """:obj:`str`: Updates with :attr:`telegram.Update.edited_message`."""
    CHANNEL_POST = "channel_post"
    """:obj:`str`: Updates with :attr:`telegram.Update.channel_post`."""
    EDITED_CHANNEL_POST = "edited_channel_post"
    """:obj:`str`: Updates with :attr:`telegram.Update.edited_channel_post`."""
    INLINE_QUERY = "inline_query"
    """:obj:`str`: Updates with :attr:`telegram.Update.inline_query`."""
    CHOSEN_INLINE_RESULT = "chosen_inline_result"
    """:obj:`str`: Updates with :attr:`telegram.Update.chosen_inline_result`."""
    CALLBACK_QUERY = "callback_query"
    """:obj:`str`: Updates with :attr:`telegram.Update.callback_query`."""
    SHIPPING_QUERY = "shipping_query"
    """:obj:`str`: Updates with :attr:`telegram.Update.shipping_query`."""
    PRE_CHECKOUT_QUERY = "pre_checkout_query"
    """:obj:`str`: Updates with :attr:`telegram.Update.pre_checkout_query`."""
    POLL = "poll"
    """:obj:`str`: Updates with :attr:`telegram.Update.poll`."""
    POLL_ANSWER = "poll_answer"
    """:obj:`str`: Updates with :attr:`telegram.Update.poll_answer`."""
    MY_CHAT_MEMBER = "my_chat_member"
    """:obj:`str`: Updates with :attr:`telegram.Update.my_chat_member`."""
    CHAT_MEMBER = "chat_member"
    """:obj:`str`: Updates with :attr:`telegram.Update.chat_member`."""
    CHAT_JOIN_REQUEST = "chat_join_request"
    """:obj:`str`: Updates with :attr:`telegram.Update.chat_join_request`."""
    CHAT_BOOST = "chat_boost"
    """:obj:`str`: Updates with :attr:`telegram.Update.chat_boost`.

    .. versionadded:: 20.8
    """
    REMOVED_CHAT_BOOST = "removed_chat_boost"
    """:obj:`str`: Updates with :attr:`telegram.Update.removed_chat_boost`.

    .. versionadded:: 20.8
    """
    MESSAGE_REACTION = "message_reaction"
    """:obj:`str`: Updates with :attr:`telegram.Update.message_reaction`.

    .. versionadded:: 20.8
    """
    MESSAGE_REACTION_COUNT = "message_reaction_count"
    """:obj:`str`: Updates with :attr:`telegram.Update.message_reaction_count`.

    .. versionadded:: 20.8
    """
    BUSINESS_CONNECTION = "business_connection"
    """:obj:`str`: Updates with :attr:`telegram.Update.business_connection`.

    .. versionadded:: 21.1
    """
    BUSINESS_MESSAGE = "business_message"
    """:obj:`str`: Updates with :attr:`telegram.Update.business_message`.

    .. versionadded:: 21.1
    """
    EDITED_BUSINESS_MESSAGE = "edited_business_message"
    """:obj:`str`: Updates with :attr:`telegram.Update.edited_business_message`.

    .. versionadded:: 21.1
    """
    DELETED_BUSINESS_MESSAGES = "deleted_business_messages"
    """:obj:`str`: Updates with :attr:`telegram.Update.deleted_business_messages`.

    .. versionadded:: 21.1
    """
    PURCHASED_PAID_MEDIA = "purchased_paid_media"
    """:obj:`str`: Updates with :attr:`telegram.Update.purchased_paid_media`.

    .. versionadded:: 21.6
    """


class InvoiceLimit(IntEnum):
    """This enum contains limitations for :class:`telegram.InputInvoiceMessageContent`,
    :meth:`telegram.Bot.send_invoice`, and :meth:`telegram.Bot.create_invoice_link`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_TITLE_LENGTH = 1
    """:obj:`int`: Minimum number of characters in a :obj:`str` passed as:

    * :paramref:`~telegram.InputInvoiceMessageContent.title` parameter of
      :class:`telegram.InputInvoiceMessageContent`
    * :paramref:`~telegram.Bot.send_invoice.title` parameter of
      :meth:`telegram.Bot.send_invoice`.
    * :paramref:`~telegram.Bot.create_invoice_link.title` parameter of
      :meth:`telegram.Bot.create_invoice_link`.
    """
    MAX_TITLE_LENGTH = 32
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as:

    * :paramref:`~telegram.InputInvoiceMessageContent.title` parameter of
      :class:`telegram.InputInvoiceMessageContent`
    * :paramref:`~telegram.Bot.send_invoice.title` parameter of
      :meth:`telegram.Bot.send_invoice`.
    * :paramref:`~telegram.Bot.create_invoice_link.title` parameter of
      :meth:`telegram.Bot.create_invoice_link`.
    """
    MIN_DESCRIPTION_LENGTH = 1
    """:obj:`int`: Minimum number of characters in a :obj:`str` passed as:

    * :paramref:`~telegram.InputInvoiceMessageContent.description` parameter of
      :class:`telegram.InputInvoiceMessageContent`
    * :paramref:`~telegram.Bot.send_invoice.description` parameter of
      :meth:`telegram.Bot.send_invoice`.
    * :paramref:`~telegram.Bot.create_invoice_link.description` parameter of
      :meth:`telegram.Bot.create_invoice_link`.
    """
    MAX_DESCRIPTION_LENGTH = 255
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as:

    * :paramref:`~telegram.InputInvoiceMessageContent.description` parameter of
      :class:`telegram.InputInvoiceMessageContent`
    * :paramref:`~telegram.Bot.send_invoice.description` parameter of
      :meth:`telegram.Bot.send_invoice`.
    * :paramref:`~telegram.Bot.create_invoice_link.description` parameter of
      :meth:`telegram.Bot.create_invoice_link`.
    """
    MIN_PAYLOAD_LENGTH = 1
    """:obj:`int`: Minimum amount of bytes in a :obj:`str` passed as:

    * :paramref:`~telegram.InputInvoiceMessageContent.payload` parameter of
      :class:`telegram.InputInvoiceMessageContent`
    * :paramref:`~telegram.Bot.send_invoice.payload` parameter of
      :meth:`telegram.Bot.send_invoice`.
    * :paramref:`~telegram.Bot.create_invoice_link.payload` parameter of
      :meth:`telegram.Bot.create_invoice_link`.
    """
    MAX_PAYLOAD_LENGTH = 128
    """:obj:`int`: Maximum amount of bytes in a :obj:`str` passed as:

    * :paramref:`~telegram.InputInvoiceMessageContent.payload` parameter of
      :class:`telegram.InputInvoiceMessageContent`
    * :paramref:`~telegram.Bot.send_invoice.payload` parameter of
      :meth:`telegram.Bot.send_invoice`.
    * :paramref:`~telegram.Bot.create_invoice_link.payload` parameter of
      :meth:`telegram.Bot.create_invoice_link`.
    * :paramref:`~telegram.Bot.send_paid_media.payload` parameter of
      :meth:`telegram.Bot.send_paid_media`.
    """
    MAX_TIP_AMOUNTS = 4
    """:obj:`int`: Maximum length of a :obj:`Sequence` passed as:

    * :paramref:`~telegram.Bot.send_invoice.suggested_tip_amounts` parameter of
      :meth:`telegram.Bot.send_invoice`.
    * :paramref:`~telegram.Bot.create_invoice_link.suggested_tip_amounts` parameter of
      :meth:`telegram.Bot.create_invoice_link`.
    """
    MIN_STAR_COUNT = 1
    """:obj:`int`: Minimum amount of starts that must be paid to buy access to a paid media
    passed as :paramref:`~telegram.Bot.send_paid_media.star_count` parameter of
    :meth:`telegram.Bot.send_paid_media`.

    .. versionadded:: 21.6
    """
    MAX_STAR_COUNT = 25000
    """:obj:`int`: Maximum amount of starts that must be paid to buy access to a paid media
    passed as :paramref:`~telegram.Bot.send_paid_media.star_count` parameter of
    :meth:`telegram.Bot.send_paid_media`.

    .. versionadded:: 21.6
    .. versionchanged:: 22.1
        Bot API 9.0 changed the value to 10000.
    .. versionchanged:: 22.6
        Bot API 9.3 changed the value to 25000.
    """
    SUBSCRIPTION_PERIOD = dtm.timedelta(days=30).total_seconds()
    """:obj:`int`: The period of time for which the subscription is active before
    the next payment, passed as :paramref:`~telegram.Bot.create_invoice_link.subscription_period`
    parameter of :meth:`telegram.Bot.create_invoice_link`.

    .. versionadded:: 21.8
    """
    SUBSCRIPTION_MAX_PRICE = 10000
    """:obj:`int`: The maximum price of a subscription created wtih
    :meth:`telegram.Bot.create_invoice_link`.

    .. versionadded:: 21.9
    .. versionchanged:: 22.1
        Bot API 9.0 changed the value to 10000.
    """


class UserProfilePhotosLimit(IntEnum):
    """This enum contains limitations for :paramref:`telegram.Bot.get_user_profile_photos.limit`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_LIMIT = 1
    """:obj:`int`: Minimum value allowed for
    :paramref:`~telegram.Bot.get_user_profile_photos.limit` parameter of
    :meth:`telegram.Bot.get_user_profile_photos`.
    """
    MAX_LIMIT = 100
    """:obj:`int`: Maximum value allowed for
    :paramref:`~telegram.Bot.get_user_profile_photos.limit` parameter of
    :meth:`telegram.Bot.get_user_profile_photos`.
    """


class WebhookLimit(IntEnum):
    """This enum contains limitations for :paramref:`telegram.Bot.set_webhook.max_connections` and
    :paramref:`telegram.Bot.set_webhook.secret_token`. The enum members of this enumeration are
    instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_CONNECTIONS_LIMIT = 1
    """:obj:`int`: Minimum value allowed for the
    :paramref:`~telegram.Bot.set_webhook.max_connections` parameter of
    :meth:`telegram.Bot.set_webhook`.
    """
    MAX_CONNECTIONS_LIMIT = 100
    """:obj:`int`: Maximum value allowed for the
    :paramref:`~telegram.Bot.set_webhook.max_connections` parameter of
    :meth:`telegram.Bot.set_webhook`.
    """
    MIN_SECRET_TOKEN_LENGTH = 1
    """:obj:`int`: Minimum length of the secret token for the
    :paramref:`~telegram.Bot.set_webhook.secret_token` parameter of
    :meth:`telegram.Bot.set_webhook`.
    """
    MAX_SECRET_TOKEN_LENGTH = 256
    """:obj:`int`: Maximum length of the secret token for the
    :paramref:`~telegram.Bot.set_webhook.secret_token` parameter of
    :meth:`telegram.Bot.set_webhook`.
    """


class ForumTopicLimit(IntEnum):
    """This enum contains limitations for :paramref:`telegram.Bot.create_forum_topic.name` and
    :paramref:`telegram.Bot.edit_forum_topic.name`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 20.0
    """

    __slots__ = ()

    MIN_NAME_LENGTH = 1
    """:obj:`int`: Minimum length of a :obj:`str` passed as:

    * :paramref:`~telegram.Bot.create_forum_topic.name` parameter of
      :meth:`telegram.Bot.create_forum_topic`
    * :paramref:`~telegram.Bot.edit_forum_topic.name` parameter of
      :meth:`telegram.Bot.edit_forum_topic`
    * :paramref:`~telegram.Bot.edit_general_forum_topic.name` parameter of
      :meth:`telegram.Bot.edit_general_forum_topic`
    """
    MAX_NAME_LENGTH = 128
    """:obj:`int`: Maximum length of a :obj:`str` passed as:

    * :paramref:`~telegram.Bot.create_forum_topic.name` parameter of
      :meth:`telegram.Bot.create_forum_topic`
    * :paramref:`~telegram.Bot.edit_forum_topic.name` parameter of
      :meth:`telegram.Bot.edit_forum_topic`
    * :paramref:`~telegram.Bot.edit_general_forum_topic.name` parameter of
      :meth:`telegram.Bot.edit_general_forum_topic`
    """


class SuggestedPostInfoState(StringEnum):
    """This enum contains the available states of :attr:`telegram.SuggestedPostInfo.state`.
    The enum members of this enumeration are instances
    of :class:`str` and can be treated as such.

    .. versionadded:: 22.4
    """

    __slots__ = ()

    PENDING = "pending"
    """:obj:`str`: Suggested post is pending."""
    APPROVED = "approved"
    """:obj:`str`: Suggested post was approved."""
    DECLINED = "declined"
    """:obj:`str`: Suggested post was declined.
    """


class ReactionType(StringEnum):
    """This enum contains the available types of :class:`telegram.ReactionType`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.8
    """

    __slots__ = ()

    EMOJI = "emoji"
    """:obj:`str`: A :class:`telegram.ReactionType` with a normal emoji."""
    CUSTOM_EMOJI = "custom_emoji"
    """:obj:`str`: A :class:`telegram.ReactionType` with a custom emoji."""
    PAID = "paid"
    """:obj:`str`: A :class:`telegram.ReactionType` with a paid reaction.

    .. versionadded:: 21.5
    """


class ReactionEmoji(StringEnum):
    """This enum contains the available emojis of :class:`telegram.ReactionTypeEmoji`. The enum
    members of this enumeration are instances of :class:`str` and can be treated as such.

    .. versionadded:: 20.8
    """

    __slots__ = ()

    THUMBS_UP = "👍"
    """:obj:`str`: Thumbs Up"""
    THUMBS_DOWN = "👎"
    """:obj:`str`: Thumbs Down"""
    RED_HEART = "❤"
    """:obj:`str`: Red Heart"""
    FIRE = "🔥"
    """:obj:`str`: Fire"""
    SMILING_FACE_WITH_HEARTS = "🥰"
    """:obj:`str`: Smiling Face with Hearts"""
    CLAPPING_HANDS = "👏"
    """:obj:`str`: Clapping Hands"""
    GRINNING_FACE_WITH_SMILING_EYES = "😁"
    """:obj:`str`: Grinning face with smiling eyes"""
    THINKING_FACE = "🤔"
    """:obj:`str`: Thinking face"""
    SHOCKED_FACE_WITH_EXPLODING_HEAD = "🤯"
    """:obj:`str`: Shocked face with exploding head"""
    FACE_SCREAMING_IN_FEAR = "😱"
    """:obj:`str`: Face screaming in fear"""
    SERIOUS_FACE_WITH_SYMBOLS_COVERING_MOUTH = "🤬"
    """:obj:`str`: Serious face with symbols covering mouth"""
    CRYING_FACE = "😢"
    """:obj:`str`: Crying face"""
    PARTY_POPPER = "🎉"
    """:obj:`str`: Party popper"""
    GRINNING_FACE_WITH_STAR_EYES = "🤩"
    """:obj:`str`: Grinning face with star eyes"""
    FACE_WITH_OPEN_MOUTH_VOMITING = "🤮"
    """:obj:`str`: Face with open mouth vomiting"""
    PILE_OF_POO = "💩"
    """:obj:`str`: Pile of poo"""
    PERSON_WITH_FOLDED_HANDS = "🙏"
    """:obj:`str`: Person with folded hands"""
    OK_HAND_SIGN = "👌"
    """:obj:`str`: Ok hand sign"""
    DOVE_OF_PEACE = "🕊"
    """:obj:`str`: Dove of peace"""
    CLOWN_FACE = "🤡"
    """:obj:`str`: Clown face"""
    YAWNING_FACE = "🥱"
    """:obj:`str`: Yawning face"""
    FACE_WITH_UNEVEN_EYES_AND_WAVY_MOUTH = "🥴"
    """:obj:`str`: Face with uneven eyes and wavy mouth"""
    SMILING_FACE_WITH_HEART_SHAPED_EYES = "😍"
    """:obj:`str`: Smiling face with heart-shaped eyes"""
    SPOUTING_WHALE = "🐳"
    """:obj:`str`: Spouting whale"""
    HEART_ON_FIRE = "❤️‍🔥"
    """:obj:`str`: Heart on fire"""
    NEW_MOON_WITH_FACE = "🌚"
    """:obj:`str`: New moon with face"""
    HOT_DOG = "🌭"
    """:obj:`str`: Hot dog"""
    HUNDRED_POINTS_SYMBOL = "💯"
    """:obj:`str`: Hundred points symbol"""
    ROLLING_ON_THE_FLOOR_LAUGHING = "🤣"
    """:obj:`str`: Rolling on the floor laughing"""
    HIGH_VOLTAGE_SIGN = "⚡"
    """:obj:`str`: High voltage sign"""
    BANANA = "🍌"
    """:obj:`str`: Banana"""
    TROPHY = "🏆"
    """:obj:`str`: Trophy"""
    BROKEN_HEART = "💔"
    """:obj:`str`: Broken heart"""
    FACE_WITH_ONE_EYEBROW_RAISED = "🤨"
    """:obj:`str`: Face with one eyebrow raised"""
    NEUTRAL_FACE = "😐"
    """:obj:`str`: Neutral face"""
    STRAWBERRY = "🍓"
    """:obj:`str`: Strawberry"""
    BOTTLE_WITH_POPPING_CORK = "🍾"
    """:obj:`str`: Bottle with popping cork"""
    KISS_MARK = "💋"
    """:obj:`str`: Kiss mark"""
    REVERSED_HAND_WITH_MIDDLE_FINGER_EXTENDED = "🖕"
    """:obj:`str`: Reversed hand with middle finger extended"""
    SMILING_FACE_WITH_HORNS = "😈"
    """:obj:`str`: Smiling face with horns"""
    SLEEPING_FACE = "😴"
    """:obj:`str`: Sleeping face"""
    LOUDLY_CRYING_FACE = "😭"
    """:obj:`str`: Loudly crying face"""
    NERD_FACE = "🤓"
    """:obj:`str`: Nerd face"""
    GHOST = "👻"
    """:obj:`str`: Ghost"""
    MAN_TECHNOLOGIST = "👨‍💻"
    """:obj:`str`: Man Technologist"""
    EYES = "👀"
    """:obj:`str`: Eyes"""
    JACK_O_LANTERN = "🎃"
    """:obj:`str`: Jack-o-lantern"""
    SEE_NO_EVIL_MONKEY = "🙈"
    """:obj:`str`: See-no-evil monkey"""
    SMILING_FACE_WITH_HALO = "😇"
    """:obj:`str`: Smiling face with halo"""
    FEARFUL_FACE = "😨"
    """:obj:`str`: Fearful face"""
    HANDSHAKE = "🤝"
    """:obj:`str`: Handshake"""
    WRITING_HAND = "✍"
    """:obj:`str`: Writing hand"""
    HUGGING_FACE = "🤗"
    """:obj:`str`: Hugging face"""
    SALUTING_FACE = "🫡"
    """:obj:`str`: Saluting face"""
    FATHER_CHRISTMAS = "🎅"
    """:obj:`str`: Father christmas"""
    CHRISTMAS_TREE = "🎄"
    """:obj:`str`: Christmas tree"""
    SNOWMAN = "☃"
    """:obj:`str`: Snowman"""
    NAIL_POLISH = "💅"
    """:obj:`str`: Nail polish"""
    GRINNING_FACE_WITH_ONE_LARGE_AND_ONE_SMALL_EYE = "🤪"
    """:obj:`str`: Grinning face with one large and one small eye"""
    MOYAI = "🗿"
    """:obj:`str`: Moyai"""
    SQUARED_COOL = "🆒"
    """:obj:`str`: Squared cool"""
    HEART_WITH_ARROW = "💘"
    """:obj:`str`: Heart with arrow"""
    HEAR_NO_EVIL_MONKEY = "🙉"
    """:obj:`str`: Hear-no-evil monkey"""
    UNICORN_FACE = "🦄"
    """:obj:`str`: Unicorn face"""
    FACE_THROWING_A_KISS = "😘"
    """:obj:`str`: Face throwing a kiss"""
    PILL = "💊"
    """:obj:`str`: Pill"""
    SPEAK_NO_EVIL_MONKEY = "🙊"
    """:obj:`str`: Speak-no-evil monkey"""
    SMILING_FACE_WITH_SUNGLASSES = "😎"
    """:obj:`str`: Smiling face with sunglasses"""
    ALIEN_MONSTER = "👾"
    """:obj:`str`: Alien monster"""
    MAN_SHRUGGING = "🤷‍♂️"
    """:obj:`str`: Man Shrugging"""
    SHRUG = "🤷"
    """:obj:`str`: Shrug"""
    WOMAN_SHRUGGING = "🤷‍♀️"
    """:obj:`str`: Woman Shrugging"""
    POUTING_FACE = "😡"
    """:obj:`str`: Pouting face"""


class VerifyLimit(IntEnum):
    """This enum contains limitations for :meth:`~telegram.Bot.verify_chat` and
    :meth:`~telegram.Bot.verify_user`.
    The enum members of this enumeration are instances of :class:`int` and can be treated as such.

    .. versionadded:: 21.10
    """

    __slots__ = ()

    MAX_TEXT_LENGTH = 70
    """:obj:`int`: Maximum number of characters in a :obj:`str` passed as the
    :paramref:`~telegram.Bot.verify_chat.custom_description` or
    :paramref:`~telegram.Bot.verify_user.custom_description` parameter.
    """
