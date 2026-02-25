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
"""This module contains an object that represents a Telegram Update."""

from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._business import BusinessConnection, BusinessMessagesDeleted
from telegram._callbackquery import CallbackQuery
from telegram._chatboost import ChatBoostRemoved, ChatBoostUpdated
from telegram._chatjoinrequest import ChatJoinRequest
from telegram._chatmemberupdated import ChatMemberUpdated
from telegram._choseninlineresult import ChosenInlineResult
from telegram._inline.inlinequery import InlineQuery
from telegram._message import Message
from telegram._messagereactionupdated import MessageReactionCountUpdated, MessageReactionUpdated
from telegram._paidmedia import PaidMediaPurchased
from telegram._payment.precheckoutquery import PreCheckoutQuery
from telegram._payment.shippingquery import ShippingQuery
from telegram._poll import Poll, PollAnswer
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict
from telegram._utils.warnings import warn

if TYPE_CHECKING:
    from telegram import Bot, Chat, User


class Update(TelegramObject):
    """This object represents an incoming update.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`update_id` is equal.

    Note:
        At most one of the optional parameters can be present in any given update.

    .. seealso:: :wiki:`Your First Bot <Extensions---Your-first-Bot>`

    Args:
        update_id (:obj:`int`): The update's unique identifier. Update identifiers start from a
            certain positive number and increase sequentially. This ID becomes especially handy if
            you're using Webhooks, since it allows you to ignore repeated updates or to restore the
            correct update sequence, should they get out of order. If there are no new updates for
            at least a week, then identifier of the next update will be chosen randomly instead of
            sequentially.
        message (:class:`telegram.Message`, optional): New incoming message of any kind - text,
            photo, sticker, etc.
        edited_message (:class:`telegram.Message`, optional): New version of a message that is
            known to the bot and was edited. This update may at times be triggered by changes to
            message fields that are either unavailable or not actively used by your bot.
        channel_post (:class:`telegram.Message`, optional): New incoming channel post of any kind
            - text, photo, sticker, etc.
        edited_channel_post (:class:`telegram.Message`, optional): New version of a channel post
            that is known to the bot and was edited. This update may at times be triggered by
            changes to message fields that are either unavailable or not actively used by your bot.
        inline_query (:class:`telegram.InlineQuery`, optional): New incoming inline query.
        chosen_inline_result (:class:`telegram.ChosenInlineResult`, optional): The result of an
            inline query that was chosen by a user and sent to their chat partner.
        callback_query (:class:`telegram.CallbackQuery`, optional): New incoming callback query.
        shipping_query (:class:`telegram.ShippingQuery`, optional): New incoming shipping query.
            Only for invoices with flexible price.
        pre_checkout_query (:class:`telegram.PreCheckoutQuery`, optional): New incoming
            pre-checkout query. Contains full information about checkout.
        poll (:class:`telegram.Poll`, optional): New poll state. Bots receive only updates about
            manually stopped polls and polls, which are sent by the bot.
        poll_answer (:class:`telegram.PollAnswer`, optional): A user changed their answer
            in a non-anonymous poll. Bots receive new votes only in polls that were sent
            by the bot itself.
        my_chat_member (:class:`telegram.ChatMemberUpdated`, optional): The bot's chat member
            status was updated in a chat. For private chats, this update is received only when the
            bot is blocked or unblocked by the user.

            .. versionadded:: 13.4
        chat_member (:class:`telegram.ChatMemberUpdated`, optional): A chat member's status was
            updated in a chat. The bot must be an administrator in the chat and must explicitly
            specify :attr:`CHAT_MEMBER` in the list of
            :paramref:`telegram.ext.Application.run_polling.allowed_updates` to receive these
            updates (see :meth:`telegram.Bot.get_updates`, :meth:`telegram.Bot.set_webhook`,
            :meth:`telegram.ext.Application.run_polling` and
            :meth:`telegram.ext.Application.run_webhook`).

            .. versionadded:: 13.4
        chat_join_request (:class:`telegram.ChatJoinRequest`, optional): A request to join the
            chat has been sent. The bot must have the
            :attr:`telegram.ChatPermissions.can_invite_users` administrator right in the chat to
            receive these updates.

            .. versionadded:: 13.8

        chat_boost (:class:`telegram.ChatBoostUpdated`, optional): A chat boost was added or
            changed. The bot must be an administrator in the chat to receive these updates.

            .. versionadded:: 20.8

        removed_chat_boost (:class:`telegram.ChatBoostRemoved`, optional): A boost was removed from
            a chat. The bot must be an administrator in the chat to receive these updates.

            .. versionadded:: 20.8

        message_reaction (:class:`telegram.MessageReactionUpdated`, optional): A reaction to a
            message was changed by a user. The bot must be an administrator in the chat and must
            explicitly specify :attr:`MESSAGE_REACTION` in the list of
            :paramref:`telegram.ext.Application.run_polling.allowed_updates` to receive these
            updates (see :meth:`telegram.Bot.get_updates`, :meth:`telegram.Bot.set_webhook`,
            :meth:`telegram.ext.Application.run_polling` and
            :meth:`telegram.ext.Application.run_webhook`). The update isn't received for reactions
            set by bots.

            .. versionadded:: 20.8

        message_reaction_count (:class:`telegram.MessageReactionCountUpdated`, optional): Reactions
            to a message with anonymous reactions were changed. The bot must be an administrator in
            the chat and must explicitly specify :attr:`MESSAGE_REACTION_COUNT` in the list of
            :paramref:`telegram.ext.Application.run_polling.allowed_updates` to receive these
            updates (see :meth:`telegram.Bot.get_updates`, :meth:`telegram.Bot.set_webhook`,
            :meth:`telegram.ext.Application.run_polling` and
            :meth:`telegram.ext.Application.run_webhook`). The updates are grouped and can be sent
            with delay up to a few minutes.

            .. versionadded:: 20.8

        business_connection (:class:`telegram.BusinessConnection`, optional): The bot was connected
            to or disconnected from a business account, or a user edited an existing connection
            with the bot.

            .. versionadded:: 21.1

        business_message (:class:`telegram.Message`, optional): New message from a connected
            business account.

            .. versionadded:: 21.1

        edited_business_message (:class:`telegram.Message`, optional): New version of a message
            from a connected business account.

            .. versionadded:: 21.1

        deleted_business_messages (:class:`telegram.BusinessMessagesDeleted`, optional): Messages
            were deleted from a connected business account.

            .. versionadded:: 21.1

        purchased_paid_media (:class:`telegram.PaidMediaPurchased`, optional): A user purchased
            paid media with a non-empty payload sent by the bot in a non-channel chat.

            .. versionadded:: 21.6


    Attributes:
        update_id (:obj:`int`): The update's unique identifier. Update identifiers start from a
            certain positive number and increase sequentially. This ID becomes especially handy if
            you're using Webhooks, since it allows you to ignore repeated updates or to restore the
            correct update sequence, should they get out of order. If there are no new updates for
            at least a week, then identifier of the next update will be chosen randomly instead of
            sequentially.
        message (:class:`telegram.Message`): Optional. New incoming message of any kind - text,
            photo, sticker, etc.
        edited_message (:class:`telegram.Message`): Optional. New version of a message that is
            known to the bot and was edited. This update may at times be triggered by changes to
            message fields that are either unavailable or not actively used by your bot.
        channel_post (:class:`telegram.Message`): Optional. New incoming channel post of any kind
            - text, photo, sticker, etc.
        edited_channel_post (:class:`telegram.Message`): Optional. New version of a channel post
            that is known to the bot and was edited. This update may at times be triggered by
            changes to message fields that are either unavailable or not actively used by your bot.
        inline_query (:class:`telegram.InlineQuery`): Optional. New incoming inline query.
        chosen_inline_result (:class:`telegram.ChosenInlineResult`): Optional. The result of an
            inline query that was chosen by a user and sent to their chat partner.
        callback_query (:class:`telegram.CallbackQuery`): Optional. New incoming callback query.

            Examples:
                :any:`Arbitrary Callback Data Bot <examples.arbitrarycallbackdatabot>`
        shipping_query (:class:`telegram.ShippingQuery`): Optional. New incoming shipping query.
            Only for invoices with flexible price.
        pre_checkout_query (:class:`telegram.PreCheckoutQuery`): Optional. New incoming
            pre-checkout query. Contains full information about checkout.
        poll (:class:`telegram.Poll`): Optional. New poll state. Bots receive only updates about
            manually stopped polls and polls, which are sent by the bot.
        poll_answer (:class:`telegram.PollAnswer`): Optional. A user changed their answer
            in a non-anonymous poll. Bots receive new votes only in polls that were sent
            by the bot itself.
        my_chat_member (:class:`telegram.ChatMemberUpdated`): Optional. The bot's chat member
            status was updated in a chat. For private chats, this update is received only when the
            bot is blocked or unblocked by the user.

            .. versionadded:: 13.4
        chat_member (:class:`telegram.ChatMemberUpdated`): Optional. A chat member's status was
            updated in a chat. The bot must be an administrator in the chat and must explicitly
            specify :attr:`CHAT_MEMBER` in the list of
            :paramref:`telegram.ext.Application.run_polling.allowed_updates` to receive these
            updates (see :meth:`telegram.Bot.get_updates`, :meth:`telegram.Bot.set_webhook`,
            :meth:`telegram.ext.Application.run_polling` and
            :meth:`telegram.ext.Application.run_webhook`).

            .. versionadded:: 13.4
        chat_join_request (:class:`telegram.ChatJoinRequest`): Optional. A request to join the
            chat has been sent. The bot must have the
            :attr:`telegram.ChatPermissions.can_invite_users` administrator right in the chat to
            receive these updates.

            .. versionadded:: 13.8

        chat_boost (:class:`telegram.ChatBoostUpdated`): Optional. A chat boost was added or
            changed. The bot must be an administrator in the chat to receive these updates.

            .. versionadded:: 20.8

        removed_chat_boost (:class:`telegram.ChatBoostRemoved`): Optional. A boost was removed from
            a chat. The bot must be an administrator in the chat to receive these updates.

            .. versionadded:: 20.8

        message_reaction (:class:`telegram.MessageReactionUpdated`): Optional. A reaction to a
            message was changed by a user. The bot must be an administrator in the chat and must
            explicitly specify :attr:`MESSAGE_REACTION` in the list of
            :paramref:`telegram.ext.Application.run_polling.allowed_updates` to receive these
            updates (see :meth:`telegram.Bot.get_updates`, :meth:`telegram.Bot.set_webhook`,
            :meth:`telegram.ext.Application.run_polling` and
            :meth:`telegram.ext.Application.run_webhook`). The update isn't received for reactions
            set by bots.

            .. versionadded:: 20.8

        message_reaction_count (:class:`telegram.MessageReactionCountUpdated`): Optional. Reactions
            to a message with anonymous reactions were changed. The bot must be an administrator in
            the chat and must explicitly specify :attr:`MESSAGE_REACTION_COUNT` in the list of
            :paramref:`telegram.ext.Application.run_polling.allowed_updates` to receive these
            updates (see :meth:`telegram.Bot.get_updates`, :meth:`telegram.Bot.set_webhook`,
            :meth:`telegram.ext.Application.run_polling` and
            :meth:`telegram.ext.Application.run_webhook`). The updates are grouped and can be sent
            with delay up to a few minutes.

            .. versionadded:: 20.8

        business_connection (:class:`telegram.BusinessConnection`): Optional. The bot was connected
            to or disconnected from a business account, or a user edited an existing connection
            with the bot.

            .. versionadded:: 21.1

        business_message (:class:`telegram.Message`): Optional. New message from a connected
            business account.

            .. versionadded:: 21.1

        edited_business_message (:class:`telegram.Message`): Optional. New version of a message
            from a connected business account.

            .. versionadded:: 21.1

        deleted_business_messages (:class:`telegram.BusinessMessagesDeleted`): Optional. Messages
            were deleted from a connected business account.

            .. versionadded:: 21.1

        purchased_paid_media (:class:`telegram.PaidMediaPurchased`): Optional. A user purchased
            paid media with a non-empty payload sent by the bot in a non-channel chat.

            .. versionadded:: 21.6
    """

    __slots__ = (
        "_effective_chat",
        "_effective_message",
        "_effective_sender",
        "_effective_user",
        "business_connection",
        "business_message",
        "callback_query",
        "channel_post",
        "chat_boost",
        "chat_join_request",
        "chat_member",
        "chosen_inline_result",
        "deleted_business_messages",
        "edited_business_message",
        "edited_channel_post",
        "edited_message",
        "inline_query",
        "message",
        "message_reaction",
        "message_reaction_count",
        "my_chat_member",
        "poll",
        "poll_answer",
        "pre_checkout_query",
        "purchased_paid_media",
        "removed_chat_boost",
        "shipping_query",
        "update_id",
    )

    MESSAGE: Final[str] = constants.UpdateType.MESSAGE
    """:const:`telegram.constants.UpdateType.MESSAGE`

    .. versionadded:: 13.5"""
    EDITED_MESSAGE: Final[str] = constants.UpdateType.EDITED_MESSAGE
    """:const:`telegram.constants.UpdateType.EDITED_MESSAGE`

    .. versionadded:: 13.5"""
    CHANNEL_POST: Final[str] = constants.UpdateType.CHANNEL_POST
    """:const:`telegram.constants.UpdateType.CHANNEL_POST`

    .. versionadded:: 13.5"""
    EDITED_CHANNEL_POST: Final[str] = constants.UpdateType.EDITED_CHANNEL_POST
    """:const:`telegram.constants.UpdateType.EDITED_CHANNEL_POST`

    .. versionadded:: 13.5"""
    INLINE_QUERY: Final[str] = constants.UpdateType.INLINE_QUERY
    """:const:`telegram.constants.UpdateType.INLINE_QUERY`

    .. versionadded:: 13.5"""
    CHOSEN_INLINE_RESULT: Final[str] = constants.UpdateType.CHOSEN_INLINE_RESULT
    """:const:`telegram.constants.UpdateType.CHOSEN_INLINE_RESULT`

    .. versionadded:: 13.5"""
    CALLBACK_QUERY: Final[str] = constants.UpdateType.CALLBACK_QUERY
    """:const:`telegram.constants.UpdateType.CALLBACK_QUERY`

    .. versionadded:: 13.5"""
    SHIPPING_QUERY: Final[str] = constants.UpdateType.SHIPPING_QUERY
    """:const:`telegram.constants.UpdateType.SHIPPING_QUERY`

    .. versionadded:: 13.5"""
    PRE_CHECKOUT_QUERY: Final[str] = constants.UpdateType.PRE_CHECKOUT_QUERY
    """:const:`telegram.constants.UpdateType.PRE_CHECKOUT_QUERY`

    .. versionadded:: 13.5"""
    POLL: Final[str] = constants.UpdateType.POLL
    """:const:`telegram.constants.UpdateType.POLL`

    .. versionadded:: 13.5"""
    POLL_ANSWER: Final[str] = constants.UpdateType.POLL_ANSWER
    """:const:`telegram.constants.UpdateType.POLL_ANSWER`

    .. versionadded:: 13.5"""
    MY_CHAT_MEMBER: Final[str] = constants.UpdateType.MY_CHAT_MEMBER
    """:const:`telegram.constants.UpdateType.MY_CHAT_MEMBER`

    .. versionadded:: 13.5"""
    CHAT_MEMBER: Final[str] = constants.UpdateType.CHAT_MEMBER
    """:const:`telegram.constants.UpdateType.CHAT_MEMBER`

    .. versionadded:: 13.5"""
    CHAT_JOIN_REQUEST: Final[str] = constants.UpdateType.CHAT_JOIN_REQUEST
    """:const:`telegram.constants.UpdateType.CHAT_JOIN_REQUEST`

    .. versionadded:: 13.8"""
    CHAT_BOOST: Final[str] = constants.UpdateType.CHAT_BOOST
    """:const:`telegram.constants.UpdateType.CHAT_BOOST`

    .. versionadded:: 20.8"""
    REMOVED_CHAT_BOOST: Final[str] = constants.UpdateType.REMOVED_CHAT_BOOST
    """:const:`telegram.constants.UpdateType.REMOVED_CHAT_BOOST`

    .. versionadded:: 20.8"""
    MESSAGE_REACTION: Final[str] = constants.UpdateType.MESSAGE_REACTION
    """:const:`telegram.constants.UpdateType.MESSAGE_REACTION`

    .. versionadded:: 20.8"""
    MESSAGE_REACTION_COUNT: Final[str] = constants.UpdateType.MESSAGE_REACTION_COUNT
    """:const:`telegram.constants.UpdateType.MESSAGE_REACTION_COUNT`

    .. versionadded:: 20.8"""
    BUSINESS_CONNECTION: Final[str] = constants.UpdateType.BUSINESS_CONNECTION
    """:const:`telegram.constants.UpdateType.BUSINESS_CONNECTION`

    .. versionadded:: 21.1"""
    BUSINESS_MESSAGE: Final[str] = constants.UpdateType.BUSINESS_MESSAGE
    """:const:`telegram.constants.UpdateType.BUSINESS_MESSAGE`

    .. versionadded:: 21.1"""
    EDITED_BUSINESS_MESSAGE: Final[str] = constants.UpdateType.EDITED_BUSINESS_MESSAGE
    """:const:`telegram.constants.UpdateType.EDITED_BUSINESS_MESSAGE`

    .. versionadded:: 21.1"""
    DELETED_BUSINESS_MESSAGES: Final[str] = constants.UpdateType.DELETED_BUSINESS_MESSAGES
    """:const:`telegram.constants.UpdateType.DELETED_BUSINESS_MESSAGES`

    .. versionadded:: 21.1"""

    PURCHASED_PAID_MEDIA: Final[str] = constants.UpdateType.PURCHASED_PAID_MEDIA
    """:const:`telegram.constants.UpdateType.PURCHASED_PAID_MEDIA`

    .. versionadded:: 21.6
    """

    ALL_TYPES: Final[list[str]] = list(constants.UpdateType)
    """list[:obj:`str`]: A list of all available update types.

    .. versionadded:: 13.5"""

    def __init__(
        self,
        update_id: int,
        message: Message | None = None,
        edited_message: Message | None = None,
        channel_post: Message | None = None,
        edited_channel_post: Message | None = None,
        inline_query: InlineQuery | None = None,
        chosen_inline_result: ChosenInlineResult | None = None,
        callback_query: CallbackQuery | None = None,
        shipping_query: ShippingQuery | None = None,
        pre_checkout_query: PreCheckoutQuery | None = None,
        poll: Poll | None = None,
        poll_answer: PollAnswer | None = None,
        my_chat_member: ChatMemberUpdated | None = None,
        chat_member: ChatMemberUpdated | None = None,
        chat_join_request: ChatJoinRequest | None = None,
        chat_boost: ChatBoostUpdated | None = None,
        removed_chat_boost: ChatBoostRemoved | None = None,
        message_reaction: MessageReactionUpdated | None = None,
        message_reaction_count: MessageReactionCountUpdated | None = None,
        business_connection: BusinessConnection | None = None,
        business_message: Message | None = None,
        edited_business_message: Message | None = None,
        deleted_business_messages: BusinessMessagesDeleted | None = None,
        purchased_paid_media: PaidMediaPurchased | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.update_id: int = update_id
        # Optionals
        self.message: Message | None = message
        self.edited_message: Message | None = edited_message
        self.inline_query: InlineQuery | None = inline_query
        self.chosen_inline_result: ChosenInlineResult | None = chosen_inline_result
        self.callback_query: CallbackQuery | None = callback_query
        self.shipping_query: ShippingQuery | None = shipping_query
        self.pre_checkout_query: PreCheckoutQuery | None = pre_checkout_query
        self.channel_post: Message | None = channel_post
        self.edited_channel_post: Message | None = edited_channel_post
        self.poll: Poll | None = poll
        self.poll_answer: PollAnswer | None = poll_answer
        self.my_chat_member: ChatMemberUpdated | None = my_chat_member
        self.chat_member: ChatMemberUpdated | None = chat_member
        self.chat_join_request: ChatJoinRequest | None = chat_join_request
        self.chat_boost: ChatBoostUpdated | None = chat_boost
        self.removed_chat_boost: ChatBoostRemoved | None = removed_chat_boost
        self.message_reaction: MessageReactionUpdated | None = message_reaction
        self.message_reaction_count: MessageReactionCountUpdated | None = message_reaction_count
        self.business_connection: BusinessConnection | None = business_connection
        self.business_message: Message | None = business_message
        self.edited_business_message: Message | None = edited_business_message
        self.deleted_business_messages: BusinessMessagesDeleted | None = deleted_business_messages
        self.purchased_paid_media: PaidMediaPurchased | None = purchased_paid_media

        self._effective_user: User | None = None
        self._effective_sender: User | Chat | None = None
        self._effective_chat: Chat | None = None
        self._effective_message: Message | None = None

        self._id_attrs = (self.update_id,)

        self._freeze()

    @property
    def effective_user(self) -> "User | None":
        """
        :class:`telegram.User`: The user that sent this update, no matter what kind of update this
        is. If no user is associated with this update, this gives :obj:`None`. This is the case
        if any of

        * :attr:`channel_post`
        * :attr:`edited_channel_post`
        * :attr:`poll`
        * :attr:`chat_boost`
        * :attr:`removed_chat_boost`
        * :attr:`message_reaction_count`
        * :attr:`deleted_business_messages`

        is present.

        .. versionchanged:: 21.1
            This property now also considers :attr:`business_connection`, :attr:`business_message`
            and :attr:`edited_business_message`.

        .. versionchanged:: 21.6
            This property now also considers :attr:`purchased_paid_media`.

        Example:
            * If :attr:`message` is present, this will give
              :attr:`telegram.Message.from_user`.
            * If :attr:`poll_answer` is present, this will give :attr:`telegram.PollAnswer.user`.

        """
        if self._effective_user:
            return self._effective_user

        user = None

        if self.message:
            user = self.message.from_user

        elif self.edited_message:
            user = self.edited_message.from_user

        elif self.inline_query:
            user = self.inline_query.from_user

        elif self.chosen_inline_result:
            user = self.chosen_inline_result.from_user

        elif self.callback_query:
            user = self.callback_query.from_user

        elif self.shipping_query:
            user = self.shipping_query.from_user

        elif self.pre_checkout_query:
            user = self.pre_checkout_query.from_user

        elif self.poll_answer:
            user = self.poll_answer.user

        elif self.my_chat_member:
            user = self.my_chat_member.from_user

        elif self.chat_member:
            user = self.chat_member.from_user

        elif self.chat_join_request:
            user = self.chat_join_request.from_user

        elif self.message_reaction:
            user = self.message_reaction.user

        elif self.business_message:
            user = self.business_message.from_user

        elif self.edited_business_message:
            user = self.edited_business_message.from_user

        elif self.business_connection:
            user = self.business_connection.user

        elif self.purchased_paid_media:
            user = self.purchased_paid_media.from_user

        self._effective_user = user
        return user

    @property
    def effective_sender(self) -> "User | Chat | None":
        """
        :class:`telegram.User` or :class:`telegram.Chat`: The user or chat that sent this update,
        no matter what kind of update this is.

        Note:
            * Depending on the type of update and the user's 'Remain anonymous' setting, this
              could either be :class:`telegram.User`, :class:`telegram.Chat` or :obj:`None`.

        If no user whatsoever is associated with this update, this gives :obj:`None`. This
        is the case if any of

        * :attr:`poll`
        * :attr:`chat_boost`
        * :attr:`removed_chat_boost`
        * :attr:`message_reaction_count`
        * :attr:`deleted_business_messages`

        is present.

        Example:
            * If :attr:`message` is present, this will give either
              :attr:`telegram.Message.from_user` or :attr:`telegram.Message.sender_chat`.
            * If :attr:`poll_answer` is present, this will give either
              :attr:`telegram.PollAnswer.user` or :attr:`telegram.PollAnswer.voter_chat`.
            * If :attr:`channel_post` is present, this will give
              :attr:`telegram.Message.sender_chat`.

        .. versionadded:: 21.1
        """
        if self._effective_sender:
            return self._effective_sender

        sender: User | Chat | None = None

        if message := (
            self.message
            or self.edited_message
            or self.channel_post
            or self.edited_channel_post
            or self.business_message
            or self.edited_business_message
        ):
            sender = message.sender_chat

        elif self.poll_answer:
            sender = self.poll_answer.voter_chat

        elif self.message_reaction:
            sender = self.message_reaction.actor_chat

        if sender is None:
            sender = self.effective_user

        self._effective_sender = sender
        return sender

    @property
    def effective_chat(self) -> "Chat | None":
        """
        :class:`telegram.Chat`: The chat that this update was sent in, no matter what kind of
        update this is.
        If no chat is associated with this update, this gives :obj:`None`.
        This is the case, if :attr:`inline_query`,
        :attr:`chosen_inline_result`, :attr:`callback_query` from inline messages,
        :attr:`shipping_query`, :attr:`pre_checkout_query`, :attr:`poll`,
        :attr:`poll_answer`, :attr:`business_connection`, or :attr:`purchased_paid_media`
        is present.

        .. versionchanged:: 21.1
            This property now also considers :attr:`business_message`,
            :attr:`edited_business_message`, and :attr:`deleted_business_messages`.

        Example:
            If :attr:`message` is present, this will give :attr:`telegram.Message.chat`.

        """
        if self._effective_chat:
            return self._effective_chat

        chat = None

        if self.message:
            chat = self.message.chat

        elif self.edited_message:
            chat = self.edited_message.chat

        elif self.callback_query and self.callback_query.message:
            chat = self.callback_query.message.chat

        elif self.channel_post:
            chat = self.channel_post.chat

        elif self.edited_channel_post:
            chat = self.edited_channel_post.chat

        elif self.my_chat_member:
            chat = self.my_chat_member.chat

        elif self.chat_member:
            chat = self.chat_member.chat

        elif self.chat_join_request:
            chat = self.chat_join_request.chat

        elif self.chat_boost:
            chat = self.chat_boost.chat

        elif self.removed_chat_boost:
            chat = self.removed_chat_boost.chat

        elif self.message_reaction:
            chat = self.message_reaction.chat

        elif self.message_reaction_count:
            chat = self.message_reaction_count.chat

        elif self.business_message:
            chat = self.business_message.chat

        elif self.edited_business_message:
            chat = self.edited_business_message.chat

        elif self.deleted_business_messages:
            chat = self.deleted_business_messages.chat

        self._effective_chat = chat
        return chat

    @property
    def effective_message(self) -> Message | None:
        """
        :class:`telegram.Message`: The message included in this update, no matter what kind of
            update this is. More precisely, this will be the message contained in :attr:`message`,
            :attr:`edited_message`, :attr:`channel_post`, :attr:`edited_channel_post` or
            :attr:`callback_query` (i.e. :attr:`telegram.CallbackQuery.message`) or :obj:`None`, if
            none of those are present.

        .. versionchanged:: 21.1
            This property now also considers :attr:`business_message`, and
            :attr:`edited_business_message`.

        Tip:
            This property will only ever return objects of type :class:`telegram.Message` or
            :obj:`None`, never :class:`telegram.MaybeInaccessibleMessage` or
            :class:`telegram.InaccessibleMessage`.
            Currently, this is only relevant for :attr:`callback_query`, as
            :attr:`telegram.CallbackQuery.message` is the only attribute considered by this
            property that can be an object of these types.
        """
        if self._effective_message:
            return self._effective_message

        message: Message | None = None

        if self.message:
            message = self.message

        elif self.edited_message:
            message = self.edited_message

        elif self.callback_query:
            if (
                isinstance(cbq_message := self.callback_query.message, Message)
                or cbq_message is None
            ):
                message = cbq_message
            else:
                warn(
                    (
                        "`update.callback_query` is not `None`, but of type "
                        f"`{cbq_message.__class__.__name__}`. This is not considered by "
                        "`Update.effective_message`. Please manually access this attribute "
                        "if necessary."
                    ),
                    stacklevel=2,
                )

        elif self.channel_post:
            message = self.channel_post

        elif self.edited_channel_post:
            message = self.edited_channel_post

        elif self.business_message:
            message = self.business_message

        elif self.edited_business_message:
            message = self.edited_business_message

        self._effective_message = message
        return message

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "Update":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["message"] = de_json_optional(data.get("message"), Message, bot)
        data["edited_message"] = de_json_optional(data.get("edited_message"), Message, bot)
        data["inline_query"] = de_json_optional(data.get("inline_query"), InlineQuery, bot)
        data["chosen_inline_result"] = de_json_optional(
            data.get("chosen_inline_result"), ChosenInlineResult, bot
        )
        data["callback_query"] = de_json_optional(data.get("callback_query"), CallbackQuery, bot)
        data["shipping_query"] = de_json_optional(data.get("shipping_query"), ShippingQuery, bot)
        data["pre_checkout_query"] = de_json_optional(
            data.get("pre_checkout_query"), PreCheckoutQuery, bot
        )
        data["channel_post"] = de_json_optional(data.get("channel_post"), Message, bot)
        data["edited_channel_post"] = de_json_optional(
            data.get("edited_channel_post"), Message, bot
        )
        data["poll"] = de_json_optional(data.get("poll"), Poll, bot)
        data["poll_answer"] = de_json_optional(data.get("poll_answer"), PollAnswer, bot)
        data["my_chat_member"] = de_json_optional(
            data.get("my_chat_member"), ChatMemberUpdated, bot
        )
        data["chat_member"] = de_json_optional(data.get("chat_member"), ChatMemberUpdated, bot)
        data["chat_join_request"] = de_json_optional(
            data.get("chat_join_request"), ChatJoinRequest, bot
        )
        data["chat_boost"] = de_json_optional(data.get("chat_boost"), ChatBoostUpdated, bot)
        data["removed_chat_boost"] = de_json_optional(
            data.get("removed_chat_boost"), ChatBoostRemoved, bot
        )
        data["message_reaction"] = de_json_optional(
            data.get("message_reaction"), MessageReactionUpdated, bot
        )
        data["message_reaction_count"] = de_json_optional(
            data.get("message_reaction_count"), MessageReactionCountUpdated, bot
        )
        data["business_connection"] = de_json_optional(
            data.get("business_connection"), BusinessConnection, bot
        )
        data["business_message"] = de_json_optional(data.get("business_message"), Message, bot)
        data["edited_business_message"] = de_json_optional(
            data.get("edited_business_message"), Message, bot
        )
        data["deleted_business_messages"] = de_json_optional(
            data.get("deleted_business_messages"), BusinessMessagesDeleted, bot
        )
        data["purchased_paid_media"] = de_json_optional(
            data.get("purchased_paid_media"), PaidMediaPurchased, bot
        )

        return super().de_json(data=data, bot=bot)
