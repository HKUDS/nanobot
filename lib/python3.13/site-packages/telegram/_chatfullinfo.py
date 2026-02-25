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
# along with this program.  If not, see [http://www.gnu.org/licenses/].
"""This module contains an object that represents a Telegram ChatFullInfo."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._birthdate import Birthdate
from telegram._chat import Chat, _ChatBase
from telegram._chatlocation import ChatLocation
from telegram._chatpermissions import ChatPermissions
from telegram._files.chatphoto import ChatPhoto
from telegram._gifts import AcceptedGiftTypes
from telegram._reaction import ReactionType
from telegram._uniquegift import UniqueGiftColors
from telegram._userrating import UserRating
from telegram._utils.argumentparsing import (
    de_json_optional,
    de_list_optional,
    parse_sequence_arg,
    to_timedelta,
)
from telegram._utils.datetime import (
    extract_tzinfo_from_defaults,
    from_timestamp,
    get_timedelta_value,
)
from telegram._utils.types import JSONDict, TimePeriod

if TYPE_CHECKING:
    from telegram import Bot, BusinessIntro, BusinessLocation, BusinessOpeningHours, Message


class ChatFullInfo(_ChatBase):
    """
    This object contains full information about a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`~telegram.Chat.id` is equal.

    .. versionadded:: 21.2

    .. versionchanged:: 21.3
        Explicit support for all shortcut methods known from :class:`telegram.Chat` on this
        object. Previously those were only available because this class inherited from
        :class:`telegram.Chat`.

    .. versionremoved:: 22.3
       Removed argument and attribute ``can_send_gift`` deprecated  by API 9.0.

    Args:
        id (:obj:`int`): Unique identifier for this chat.
        type (:obj:`str`): Type of chat, can be either :attr:`PRIVATE`, :attr:`GROUP`,
            :attr:`SUPERGROUP` or :attr:`CHANNEL`.
        accent_color_id (:obj:`int`, optional): Identifier of the
            :class:`accent color <telegram.constants.AccentColor>` for the chat name and
            backgrounds of the chat photo, reply header, and link preview. See `accent colors`_
            for more details.

            .. versionadded:: 20.8
        max_reaction_count (:obj:`int`): The maximum number of reactions that can be set on a
            message in the chat.

            .. versionadded:: 21.2
        accepted_gift_types (:class:`telegram.AcceptedGiftTypes`): Information about types of
            gifts that are accepted by the chat or by the corresponding user for private chats.

            .. versionadded:: 22.1
        title (:obj:`str`, optional): Title, for supergroups, channels and group chats.
        username (:obj:`str`, optional): Username, for private chats, supergroups and channels if
            available.
        first_name (:obj:`str`, optional): First name of the other party in a private chat.
        last_name (:obj:`str`, optional): Last name of the other party in a private chat.
        is_forum (:obj:`bool`, optional): :obj:`True`, if the supergroup chat is a forum
            (has topics_ enabled).

            .. versionadded:: 20.0
        photo (:class:`telegram.ChatPhoto`, optional): Chat photo.
        active_usernames (Sequence[:obj:`str`], optional):  If set, the list of all `active chat
            usernames <https://telegram.org/blog/topics-in-groups-collectible-usernames\
            #collectible-usernames>`_; for private chats, supergroups and channels.

            .. versionadded:: 20.0
        birthdate (:class:`telegram.Birthdate`, optional): For private chats,
            the date of birth of the user.

            .. versionadded:: 21.1
        business_intro (:class:`telegram.BusinessIntro`, optional): For private chats with
            business accounts, the intro of the business.

            .. versionadded:: 21.1
        business_location (:class:`telegram.BusinessLocation`, optional): For private chats with
            business accounts, the location of the business.

            .. versionadded:: 21.1
        business_opening_hours (:class:`telegram.BusinessOpeningHours`, optional): For private
            chats with business accounts, the opening hours of the business.

            .. versionadded:: 21.1
        personal_chat (:class:`telegram.Chat`, optional): For private chats, the personal channel
            of the user.

            .. versionadded:: 21.1
        available_reactions (Sequence[:class:`telegram.ReactionType`], optional): List of available
            reactions allowed in the chat. If omitted, then all of
            :const:`telegram.constants.ReactionEmoji` are allowed.

            .. versionadded:: 20.8
        background_custom_emoji_id (:obj:`str`, optional): Custom emoji identifier of emoji chosen
            by the chat for the reply header and link preview background.

            .. versionadded:: 20.8
        profile_accent_color_id (:obj:`int`, optional): Identifier of the
            :class:`accent color <telegram.constants.ProfileAccentColor>` for the chat's profile
            background. See profile `accent colors`_ for more details.

            .. versionadded:: 20.8
        profile_background_custom_emoji_id (:obj:`str`, optional): Custom emoji identifier of
            the emoji chosen by the chat for its profile background.

            .. versionadded:: 20.8
        emoji_status_custom_emoji_id (:obj:`str`, optional): Custom emoji identifier of emoji
            status of the chat or the other party in a private chat.

            .. versionadded:: 20.0
        emoji_status_expiration_date (:class:`datetime.datetime`, optional): Expiration date of
            emoji status of the chat or the other party in a private chat, as a datetime object,
            if any.

            |datetime_localization|

            .. versionadded:: 20.5
        bio (:obj:`str`, optional): Bio of the other party in a private chat.
        has_private_forwards (:obj:`bool`, optional): :obj:`True`, if privacy settings of the other
            party in the private chat allows to use ``tg://user?id=<user_id>`` links only in chats
            with the user.

            .. versionadded:: 13.9
        has_restricted_voice_and_video_messages (:obj:`bool`, optional): :obj:`True`, if the
            privacy settings of the other party restrict sending voice and video note messages
            in the private chat.

            .. versionadded:: 20.0
        join_to_send_messages (:obj:`bool`, optional): :obj:`True`, if users need to join the
            supergroup before they can send messages.

            .. versionadded:: 20.0
        join_by_request (:obj:`bool`, optional): :obj:`True`, if all users directly joining the
            supergroup without using an invite link need to be approved by supergroup
            administrators.

            .. versionadded:: 20.0
        description (:obj:`str`, optional): Description, for groups, supergroups and channel chats.
        invite_link (:obj:`str`, optional): Primary invite link, for groups, supergroups and
            channel.
        pinned_message (:class:`telegram.Message`, optional): The most recent pinned message
            (by sending date).
        permissions (:class:`telegram.ChatPermissions`): Optional. Default chat member permissions,
            for groups and supergroups.
        slow_mode_delay (:obj:`int` | :class:`datetime.timedelta`, optional): For supergroups,
            the minimum allowed delay between consecutive messages sent by each unprivileged user.

            .. versionchanged:: v22.2
                |time-period-input|
        unrestrict_boost_count (:obj:`int`, optional): For supergroups, the minimum number of
            boosts that a non-administrator user needs to add in order to ignore slow mode and chat
            permissions.

            .. versionadded:: 21.0
        message_auto_delete_time (:obj:`int` | :class:`datetime.timedelta`, optional): The time
            after which all messages sent to the chat will be automatically deleted; in seconds.

            .. versionadded:: 13.4

            .. versionchanged:: v22.2
                |time-period-input|
        has_aggressive_anti_spam_enabled (:obj:`bool`, optional): :obj:`True`, if aggressive
            anti-spam checks are enabled in the supergroup. The field is only available to chat
            administrators.

            .. versionadded:: 20.0
        has_hidden_members (:obj:`bool`, optional): :obj:`True`, if non-administrators can only
            get the list of bots and administrators in the chat.

            .. versionadded:: 20.0
        has_protected_content (:obj:`bool`, optional): :obj:`True`, if messages from the chat can't
            be forwarded to other chats.

            .. versionadded:: 13.9
        has_visible_history (:obj:`bool`, optional): :obj:`True`, if new chat members will have
            access to old messages; available only to chat administrators.

            .. versionadded:: 20.8
        sticker_set_name (:obj:`str`, optional): For supergroups, name of group sticker set.
        can_set_sticker_set (:obj:`bool`, optional): :obj:`True`, if the bot can change group the
            sticker set.
        custom_emoji_sticker_set_name (:obj:`str`, optional): For supergroups, the name of the
            group's custom emoji sticker set. Custom emoji from this set can be used by all users
            and bots in the group.

            .. versionadded:: 21.0
        linked_chat_id (:obj:`int`, optional): Unique identifier for the linked chat, i.e. the
            discussion group identifier for a channel and vice versa; for supergroups and channel
            chats.
        location (:class:`telegram.ChatLocation`, optional): For supergroups, the location to which
            the supergroup is connected.
        can_send_paid_media (:obj:`bool`, optional): :obj:`True`, if paid media messages can be
            sent or forwarded to the channel chat. The field is available only for channel chats.

            .. versionadded:: 21.4
        is_direct_messages (:obj:`bool`, optional): :obj:`True`, if the chat is the direct messages
            chat of a channel.

            .. versionadded:: 22.4
        parent_chat (:obj:`telegram.Chat`, optional): Information about the corresponding channel
            chat; for direct messages chats only.

            .. versionadded:: 22.4
        rating (:class:`telegram.UserRating`, optional): For private chats, the rating of the user
            if any.

            .. versionadded:: 22.6
        unique_gift_colors (:class:`telegram.UniqueGiftColors`, optional): The color scheme based
            on a unique gift that must be used for the chat's name, message replies and link
            previews

            .. versionadded:: 22.6
        paid_message_star_count (:obj:`int`, optional): The number of Telegram Stars a general user
            have to pay to send a message to the chat

            .. versionadded:: 22.6

    Attributes:
        id (:obj:`int`): Unique identifier for this chat.
        type (:obj:`str`): Type of chat, can be either :attr:`PRIVATE`, :attr:`GROUP`,
            :attr:`SUPERGROUP` or :attr:`CHANNEL`.
        accent_color_id (:obj:`int`): Optional. Identifier of the
            :class:`accent color <telegram.constants.AccentColor>` for the chat name and
            backgrounds of the chat photo, reply header, and link preview. See `accent colors`_
            for more details.

            .. versionadded:: 20.8
        max_reaction_count (:obj:`int`): The maximum number of reactions that can be set on a
            message in the chat.

            .. versionadded:: 21.2
        accepted_gift_types (:class:`telegram.AcceptedGiftTypes`): Information about types of
            gifts that are accepted by the chat or by the corresponding user for private chats.

            .. versionadded:: 22.1
        title (:obj:`str`, optional): Title, for supergroups, channels and group chats.
        username (:obj:`str`, optional): Username, for private chats, supergroups and channels if
            available.
        first_name (:obj:`str`, optional): First name of the other party in a private chat.
        last_name (:obj:`str`, optional): Last name of the other party in a private chat.
        is_forum (:obj:`bool`, optional): :obj:`True`, if the supergroup chat is a forum
            (has topics_ enabled).

            .. versionadded:: 20.0
        photo (:class:`telegram.ChatPhoto`): Optional. Chat photo.
        active_usernames (tuple[:obj:`str`]): Optional. If set, the list of all `active chat
            usernames <https://telegram.org/blog/topics-in-groups-collectible-usernames\
            #collectible-usernames>`_; for private chats, supergroups and channels.

            This list is empty if the chat has no active usernames or this chat instance was not
            obtained via :meth:`~telegram.Bot.get_chat`.

            .. versionadded:: 20.0
        birthdate (:class:`telegram.Birthdate`): Optional. For private chats,
            the date of birth of the user.

            .. versionadded:: 21.1
        business_intro (:class:`telegram.BusinessIntro`): Optional. For private chats with
            business accounts, the intro of the business.

            .. versionadded:: 21.1
        business_location (:class:`telegram.BusinessLocation`): Optional. For private chats with
            business accounts, the location of the business.

            .. versionadded:: 21.1
        business_opening_hours (:class:`telegram.BusinessOpeningHours`): Optional. For private
            chats with business accounts, the opening hours of the business.

            .. versionadded:: 21.1
        personal_chat (:class:`telegram.Chat`): Optional. For private chats, the personal channel
            of the user.

            .. versionadded:: 21.1
        available_reactions (tuple[:class:`telegram.ReactionType`]): Optional. List of available
            reactions allowed in the chat. If omitted, then all of
            :const:`telegram.constants.ReactionEmoji` are allowed.

            .. versionadded:: 20.8
        background_custom_emoji_id (:obj:`str`): Optional. Custom emoji identifier of emoji chosen
            by the chat for the reply header and link preview background.

            .. versionadded:: 20.8
        profile_accent_color_id (:obj:`int`): Optional. Identifier of the
            :class:`accent color <telegram.constants.ProfileAccentColor>` for the chat's profile
            background. See profile `accent colors`_ for more details.

            .. versionadded:: 20.8
        profile_background_custom_emoji_id (:obj:`str`): Optional. Custom emoji identifier of
            the emoji chosen by the chat for its profile background.

            .. versionadded:: 20.8
        emoji_status_custom_emoji_id (:obj:`str`): Optional. Custom emoji identifier of emoji
            status of the chat or the other party in a private chat.

            .. versionadded:: 20.0
        emoji_status_expiration_date (:class:`datetime.datetime`): Optional. Expiration date of
            emoji status of the chat or the other party in a private chat, as a datetime object,
            if any.

            |datetime_localization|

            .. versionadded:: 20.5
        bio (:obj:`str`): Optional. Bio of the other party in a private chat.
        has_private_forwards (:obj:`bool`): Optional. :obj:`True`, if privacy settings of the other
            party in the private chat allows to use ``tg://user?id=<user_id>`` links only in chats
            with the user.

            .. versionadded:: 13.9
        has_restricted_voice_and_video_messages (:obj:`bool`): Optional. :obj:`True`, if the
            privacy settings of the other party restrict sending voice and video note messages
            in the private chat.

            .. versionadded:: 20.0
        join_to_send_messages (:obj:`bool`): Optional. :obj:`True`, if users need to join
            the supergroup before they can send messages.

            .. versionadded:: 20.0
        join_by_request (:obj:`bool`): Optional. :obj:`True`, if all users directly joining the
            supergroup without using an invite link need to be approved by supergroup
            administrators.

            .. versionadded:: 20.0
        description (:obj:`str`): Optional. Description, for groups, supergroups and channel chats.
        invite_link (:obj:`str`): Optional. Primary invite link, for groups, supergroups and
            channel.
        pinned_message (:class:`telegram.Message`): Optional. The most recent pinned message
            (by sending date).
        permissions (:class:`telegram.ChatPermissions`): Optional. Default chat member permissions,
            for groups and supergroups.
        slow_mode_delay (:obj:`int` | :class:`datetime.timedelta`): Optional. For supergroups,
            the minimum allowed delay between consecutive messages sent by each unprivileged user.

            .. deprecated:: v22.2
                |time-period-int-deprecated|
        unrestrict_boost_count (:obj:`int`): Optional. For supergroups, the minimum number of
            boosts that a non-administrator user needs to add in order to ignore slow mode and chat
            permissions.

            .. versionadded:: 21.0
        message_auto_delete_time (:obj:`int` | :class:`datetime.timedelta`): Optional. The time
            after which all messages sent to the chat will be automatically deleted; in seconds.

            .. versionadded:: 13.4

            .. deprecated:: v22.2
                |time-period-int-deprecated|
        has_aggressive_anti_spam_enabled (:obj:`bool`): Optional. :obj:`True`, if aggressive
            anti-spam checks are enabled in the supergroup. The field is only available to chat
            administrators.

            .. versionadded:: 20.0
        has_hidden_members (:obj:`bool`): Optional. :obj:`True`, if non-administrators can only
            get the list of bots and administrators in the chat.

            .. versionadded:: 20.0
        has_protected_content (:obj:`bool`): Optional. :obj:`True`, if messages from the chat can't
            be forwarded to other chats.

            .. versionadded:: 13.9
        has_visible_history (:obj:`bool`): Optional. :obj:`True`, if new chat members will have
            access to old messages; available only to chat administrators.

            .. versionadded:: 20.8
        sticker_set_name (:obj:`str`): Optional. For supergroups, name of Group sticker set.
        can_set_sticker_set (:obj:`bool`): Optional. :obj:`True`, if the bot can change group the
            sticker set.
        custom_emoji_sticker_set_name (:obj:`str`): Optional. For supergroups, the name of the
            group's custom emoji sticker set. Custom emoji from this set can be used by all users
            and bots in the group.

            .. versionadded:: 21.0
        linked_chat_id (:obj:`int`): Optional. Unique identifier for the linked chat, i.e. the
            discussion group identifier for a channel and vice versa; for supergroups and channel
            chats.
        location (:class:`telegram.ChatLocation`): Optional. For supergroups, the location to which
            the supergroup is connected.
        can_send_paid_media (:obj:`bool`): Optional. :obj:`True`, if paid media messages can be
            sent or forwarded to the channel chat. The field is available only for channel chats.

            .. versionadded:: 21.4
        is_direct_messages (:obj:`bool`): Optional. :obj:`True`, if the chat is the direct messages
            chat of a channel.

            .. versionadded:: 22.4
        parent_chat (:obj:`telegram.Chat`): Optional. Information about the corresponding channel
            chat; for direct messages chats only.

            .. versionadded:: 22.4
        rating (:class:`telegram.UserRating`): Optional. For private chats, the rating of the user
            if any.

            .. versionadded:: 22.6
        unique_gift_colors (:class:`telegram.UniqueGiftColors`): Optional. The color scheme based
            on a unique gift that must be used for the chat's name, message replies and link
            previews

            .. versionadded:: 22.6
        paid_message_star_count (:obj:`int`): Optional. The number of Telegram Stars a general user
            have to pay to send a message to the chat

            .. versionadded:: 22.6

    .. _accent colors: https://core.telegram.org/bots/api#accent-colors
    .. _topics: https://telegram.org/blog/topics-in-groups-collectible-usernames#topics-in-groups
    """

    __slots__ = (
        "_message_auto_delete_time",
        "_slow_mode_delay",
        "accent_color_id",
        "accepted_gift_types",
        "active_usernames",
        "available_reactions",
        "background_custom_emoji_id",
        "bio",
        "birthdate",
        "business_intro",
        "business_location",
        "business_opening_hours",
        "can_send_paid_media",
        "can_set_sticker_set",
        "custom_emoji_sticker_set_name",
        "description",
        "emoji_status_custom_emoji_id",
        "emoji_status_expiration_date",
        "has_aggressive_anti_spam_enabled",
        "has_hidden_members",
        "has_private_forwards",
        "has_protected_content",
        "has_restricted_voice_and_video_messages",
        "has_visible_history",
        "invite_link",
        "join_by_request",
        "join_to_send_messages",
        "linked_chat_id",
        "location",
        "max_reaction_count",
        "paid_message_star_count",
        "parent_chat",
        "permissions",
        "personal_chat",
        "photo",
        "pinned_message",
        "profile_accent_color_id",
        "profile_background_custom_emoji_id",
        "rating",
        "sticker_set_name",
        "unique_gift_colors",
        "unrestrict_boost_count",
    )

    def __init__(
        self,
        id: int,
        type: str,
        accent_color_id: int,
        max_reaction_count: int,
        accepted_gift_types: AcceptedGiftTypes,
        title: str | None = None,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        is_forum: bool | None = None,
        photo: ChatPhoto | None = None,
        active_usernames: Sequence[str] | None = None,
        birthdate: Birthdate | None = None,
        business_intro: "BusinessIntro | None" = None,
        business_location: "BusinessLocation | None" = None,
        business_opening_hours: "BusinessOpeningHours | None" = None,
        personal_chat: "Chat | None" = None,
        available_reactions: Sequence[ReactionType] | None = None,
        background_custom_emoji_id: str | None = None,
        profile_accent_color_id: int | None = None,
        profile_background_custom_emoji_id: str | None = None,
        emoji_status_custom_emoji_id: str | None = None,
        emoji_status_expiration_date: dtm.datetime | None = None,
        bio: str | None = None,
        has_private_forwards: bool | None = None,
        has_restricted_voice_and_video_messages: bool | None = None,
        join_to_send_messages: bool | None = None,
        join_by_request: bool | None = None,
        description: str | None = None,
        invite_link: str | None = None,
        pinned_message: "Message | None" = None,
        permissions: ChatPermissions | None = None,
        slow_mode_delay: TimePeriod | None = None,
        unrestrict_boost_count: int | None = None,
        message_auto_delete_time: TimePeriod | None = None,
        has_aggressive_anti_spam_enabled: bool | None = None,
        has_hidden_members: bool | None = None,
        has_protected_content: bool | None = None,
        has_visible_history: bool | None = None,
        sticker_set_name: str | None = None,
        can_set_sticker_set: bool | None = None,
        custom_emoji_sticker_set_name: str | None = None,
        linked_chat_id: int | None = None,
        location: ChatLocation | None = None,
        can_send_paid_media: bool | None = None,
        is_direct_messages: bool | None = None,
        parent_chat: Chat | None = None,
        rating: UserRating | None = None,
        unique_gift_colors: UniqueGiftColors | None = None,
        paid_message_star_count: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(
            id=id,
            type=type,
            title=title,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_forum=is_forum,
            is_direct_messages=is_direct_messages,
            api_kwargs=api_kwargs,
        )
        # Required and unique to this class-
        with self._unfrozen():
            self.max_reaction_count: int = max_reaction_count
            self.photo: ChatPhoto | None = photo
            self.bio: str | None = bio
            self.has_private_forwards: bool | None = has_private_forwards
            self.description: str | None = description
            self.invite_link: str | None = invite_link
            self.pinned_message: Message | None = pinned_message
            self.permissions: ChatPermissions | None = permissions
            self._slow_mode_delay: dtm.timedelta | None = to_timedelta(slow_mode_delay)
            self._message_auto_delete_time: dtm.timedelta | None = to_timedelta(
                message_auto_delete_time
            )
            self.has_protected_content: bool | None = has_protected_content
            self.has_visible_history: bool | None = has_visible_history
            self.sticker_set_name: str | None = sticker_set_name
            self.can_set_sticker_set: bool | None = can_set_sticker_set
            self.linked_chat_id: int | None = linked_chat_id
            self.location: ChatLocation | None = location
            self.join_to_send_messages: bool | None = join_to_send_messages
            self.join_by_request: bool | None = join_by_request
            self.has_restricted_voice_and_video_messages: bool | None = (
                has_restricted_voice_and_video_messages
            )
            self.active_usernames: tuple[str, ...] = parse_sequence_arg(active_usernames)
            self.emoji_status_custom_emoji_id: str | None = emoji_status_custom_emoji_id
            self.emoji_status_expiration_date: dtm.datetime | None = emoji_status_expiration_date
            self.has_aggressive_anti_spam_enabled: bool | None = has_aggressive_anti_spam_enabled
            self.has_hidden_members: bool | None = has_hidden_members
            self.available_reactions: tuple[ReactionType, ...] | None = parse_sequence_arg(
                available_reactions
            )
            self.accent_color_id: int | None = accent_color_id
            self.background_custom_emoji_id: str | None = background_custom_emoji_id
            self.profile_accent_color_id: int | None = profile_accent_color_id
            self.profile_background_custom_emoji_id: str | None = (
                profile_background_custom_emoji_id
            )
            self.unrestrict_boost_count: int | None = unrestrict_boost_count
            self.custom_emoji_sticker_set_name: str | None = custom_emoji_sticker_set_name
            self.birthdate: Birthdate | None = birthdate
            self.personal_chat: Chat | None = personal_chat
            self.business_intro: BusinessIntro | None = business_intro
            self.business_location: BusinessLocation | None = business_location
            self.business_opening_hours: BusinessOpeningHours | None = business_opening_hours
            self.can_send_paid_media: bool | None = can_send_paid_media
            self.accepted_gift_types: AcceptedGiftTypes = accepted_gift_types
            self.parent_chat: Chat | None = parent_chat
            self.rating: UserRating | None = rating
            self.unique_gift_colors: UniqueGiftColors | None = unique_gift_colors
            self.paid_message_star_count: int | None = paid_message_star_count

    @property
    def slow_mode_delay(self) -> int | dtm.timedelta | None:
        return get_timedelta_value(self._slow_mode_delay, attribute="slow_mode_delay")

    @property
    def message_auto_delete_time(self) -> int | dtm.timedelta | None:
        return get_timedelta_value(
            self._message_auto_delete_time, attribute="message_auto_delete_time"
        )

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChatFullInfo":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["emoji_status_expiration_date"] = from_timestamp(
            data.get("emoji_status_expiration_date"), tzinfo=loc_tzinfo
        )

        data["photo"] = de_json_optional(data.get("photo"), ChatPhoto, bot)
        data["accepted_gift_types"] = de_json_optional(
            data.get("accepted_gift_types"), AcceptedGiftTypes, bot
        )

        from telegram import (  # pylint: disable=import-outside-toplevel  # noqa: PLC0415
            BusinessIntro,
            BusinessLocation,
            BusinessOpeningHours,
            Message,
        )

        data["pinned_message"] = de_json_optional(data.get("pinned_message"), Message, bot)
        data["permissions"] = de_json_optional(data.get("permissions"), ChatPermissions, bot)
        data["location"] = de_json_optional(data.get("location"), ChatLocation, bot)
        data["available_reactions"] = de_list_optional(
            data.get("available_reactions"), ReactionType, bot
        )
        data["birthdate"] = de_json_optional(data.get("birthdate"), Birthdate, bot)
        data["personal_chat"] = de_json_optional(data.get("personal_chat"), Chat, bot)
        data["business_intro"] = de_json_optional(data.get("business_intro"), BusinessIntro, bot)
        data["business_location"] = de_json_optional(
            data.get("business_location"), BusinessLocation, bot
        )
        data["business_opening_hours"] = de_json_optional(
            data.get("business_opening_hours"), BusinessOpeningHours, bot
        )
        data["parent_chat"] = de_json_optional(data.get("parent_chat"), Chat, bot)

        data["rating"] = de_json_optional(data.get("rating"), UserRating, bot)
        data["unique_gift_colors"] = de_json_optional(
            data.get("unique_gift_colors"), UniqueGiftColors, bot
        )

        return super().de_json(data=data, bot=bot)
