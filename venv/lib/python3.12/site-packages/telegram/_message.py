#!/usr/bin/env python
# pylint: disable=too-many-instance-attributes, too-many-arguments
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
"""This module contains an object that represents a Telegram Message."""

import datetime as dtm
import re
from collections.abc import Sequence
from html import escape
from typing import TYPE_CHECKING, TypedDict

from telegram._chat import Chat
from telegram._chatbackground import ChatBackground
from telegram._chatboost import ChatBoostAdded
from telegram._checklists import Checklist, ChecklistTasksAdded, ChecklistTasksDone
from telegram._dice import Dice
from telegram._directmessagepricechanged import DirectMessagePriceChanged
from telegram._directmessagestopic import DirectMessagesTopic
from telegram._files.animation import Animation
from telegram._files.audio import Audio
from telegram._files.contact import Contact
from telegram._files.document import Document
from telegram._files.location import Location
from telegram._files.photosize import PhotoSize
from telegram._files.sticker import Sticker
from telegram._files.venue import Venue
from telegram._files.video import Video
from telegram._files.videonote import VideoNote
from telegram._files.voice import Voice
from telegram._forumtopic import (
    ForumTopicClosed,
    ForumTopicCreated,
    ForumTopicEdited,
    ForumTopicReopened,
    GeneralForumTopicHidden,
    GeneralForumTopicUnhidden,
)
from telegram._games.game import Game
from telegram._gifts import GiftInfo
from telegram._inline.inlinekeyboardmarkup import InlineKeyboardMarkup
from telegram._inputchecklist import InputChecklist
from telegram._linkpreviewoptions import LinkPreviewOptions
from telegram._messageautodeletetimerchanged import MessageAutoDeleteTimerChanged
from telegram._messageentity import MessageEntity
from telegram._paidmedia import PaidMediaInfo
from telegram._paidmessagepricechanged import PaidMessagePriceChanged
from telegram._passport.passportdata import PassportData
from telegram._payment.invoice import Invoice
from telegram._payment.refundedpayment import RefundedPayment
from telegram._payment.successfulpayment import SuccessfulPayment
from telegram._poll import Poll
from telegram._proximityalerttriggered import ProximityAlertTriggered
from telegram._reply import ReplyParameters
from telegram._shared import ChatShared, UsersShared
from telegram._story import Story
from telegram._telegramobject import TelegramObject
from telegram._uniquegift import UniqueGiftInfo
from telegram._user import User
from telegram._utils.argumentparsing import de_json_optional, de_list_optional, parse_sequence_arg
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.defaultvalue import DEFAULT_NONE, DefaultValue
from telegram._utils.entities import parse_message_entities, parse_message_entity
from telegram._utils.strings import TextEncoding
from telegram._utils.types import (
    CorrectOptionID,
    JSONDict,
    MarkdownVersion,
    ODVInput,
    TimePeriod,
)
from telegram._utils.warnings import warn
from telegram._videochat import (
    VideoChatEnded,
    VideoChatParticipantsInvited,
    VideoChatScheduled,
    VideoChatStarted,
)
from telegram._webappdata import WebAppData
from telegram._writeaccessallowed import WriteAccessAllowed
from telegram.constants import ZERO_DATE, MessageAttachmentType, ParseMode
from telegram.helpers import escape_markdown
from telegram.warnings import PTBDeprecationWarning

if TYPE_CHECKING:
    from telegram import (
        Bot,
        ExternalReplyInfo,
        GameHighScore,
        Giveaway,
        GiveawayCompleted,
        GiveawayCreated,
        GiveawayWinners,
        InputMedia,
        InputMediaAudio,
        InputMediaDocument,
        InputMediaPhoto,
        InputMediaVideo,
        InputPaidMedia,
        InputPollOption,
        LabeledPrice,
        MessageId,
        MessageOrigin,
        ReactionType,
        SuggestedPostApprovalFailed,
        SuggestedPostApproved,
        SuggestedPostDeclined,
        SuggestedPostInfo,
        SuggestedPostPaid,
        SuggestedPostParameters,
        SuggestedPostRefunded,
        TextQuote,
    )
    from telegram._utils.types import FileInput, ReplyMarkup


class _ReplyKwargs(TypedDict):
    __slots__ = ("chat_id", "reply_parameters")  # type: ignore[misc]

    chat_id: str | int
    reply_parameters: ReplyParameters


class MaybeInaccessibleMessage(TelegramObject):
    """Base class for Telegram Message Objects.

    Currently, that includes :class:`telegram.Message` and :class:`telegram.InaccessibleMessage`.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`message_id` and :attr:`chat` are equal

    .. versionchanged:: 21.0
       ``__bool__`` is no longer overriden and defaults to Pythons standard implementation.

    .. versionadded:: 20.8

    Args:
        message_id (:obj:`int`): Unique message identifier.
        date (:class:`datetime.datetime`): Date the message was sent in Unix time or 0 in Unix
            time. Converted to :class:`datetime.datetime`

            |datetime_localization|
        chat (:class:`telegram.Chat`): Conversation the message belongs to.

    Attributes:
        message_id (:obj:`int`): Unique message identifier.
        date (:class:`datetime.datetime`): Date the message was sent in Unix time or 0 in Unix
            time. Converted to :class:`datetime.datetime`

            |datetime_localization|
        chat (:class:`telegram.Chat`): Conversation the message belongs to.
    """

    __slots__ = ("chat", "date", "message_id")

    def __init__(
        self,
        chat: Chat,
        message_id: int,
        date: dtm.datetime,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.chat: Chat = chat
        self.message_id: int = message_id
        self.date: dtm.datetime = date

        self._id_attrs = (self.message_id, self.chat)

        self._freeze()

    @property
    def is_accessible(self) -> bool:
        """Convenience attribute. :obj:`True`, if the date is not 0 in Unix time.

        .. versionadded:: 20.8
        """
        return self.date != ZERO_DATE

    @classmethod
    def _de_json(
        cls,
        data: JSONDict | None,
        bot: "Bot | None" = None,
        api_kwargs: JSONDict | None = None,
    ) -> "MaybeInaccessibleMessage | None":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        if cls is MaybeInaccessibleMessage:
            if data["date"] == 0:
                return InaccessibleMessage.de_json(data=data, bot=bot)
            return Message.de_json(data=data, bot=bot)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        # this is to include the Literal from InaccessibleMessage
        if data["date"] == 0:
            data["date"] = ZERO_DATE
        else:
            data["date"] = from_timestamp(data.get("date"), tzinfo=loc_tzinfo)

        data["chat"] = de_json_optional(data.get("chat"), Chat, bot)
        return super()._de_json(data=data, bot=bot, api_kwargs=api_kwargs)


class InaccessibleMessage(MaybeInaccessibleMessage):
    """This object represents an inaccessible message.

    These are messages that are e.g. deleted.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`message_id` and :attr:`chat` are equal

    .. versionadded:: 20.8

    Args:
        message_id (:obj:`int`): Unique message identifier.
        chat (:class:`telegram.Chat`): Chat the message belongs to.

    Attributes:
        message_id (:obj:`int`): Unique message identifier.
        date (:class:`constants.ZERO_DATE`): Always :tg-const:`telegram.constants.ZERO_DATE`.
            The field can be used to differentiate regular and inaccessible messages.
        chat (:class:`telegram.Chat`): Chat the message belongs to.
    """

    __slots__ = ()

    def __init__(
        self,
        chat: Chat,
        message_id: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(chat=chat, message_id=message_id, date=ZERO_DATE, api_kwargs=api_kwargs)
        self._freeze()


class Message(MaybeInaccessibleMessage):
    # fmt: off
    """This object represents a message.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`message_id` and :attr:`chat` are equal.

    Note:
        In Python :keyword:`from` is a reserved word. Use :paramref:`from_user` instead.

    .. versionchanged:: 21.0
       Removed deprecated arguments and attributes ``user_shared``, ``forward_from``,
       ``forward_from_chat``, ``forward_from_message_id``, ``forward_signature``,
       ``forward_sender_name`` and ``forward_date``.

    .. versionchanged:: 20.8
        * This class is now a subclass of :class:`telegram.MaybeInaccessibleMessage`.
        * The :paramref:`pinned_message` now can be either :class:`telegram.Message` or
          :class:`telegram.InaccessibleMessage`.

    .. versionchanged:: 20.0

        * The arguments and attributes ``voice_chat_scheduled``, ``voice_chat_started`` and
          ``voice_chat_ended``, ``voice_chat_participants_invited`` were renamed to
          :paramref:`video_chat_scheduled`/:attr:`video_chat_scheduled`,
          :paramref:`video_chat_started`/:attr:`video_chat_started`,
          :paramref:`video_chat_ended`/:attr:`video_chat_ended` and
          :paramref:`video_chat_participants_invited`/:attr:`video_chat_participants_invited`,
          respectively, in accordance to Bot API 6.0.
        * The following are now keyword-only arguments in Bot methods:
          ``{read, write, connect, pool}_timeout``, ``api_kwargs``, ``contact``, ``quote``,
          ``filename``, ``loaction``, ``venue``. Use a named argument for those,
          and notice that some positional arguments changed position as a result.

    Args:
        message_id (:obj:`int`): Unique message identifier inside this chat. In specific instances
            (e.g., message containing a video sent to a big chat), the server might automatically
            schedule a message instead of sending it immediately. In such cases, this field will be
            ``0`` and the relevant message will be unusable until it is actually sent.
        from_user (:class:`telegram.User`, optional): Sender of the message; may be empty for
            messages sent to channels. For backward compatibility, if the message was sent on
            behalf of a chat, the field contains a fake sender user in non-channel chats.
        sender_chat (:class:`telegram.Chat`, optional): Sender of the message when sent on behalf
            of a chat. For example, the supergroup itself for messages sent by its anonymous
            administrators or a linked channel for messages automatically forwarded to the
            channel's discussion group. For backward compatibility, if the message was sent on
            behalf of a chat, the field from contains a fake sender user in non-channel chats.
        date (:class:`datetime.datetime`): Date the message was sent in Unix time. Converted to
            :class:`datetime.datetime`.

            .. versionchanged:: 20.3
                |datetime_localization|
        chat (:class:`telegram.Chat`): Conversation the message belongs to.
        is_automatic_forward (:obj:`bool`, optional): :obj:`True`, if the message is a channel
            post that was automatically forwarded to the connected discussion group.

            .. versionadded:: 13.9
        reply_to_message (:class:`telegram.Message`, optional): For replies, the original message.
            Note that the Message object in this field will not contain further
            ``reply_to_message`` fields even if it itself is a reply.
        edit_date (:class:`datetime.datetime`, optional): Date the message was last edited in Unix
            time. Converted to :class:`datetime.datetime`.

            .. versionchanged:: 20.3
                |datetime_localization|
        has_protected_content (:obj:`bool`, optional): :obj:`True`, if the message can't be
            forwarded.

            .. versionadded:: 13.9
        is_from_offline (:obj:`bool`, optional): :obj:`True`, if the message was sent
            by an implicit action, for example, as an away or a greeting business message,
            or as a scheduled message.

            .. versionadded:: 21.1
        media_group_id (:obj:`str`, optional): The unique identifier of a media message group this
            message belongs to.
        text (:obj:`str`, optional): For text messages, the actual UTF-8 text of the message,
            0-:tg-const:`telegram.constants.MessageLimit.MAX_TEXT_LENGTH` characters.
        entities (Sequence[:class:`telegram.MessageEntity`], optional): For text messages, special
            entities like usernames, URLs, bot commands, etc. that appear in the text. See
            :attr:`parse_entity` and :attr:`parse_entities` methods for how to use properly.
            This list is empty if the message does not contain entities.

            .. versionchanged:: 20.0
                |sequenceclassargs|

        link_preview_options (:class:`telegram.LinkPreviewOptions`, optional): Options used for
            link preview generation for the message, if it is a text message and link preview
            options were changed.

            .. versionadded:: 20.8

        suggested_post_info (:class:`telegram.SuggestedPostInfo`, optional): Information about
            suggested post parameters if the message is a suggested post in a channel direct
            messages chat. If the message is an approved or declined suggested post, then it can't
            be edited.

            .. versionadded:: 22.4

        effect_id (:obj:`str`, optional): Unique identifier of the message effect added to the
            message.

            .. versionadded:: 21.3

        caption_entities (Sequence[:class:`telegram.MessageEntity`], optional): For messages with a
            Caption. Special entities like usernames, URLs, bot commands, etc. that appear in the
            caption. See :attr:`Message.parse_caption_entity` and :attr:`parse_caption_entities`
            methods for how to use properly. This list is empty if the message does not contain
            caption entities.

            .. versionchanged:: 20.0
                |sequenceclassargs|

        show_caption_above_media (:obj:`bool`, optional): |show_cap_above_med|

            .. versionadded:: 21.3
        audio (:class:`telegram.Audio`, optional): Message is an audio file, information
            about the file.
        document (:class:`telegram.Document`, optional): Message is a general file, information
            about the file.
        animation (:class:`telegram.Animation`, optional): Message is an animation, information
            about the animation. For backward compatibility, when this field is set, the document
            field will also be set.
        game (:class:`telegram.Game`, optional): Message is a game, information about the game.
            :ref:`More about games >> <games-tree>`.
        photo (Sequence[:class:`telegram.PhotoSize`], optional): Message is a photo, available
            sizes of the photo. This list is empty if the message does not contain a photo.

            .. versionchanged:: 20.0
                |sequenceclassargs|

        sticker (:class:`telegram.Sticker`, optional): Message is a sticker, information
            about the sticker.
        story (:class:`telegram.Story`, optional): Message is a forwarded story.

            .. versionadded:: 20.5
        video (:class:`telegram.Video`, optional): Message is a video, information about the
            video.
        voice (:class:`telegram.Voice`, optional): Message is a voice message, information about
            the file.
        video_note (:class:`telegram.VideoNote`, optional): Message is a
            `video note <https://telegram.org/blog/video-messages-and-telescope>`_, information
            about the video message.
        new_chat_members (Sequence[:class:`telegram.User`], optional): New members that were added
            to the group or supergroup and information about them (the bot itself may be one of
            these members). This list is empty if the message does not contain new chat members.

            .. versionchanged:: 20.0
                |sequenceclassargs|

        caption (:obj:`str`, optional): Caption for the animation, audio, document, paid media,
            photo, video
            or voice, 0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters.
        contact (:class:`telegram.Contact`, optional): Message is a shared contact, information
            about the contact.
        location (:class:`telegram.Location`, optional): Message is a shared location, information
            about the location.
        venue (:class:`telegram.Venue`, optional): Message is a venue, information about the
            venue. For backward compatibility, when this field is set, the location field will
            also be set.
        left_chat_member (:class:`telegram.User`, optional): A member was removed from the group,
            information about them (this member may be the bot itself).
        new_chat_title (:obj:`str`, optional): A chat title was changed to this value.
        new_chat_photo (Sequence[:class:`telegram.PhotoSize`], optional): A chat photo was changed
            to this value. This list is empty if the message does not contain a new chat photo.

            .. versionchanged:: 20.0
                |sequenceclassargs|

        delete_chat_photo (:obj:`bool`, optional): Service message: The chat photo was deleted.
        group_chat_created (:obj:`bool`, optional): Service message: The group has been created.
        supergroup_chat_created (:obj:`bool`, optional): Service message: The supergroup has been
            created. This field can't be received in a message coming through updates, because bot
            can't be a member of a supergroup when it is created. It can only be found in
            :attr:`reply_to_message` if someone replies to a very first message in a directly
            created supergroup.
        channel_chat_created (:obj:`bool`, optional): Service message: The channel has been
            created. This field can't be received in a message coming through updates, because bot
            can't be a member of a channel when it is created. It can only be found in
            :attr:`reply_to_message` if someone replies to a very first message in a channel.
        message_auto_delete_timer_changed (:class:`telegram.MessageAutoDeleteTimerChanged`, \
            optional): Service message: auto-delete timer settings changed in the chat.

            .. versionadded:: 13.4
        migrate_to_chat_id (:obj:`int`, optional): The group has been migrated to a supergroup
            with the specified identifier.
        migrate_from_chat_id (:obj:`int`, optional): The supergroup has been migrated from a group
            with the specified identifier.
        pinned_message (:class:`telegram.MaybeInaccessibleMessage`, optional): Specified message
            was pinned. Note that the Message object in this field will not contain further
            :attr:`reply_to_message` fields even if it is itself a reply.

            .. versionchanged:: 20.8
                This attribute now is either :class:`telegram.Message` or
                :class:`telegram.InaccessibleMessage`.
        invoice (:class:`telegram.Invoice`, optional): Message is an invoice for a payment,
            information about the invoice.
            :ref:`More about payments >> <payments-tree>`.
        successful_payment (:class:`telegram.SuccessfulPayment`, optional): Message is a service
            message about a successful payment, information about the payment.
            :ref:`More about payments >> <payments-tree>`.
        connected_website (:obj:`str`, optional): The domain name of the website on which the user
            has logged in.
            `More about Telegram Login >> <https://core.telegram.org/widgets/login>`_.
        author_signature (:obj:`str`, optional): Signature of the post author for messages in
            channels, or the custom title of an anonymous group administrator.
        paid_star_count (:obj:`int`, optional): The number of Telegram Stars that were paid by the
            sender of the message to send it

            .. versionadded:: 22.1
        passport_data (:class:`telegram.PassportData`, optional): Telegram Passport data.
        poll (:class:`telegram.Poll`, optional): Message is a native poll,
            information about the poll.
        dice (:class:`telegram.Dice`, optional): Message is a dice with random value.
        via_bot (:class:`telegram.User`, optional): Bot through which message was sent.
        proximity_alert_triggered (:class:`telegram.ProximityAlertTriggered`, optional): Service
            message. A user in the chat triggered another user's proximity alert while sharing
            Live Location.
        video_chat_scheduled (:class:`telegram.VideoChatScheduled`, optional): Service message:
            video chat scheduled.

            .. versionadded:: 20.0
        video_chat_started (:class:`telegram.VideoChatStarted`, optional): Service message: video
            chat started.

            .. versionadded:: 20.0
        video_chat_ended (:class:`telegram.VideoChatEnded`, optional): Service message: video chat
            ended.

            .. versionadded:: 20.0
        video_chat_participants_invited (:class:`telegram.VideoChatParticipantsInvited` optional):
            Service message: new participants invited to a video chat.

            .. versionadded:: 20.0
        web_app_data (:class:`telegram.WebAppData`, optional): Service message: data sent by a Web
            App.

            .. versionadded:: 20.0
        reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): Inline keyboard attached
            to the message. :paramref:`~telegram.InlineKeyboardButton.login_url` buttons are
            represented as ordinary url buttons.
        is_topic_message (:obj:`bool`, optional): :obj:`True`, if the message is sent to a topic
            in a forum supergroup or a private chat with the bot.

            .. versionadded:: 20.0
        message_thread_id (:obj:`int`, optional): Unique identifier of a message thread or forum
            topic to which the message belongs; for supergroups and private chats only.

            .. versionadded:: 20.0
        forum_topic_created (:class:`telegram.ForumTopicCreated`, optional): Service message:
            forum topic created.

            .. versionadded:: 20.0
        forum_topic_closed (:class:`telegram.ForumTopicClosed`, optional): Service message:
            forum topic closed.

            .. versionadded:: 20.0
        forum_topic_reopened (:class:`telegram.ForumTopicReopened`, optional): Service message:
            forum topic reopened.

            .. versionadded:: 20.0
        forum_topic_edited (:class:`telegram.ForumTopicEdited`, optional): Service message:
            forum topic edited.

            .. versionadded:: 20.0
        general_forum_topic_hidden (:class:`telegram.GeneralForumTopicHidden`, optional):
            Service message: General forum topic hidden.

            .. versionadded:: 20.0
        general_forum_topic_unhidden (:class:`telegram.GeneralForumTopicUnhidden`, optional):
            Service message: General forum topic unhidden.

            .. versionadded:: 20.0
        write_access_allowed (:class:`telegram.WriteAccessAllowed`, optional): Service message:
            the user allowed the bot to write messages after adding it to the attachment or side
            menu, launching a Web App from a link, or accepting an explicit request from a Web App
            sent by the method
            `requestWriteAccess <https://core.telegram.org/bots/webapps#initializing-mini-apps>`_.

            .. versionadded:: 20.0
        has_media_spoiler (:obj:`bool`, optional): :obj:`True`, if the message media is covered
            by a spoiler animation.

            .. versionadded:: 20.0
        checklist (:class:`telegram.Checklist`, optional): Message is a checklist

            .. versionadded:: 22.3
        users_shared (:class:`telegram.UsersShared`, optional): Service message: users were shared
            with the bot

            .. versionadded:: 20.8
        chat_shared (:class:`telegram.ChatShared`, optional):Service message: a chat was shared
            with the bot.

            .. versionadded:: 20.1
        gift (:class:`telegram.GiftInfo`, optional): Service message: a regular gift was sent
            or received.

            .. versionadded:: 22.1
        unique_gift (:class:`telegram.UniqueGiftInfo`, optional): Service message: a unique gift
            was sent or received

            .. versionadded:: 22.1
        gift_upgrade_sent (:class:`telegram.GiftInfo`, optional): Service message: upgrade of a
            gift was purchased after the gift was sent

            .. versionadded:: 22.6
        giveaway_created (:class:`telegram.GiveawayCreated`, optional): Service message: a
            scheduled giveaway was created

            .. versionadded:: 20.8
        giveaway (:class:`telegram.Giveaway`, optional): The message is a scheduled giveaway
            message

            .. versionadded:: 20.8
        giveaway_winners (:class:`telegram.GiveawayWinners`, optional): A giveaway with public
            winners was completed

            .. versionadded:: 20.8
        giveaway_completed (:class:`telegram.GiveawayCompleted`, optional): Service message: a
            giveaway without public winners was completed

            .. versionadded:: 20.8
        paid_message_price_changed (:class:`telegram.PaidMessagePriceChanged`, optional): Service
            message: the price for paid messages has changed in the chat

            .. versionadded:: 22.1
        suggested_post_approved (:class:`telegram.SuggestedPostApproved`, optional): Service
            message: a suggested post was approved.

            .. versionadded:: 22.4
        suggested_post_approval_failed (:class:`telegram.SuggestedPostApproved`, optional): Service
            message: approval of a suggested post has failed.

            .. versionadded:: 22.4
        suggested_post_declined (:class:`telegram.SuggestedPostDeclined`, optional): Service
            message: a suggested post was declined.

            .. versionadded:: 22.4
        suggested_post_paid (:class:`telegram.SuggestedPostPaid`, optional): Service
            message: payment for a suggested post was received.

            .. versionadded:: 22.4
        suggested_post_refunded (:class:`telegram.SuggestedPostRefunded`, optional): Service
            message: payment for a suggested post was refunded.

            .. versionadded:: 22.4
        external_reply (:class:`telegram.ExternalReplyInfo`, optional): Information about the
            message that is being replied to, which may come from another chat or forum topic.

            .. versionadded:: 20.8
        quote (:class:`telegram.TextQuote`, optional): For replies that quote part of the original
            message, the quoted part of the message.

            .. versionadded:: 20.8
        forward_origin (:class:`telegram.MessageOrigin`, optional): Information about the original
            message for forwarded messages

            .. versionadded:: 20.8
        reply_to_story (:class:`telegram.Story`, optional): For replies to a story, the original
            story.

            .. versionadded:: 21.0
        boost_added (:class:`telegram.ChatBoostAdded`, optional): Service message: user boosted
            the chat.

            .. versionadded:: 21.0
        sender_boost_count (:obj:`int`, optional): If the sender of the
            message boosted the chat, the number of boosts added by the user.

            .. versionadded:: 21.0
        business_connection_id (:obj:`str`, optional): Unique identifier of the business connection
            from which the message was received. If non-empty, the message belongs to a chat of the
            corresponding business account that is independent from any potential bot chat which
            might share the same identifier.

            .. versionadded:: 21.1

        sender_business_bot (:class:`telegram.User`, optional): The bot that actually sent the
            message on behalf of the business account. Available only for outgoing messages sent
            on behalf of the connected business account.

            .. versionadded:: 21.1

        chat_background_set  (:class:`telegram.ChatBackground`, optional): Service message: chat
            background set.

            .. versionadded:: 21.2
        checklist_tasks_done (:class:`telegram.ChecklistTasksDone`, optional): Service message:
            some tasks in a checklist were marked as done or not done

            .. versionadded:: 22.3
        checklist_tasks_added (:class:`telegram.ChecklistTasksAdded`, optional): Service message:
            tasks were added to a checklist

            .. versionadded:: 22.3
        paid_media (:class:`telegram.PaidMediaInfo`, optional): Message contains paid media;
            information about the paid media.

            .. versionadded:: 21.4
        refunded_payment (:class:`telegram.RefundedPayment`, optional): Message is a service
            message about a refunded payment, information about the payment.

            .. versionadded:: 21.4
        direct_message_price_changed (:class:`telegram.DirectMessagePriceChanged`, optional):
            Service message: the price for paid messages in the corresponding direct messages chat
            of a channel has changed.

            .. versionadded:: 22.3
        is_paid_post (:obj:`bool`, optional): :obj:`True`, if the message is a paid post. Note that
            such posts must not be deleted for 24 hours to receive the payment and can't be edited.

            .. versionadded:: 22.4
        direct_messages_topic (:class:`telegram.DirectMessagesTopic`, optional): Information about
            the direct messages chat topic that contains the message.

            .. versionadded:: 22.4
        reply_to_checklist_task_id (:obj:`int`, optional): Identifier of the specific checklist
            task that is being replied to.

            .. versionadded:: 22.4

    Attributes:
        message_id (:obj:`int`): Unique message identifier inside this chat. In specific instances
            (e.g., message containing a video sent to a big chat), the server might automatically
            schedule a message instead of sending it immediately. In such cases, this field will be
            ``0`` and the relevant message will be unusable until it is actually sent.
        from_user (:class:`telegram.User`): Optional. Sender of the message; may be empty for
            messages sent to channels. For backward compatibility, if the message was sent on
            behalf of a chat, the field contains a fake sender user in non-channel chats.
        sender_chat (:class:`telegram.Chat`): Optional. Sender of the message when sent on behalf
            of a chat. For example, the supergroup itself for messages sent by its anonymous
            administrators or a linked channel for messages automatically forwarded to the
            channel's discussion group. For backward compatibility, if the message was sent on
            behalf of a chat, the field from contains a fake sender user in non-channel chats.
        date (:class:`datetime.datetime`): Date the message was sent in Unix time. Converted to
            :class:`datetime.datetime`.

            .. versionchanged:: 20.3
                |datetime_localization|
        chat (:class:`telegram.Chat`): Conversation the message belongs to.
        is_automatic_forward (:obj:`bool`): Optional. :obj:`True`, if the message is a channel
            post that was automatically forwarded to the connected discussion group.

            .. versionadded:: 13.9
        reply_to_message (:class:`telegram.Message`): Optional. For replies, the original message.
            Note that the Message object in this field will not contain further
            ``reply_to_message`` fields even if it itself is a reply.
        edit_date (:class:`datetime.datetime`): Optional. Date the message was last edited in Unix
            time. Converted to :class:`datetime.datetime`.

            .. versionchanged:: 20.3
                |datetime_localization|
        has_protected_content (:obj:`bool`): Optional. :obj:`True`, if the message can't be
            forwarded.

            .. versionadded:: 13.9
        is_from_offline (:obj:`bool`): Optional. :obj:`True`, if the message was sent
            by an implicit action, for example, as an away or a greeting business message,
            or as a scheduled message.

            .. versionadded:: 21.1
        media_group_id (:obj:`str`): Optional. The unique identifier of a media message group this
            message belongs to.
        text (:obj:`str`): Optional. For text messages, the actual UTF-8 text of the message,
            0-:tg-const:`telegram.constants.MessageLimit.MAX_TEXT_LENGTH` characters.
        entities (tuple[:class:`telegram.MessageEntity`]): Optional. For text messages, special
            entities like usernames, URLs, bot commands, etc. that appear in the text. See
            :attr:`parse_entity` and :attr:`parse_entities` methods for how to use properly.
            This list is empty if the message does not contain entities.

            .. versionchanged:: 20.0
                |tupleclassattrs|

        link_preview_options (:class:`telegram.LinkPreviewOptions`): Optional. Options used for
            link preview generation for the message, if it is a text message and link preview
            options were changed.

            .. versionadded:: 20.8

        suggested_post_info (:class:`telegram.SuggestedPostInfo`): Optional. Information about
            suggested post parameters if the message is a suggested post in a channel direct
            messages chat. If the message is an approved or declined suggested post, then it can't
            be edited.

            .. versionadded:: 22.4

        effect_id (:obj:`str`): Optional. Unique identifier of the message effect added to the
            message.

            .. versionadded:: 21.3

        caption_entities (tuple[:class:`telegram.MessageEntity`]): Optional. For messages with a
            Caption. Special entities like usernames, URLs, bot commands, etc. that appear in the
            caption. See :attr:`Message.parse_caption_entity` and :attr:`parse_caption_entities`
            methods for how to use properly. This list is empty if the message does not contain
            caption entities.

            .. versionchanged:: 20.0
                |tupleclassattrs|

        show_caption_above_media (:obj:`bool`): Optional. |show_cap_above_med|

            .. versionadded:: 21.3
        audio (:class:`telegram.Audio`): Optional. Message is an audio file, information
            about the file.

            .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`
        document (:class:`telegram.Document`): Optional. Message is a general file, information
            about the file.

            .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`
        animation (:class:`telegram.Animation`): Optional. Message is an animation, information
            about the animation. For backward compatibility, when this field is set, the document
            field will also be set.

            .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`
        game (:class:`telegram.Game`): Optional. Message is a game, information about the game.
            :ref:`More about games >> <games-tree>`.
        photo (tuple[:class:`telegram.PhotoSize`]): Optional. Message is a photo, available
            sizes of the photo. This list is empty if the message does not contain a photo.

            .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

            .. versionchanged:: 20.0
                |tupleclassattrs|

        sticker (:class:`telegram.Sticker`): Optional. Message is a sticker, information
            about the sticker.

            .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`
        story (:class:`telegram.Story`): Optional. Message is a forwarded story.

            .. versionadded:: 20.5
        video (:class:`telegram.Video`): Optional. Message is a video, information about the
            video.

            .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`
        voice (:class:`telegram.Voice`): Optional. Message is a voice message, information about
            the file.

            .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`
        video_note (:class:`telegram.VideoNote`): Optional. Message is a
            `video note <https://telegram.org/blog/video-messages-and-telescope>`_, information
            about the video message.

            .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`
        new_chat_members (tuple[:class:`telegram.User`]): Optional. New members that were added
            to the group or supergroup and information about them (the bot itself may be one of
            these members). This list is empty if the message does not contain new chat members.

            .. versionchanged:: 20.0
                |tupleclassattrs|
        caption (:obj:`str`): Optional. Caption for the animation, audio, document, paid media,
            photo, video
            or voice, 0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters.
        contact (:class:`telegram.Contact`): Optional. Message is a shared contact, information
            about the contact.
        location (:class:`telegram.Location`): Optional. Message is a shared location, information
            about the location.
        venue (:class:`telegram.Venue`): Optional. Message is a venue, information about the
            venue. For backward compatibility, when this field is set, the location field will
            also be set.
        left_chat_member (:class:`telegram.User`): Optional. A member was removed from the group,
            information about them (this member may be the bot itself).
        new_chat_title (:obj:`str`): Optional. A chat title was changed to this value.
        new_chat_photo (tuple[:class:`telegram.PhotoSize`]): A chat photo was changed to
            this value. This list is empty if the message does not contain a new chat photo.

            .. versionchanged:: 20.0
                |tupleclassattrs|

        delete_chat_photo (:obj:`bool`): Optional. Service message: The chat photo was deleted.
        group_chat_created (:obj:`bool`): Optional. Service message: The group has been created.
        supergroup_chat_created (:obj:`bool`): Optional. Service message: The supergroup has been
            created. This field can't be received in a message coming through updates, because bot
            can't be a member of a supergroup when it is created. It can only be found in
            :attr:`reply_to_message` if someone replies to a very first message in a directly
            created supergroup.
        channel_chat_created (:obj:`bool`): Optional. Service message: The channel has been
            created. This field can't be received in a message coming through updates, because bot
            can't be a member of a channel when it is created. It can only be found in
            :attr:`reply_to_message` if someone replies to a very first message in a channel.
        message_auto_delete_timer_changed (:class:`telegram.MessageAutoDeleteTimerChanged`):
            Optional. Service message: auto-delete timer settings changed in the chat.

            .. versionadded:: 13.4
        migrate_to_chat_id (:obj:`int`): Optional. The group has been migrated to a supergroup
            with the specified identifier.
        migrate_from_chat_id (:obj:`int`): Optional. The supergroup has been migrated from a group
            with the specified identifier.
        pinned_message (:class:`telegram.MaybeInaccessibleMessage`): Optional. Specified message
            was pinned. Note that the Message object in this field will not contain further
            :attr:`reply_to_message` fields even if it is itself a reply.

            .. versionchanged:: 20.8
                This attribute now is either :class:`telegram.Message` or
                :class:`telegram.InaccessibleMessage`.
        invoice (:class:`telegram.Invoice`): Optional. Message is an invoice for a payment,
            information about the invoice.
            :ref:`More about payments >> <payments-tree>`.
        successful_payment (:class:`telegram.SuccessfulPayment`): Optional. Message is a service
            message about a successful payment, information about the payment.
            :ref:`More about payments >> <payments-tree>`.
        connected_website (:obj:`str`): Optional. The domain name of the website on which the user
            has logged in.
            `More about Telegram Login >> <https://core.telegram.org/widgets/login>`_.
        author_signature (:obj:`str`): Optional. Signature of the post author for messages in
            channels, or the custom title of an anonymous group administrator.
        paid_star_count (:obj:`int`): Optional. The number of Telegram Stars that were paid by the
            sender of the message to send it

            .. versionadded:: 22.1
        passport_data (:class:`telegram.PassportData`): Optional. Telegram Passport data.

            Examples:
                :any:`Passport Bot <examples.passportbot>`
        poll (:class:`telegram.Poll`): Optional. Message is a native poll,
            information about the poll.
        dice (:class:`telegram.Dice`): Optional. Message is a dice with random value.
        via_bot (:class:`telegram.User`): Optional. Bot through which message was sent.
        proximity_alert_triggered (:class:`telegram.ProximityAlertTriggered`): Optional. Service
            message. A user in the chat triggered another user's proximity alert while sharing
            Live Location.
        video_chat_scheduled (:class:`telegram.VideoChatScheduled`): Optional. Service message:
            video chat scheduled.

            .. versionadded:: 20.0
        video_chat_started (:class:`telegram.VideoChatStarted`): Optional. Service message: video
            chat started.

            .. versionadded:: 20.0
        video_chat_ended (:class:`telegram.VideoChatEnded`): Optional. Service message: video chat
            ended.

            .. versionadded:: 20.0
        video_chat_participants_invited (:class:`telegram.VideoChatParticipantsInvited`): Optional.
            Service message: new participants invited to a video chat.

            .. versionadded:: 20.0
        web_app_data (:class:`telegram.WebAppData`): Optional. Service message: data sent by a Web
            App.

            .. versionadded:: 20.0
        reply_markup (:class:`telegram.InlineKeyboardMarkup`): Optional. Inline keyboard attached
            to the message. :paramref:`~telegram.InlineKeyboardButton.login_url` buttons are
            represented as ordinary url buttons.
        is_topic_message (:obj:`bool`): Optional. :obj:`True`, if the message is sent to a topic
            in a forum supergroup or a private chat with the bot.

            .. versionadded:: 20.0
        message_thread_id (:obj:`int`): Optional. Unique identifier of a message thread or forum
            topic to which the message belongs; for supergroups and private chats only.

            .. versionadded:: 20.0
        forum_topic_created (:class:`telegram.ForumTopicCreated`): Optional. Service message:
            forum topic created.

            .. versionadded:: 20.0
        forum_topic_closed (:class:`telegram.ForumTopicClosed`): Optional. Service message:
            forum topic closed.

            .. versionadded:: 20.0
        forum_topic_reopened (:class:`telegram.ForumTopicReopened`): Optional. Service message:
            forum topic reopened.

            .. versionadded:: 20.0
        forum_topic_edited (:class:`telegram.ForumTopicEdited`): Optional. Service message:
            forum topic edited.

            .. versionadded:: 20.0
        general_forum_topic_hidden (:class:`telegram.GeneralForumTopicHidden`): Optional.
            Service message: General forum topic hidden.

            .. versionadded:: 20.0
        general_forum_topic_unhidden (:class:`telegram.GeneralForumTopicUnhidden`): Optional.
            Service message: General forum topic unhidden.

            .. versionadded:: 20.0
        write_access_allowed (:class:`telegram.WriteAccessAllowed`): Optional. Service message:
            the user allowed the bot added to the attachment menu to write messages.

            .. versionadded:: 20.0
        has_media_spoiler (:obj:`bool`): Optional. :obj:`True`, if the message media is covered
            by a spoiler animation.

            .. versionadded:: 20.0
        checklist (:class:`telegram.Checklist`): Optional. Message is a checklist

            .. versionadded:: 22.3
        users_shared (:class:`telegram.UsersShared`): Optional. Service message: users were shared
            with the bot

            .. versionadded:: 20.8
        chat_shared (:class:`telegram.ChatShared`): Optional. Service message: a chat was shared
            with the bot.

            .. versionadded:: 20.1
        gift (:class:`telegram.GiftInfo`): Optional. Service message: a regular gift was sent
            or received.

            .. versionadded:: 22.1
        unique_gift (:class:`telegram.UniqueGiftInfo`): Optional. Service message: a unique gift
            was sent or received

            .. versionadded:: 22.1
        gift_upgrade_sent (:class:`telegram.GiftInfo`): Optional. Service message: upgrade of a
            gift was purchased after the gift was sent

            .. versionadded:: 22.6
        giveaway_created (:class:`telegram.GiveawayCreated`): Optional. Service message: a
            scheduled giveaway was created

            .. versionadded:: 20.8
        giveaway (:class:`telegram.Giveaway`): Optional. The message is a scheduled giveaway
            message

            .. versionadded:: 20.8
        giveaway_winners (:class:`telegram.GiveawayWinners`): Optional. A giveaway with public
            winners was completed

            .. versionadded:: 20.8
        giveaway_completed (:class:`telegram.GiveawayCompleted`): Optional. Service message: a
            giveaway without public winners was completed

            .. versionadded:: 20.8
        paid_message_price_changed (:class:`telegram.PaidMessagePriceChanged`): Optional. Service
            message: the price for paid messages has changed in the chat

            .. versionadded:: 22.1
        suggested_post_approved (:class:`telegram.SuggestedPostApproved`): Optional. Service
            message: a suggested post was approved.

            .. versionadded:: 22.4
        suggested_post_approval_failed (:class:`telegram.SuggestedPostApproved`): Optional. Service
            message: approval of a suggested post has failed.

            .. versionadded:: 22.4
        suggested_post_declined (:class:`telegram.SuggestedPostDeclined`): Optional. Service
            message: a suggested post was declined.

            .. versionadded:: 22.4
        suggested_post_paid (:class:`telegram.SuggestedPostPaid`): Optional. Service
            message: payment for a suggested post was received.

            .. versionadded:: 22.4
        suggested_post_refunded (:class:`telegram.SuggestedPostRefunded`): Optional. Service
            message: payment for a suggested post was refunded.

            .. versionadded:: 22.4
        external_reply (:class:`telegram.ExternalReplyInfo`): Optional. Information about the
            message that is being replied to, which may come from another chat or forum topic.

            .. versionadded:: 20.8
        quote (:class:`telegram.TextQuote`): Optional. For replies that quote part of the original
            message, the quoted part of the message.

            .. versionadded:: 20.8
        forward_origin (:class:`telegram.MessageOrigin`): Optional. Information about the original
            message for forwarded messages

            .. versionadded:: 20.8
        reply_to_story (:class:`telegram.Story`): Optional. For replies to a story, the original
            story.

            .. versionadded:: 21.0
        boost_added (:class:`telegram.ChatBoostAdded`): Optional. Service message: user boosted
            the chat.

            .. versionadded:: 21.0
        sender_boost_count (:obj:`int`): Optional. If the sender of the
            message boosted the chat, the number of boosts added by the user.

            .. versionadded:: 21.0

        business_connection_id (:obj:`str`): Optional. Unique identifier of the business connection
            from which the message was received. If non-empty, the message belongs to a chat of the
            corresponding business account that is independent from any potential bot chat which
            might share the same identifier.

            .. versionadded:: 21.1

        sender_business_bot (:class:`telegram.User`): Optional. The bot that actually sent the
            message on behalf of the business account. Available only for outgoing messages sent
            on behalf of the connected business account.

            .. versionadded:: 21.1

        chat_background_set (:class:`telegram.ChatBackground`): Optional. Service message: chat
            background set

            .. versionadded:: 21.2
        checklist_tasks_done (:class:`telegram.ChecklistTasksDone`): Optional. Service message:
            some tasks in a checklist were marked as done or not done

            .. versionadded:: 22.3
        checklist_tasks_added (:class:`telegram.ChecklistTasksAdded`): Optional. Service message:
            tasks were added to a checklist

            .. versionadded:: 22.3
        paid_media (:class:`telegram.PaidMediaInfo`): Optional. Message contains paid media;
            information about the paid media.

            .. versionadded:: 21.4
        refunded_payment (:class:`telegram.RefundedPayment`): Optional. Message is a service
            message about a refunded payment, information about the payment.

            .. versionadded:: 21.4
        direct_message_price_changed (:class:`telegram.DirectMessagePriceChanged`):
            Optional. Service message: the price for paid messages in the corresponding direct
            messages chat of a channel has changed.

            .. versionadded:: 22.3
        is_paid_post (:obj:`bool`): Optional. :obj:`True`, if the message is a paid post. Note that
            such posts must not be deleted for 24 hours to receive the payment and can't be edited.

            .. versionadded:: 22.4
        direct_messages_topic (:class:`telegram.DirectMessagesTopic`): Optional. Information about
            the direct messages chat topic that contains the message.

            .. versionadded:: 22.4
        reply_to_checklist_task_id (:obj:`int`): Optional. Identifier of the specific checklist
            task that is being replied to.

            .. versionadded:: 22.4

    .. |custom_emoji_no_md1_support| replace:: Since custom emoji entities are not supported by
       :attr:`~telegram.constants.ParseMode.MARKDOWN`, this method now raises a
       :exc:`ValueError` when encountering a custom emoji.

    .. |blockquote_no_md1_support| replace:: Since block quotation entities are not supported
       by :attr:`~telegram.constants.ParseMode.MARKDOWN`, this method now raises a
       :exc:`ValueError` when encountering a block quotation.

    .. |reply_same_thread| replace:: If :paramref:`message_thread_id` is not provided,
       this will reply to the same thread (topic) of the original message.

    .. |quote_removed| replace:: Removed deprecated parameter ``quote``. Use :paramref:`do_quote`
         instead.
    """

    # fmt: on
    __slots__ = (
        "_effective_attachment",
        "animation",
        "audio",
        "author_signature",
        "boost_added",
        "business_connection_id",
        "caption",
        "caption_entities",
        "channel_chat_created",
        "chat_background_set",
        "chat_shared",
        "checklist",
        "checklist_tasks_added",
        "checklist_tasks_done",
        "connected_website",
        "contact",
        "delete_chat_photo",
        "dice",
        "direct_message_price_changed",
        "direct_messages_topic",
        "document",
        "edit_date",
        "effect_id",
        "entities",
        "external_reply",
        "forum_topic_closed",
        "forum_topic_created",
        "forum_topic_edited",
        "forum_topic_reopened",
        "forward_origin",
        "from_user",
        "game",
        "general_forum_topic_hidden",
        "general_forum_topic_unhidden",
        "gift",
        "gift_upgrade_sent",
        "giveaway",
        "giveaway_completed",
        "giveaway_created",
        "giveaway_winners",
        "group_chat_created",
        "has_media_spoiler",
        "has_protected_content",
        "invoice",
        "is_automatic_forward",
        "is_from_offline",
        "is_paid_post",
        "is_topic_message",
        "left_chat_member",
        "link_preview_options",
        "location",
        "media_group_id",
        "message_auto_delete_timer_changed",
        "message_thread_id",
        "migrate_from_chat_id",
        "migrate_to_chat_id",
        "new_chat_members",
        "new_chat_photo",
        "new_chat_title",
        "paid_media",
        "paid_message_price_changed",
        "paid_star_count",
        "passport_data",
        "photo",
        "pinned_message",
        "poll",
        "proximity_alert_triggered",
        "quote",
        "refunded_payment",
        "reply_markup",
        "reply_to_checklist_task_id",
        "reply_to_message",
        "reply_to_story",
        "sender_boost_count",
        "sender_business_bot",
        "sender_chat",
        "show_caption_above_media",
        "sticker",
        "story",
        "successful_payment",
        "suggested_post_approval_failed",
        "suggested_post_approved",
        "suggested_post_declined",
        "suggested_post_info",
        "suggested_post_paid",
        "suggested_post_refunded",
        "supergroup_chat_created",
        "text",
        "unique_gift",
        "users_shared",
        "venue",
        "via_bot",
        "video",
        "video_chat_ended",
        "video_chat_participants_invited",
        "video_chat_scheduled",
        "video_chat_started",
        "video_note",
        "voice",
        "web_app_data",
        "write_access_allowed",
    )

    def __init__(
        self,
        message_id: int,
        date: dtm.datetime,
        chat: Chat,
        from_user: User | None = None,
        reply_to_message: "Message | None" = None,
        edit_date: dtm.datetime | None = None,
        text: str | None = None,
        entities: Sequence["MessageEntity"] | None = None,
        caption_entities: Sequence["MessageEntity"] | None = None,
        audio: Audio | None = None,
        document: Document | None = None,
        game: Game | None = None,
        photo: Sequence[PhotoSize] | None = None,
        sticker: Sticker | None = None,
        video: Video | None = None,
        voice: Voice | None = None,
        video_note: VideoNote | None = None,
        new_chat_members: Sequence[User] | None = None,
        caption: str | None = None,
        contact: "Contact | None" = None,
        location: "Location | None" = None,
        venue: Venue | None = None,
        left_chat_member: User | None = None,
        new_chat_title: str | None = None,
        new_chat_photo: Sequence[PhotoSize] | None = None,
        delete_chat_photo: bool | None = None,
        group_chat_created: bool | None = None,
        supergroup_chat_created: bool | None = None,
        channel_chat_created: bool | None = None,
        migrate_to_chat_id: int | None = None,
        migrate_from_chat_id: int | None = None,
        pinned_message: MaybeInaccessibleMessage | None = None,
        invoice: Invoice | None = None,
        successful_payment: SuccessfulPayment | None = None,
        author_signature: str | None = None,
        media_group_id: str | None = None,
        connected_website: str | None = None,
        animation: Animation | None = None,
        passport_data: PassportData | None = None,
        poll: Poll | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        dice: Dice | None = None,
        via_bot: User | None = None,
        proximity_alert_triggered: ProximityAlertTriggered | None = None,
        sender_chat: Chat | None = None,
        video_chat_started: VideoChatStarted | None = None,
        video_chat_ended: VideoChatEnded | None = None,
        video_chat_participants_invited: VideoChatParticipantsInvited | None = None,
        message_auto_delete_timer_changed: MessageAutoDeleteTimerChanged | None = None,
        video_chat_scheduled: VideoChatScheduled | None = None,
        is_automatic_forward: bool | None = None,
        has_protected_content: bool | None = None,
        web_app_data: WebAppData | None = None,
        is_topic_message: bool | None = None,
        message_thread_id: int | None = None,
        forum_topic_created: ForumTopicCreated | None = None,
        forum_topic_closed: ForumTopicClosed | None = None,
        forum_topic_reopened: ForumTopicReopened | None = None,
        forum_topic_edited: ForumTopicEdited | None = None,
        general_forum_topic_hidden: GeneralForumTopicHidden | None = None,
        general_forum_topic_unhidden: GeneralForumTopicUnhidden | None = None,
        write_access_allowed: WriteAccessAllowed | None = None,
        has_media_spoiler: bool | None = None,
        chat_shared: ChatShared | None = None,
        story: Story | None = None,
        giveaway: "Giveaway | None" = None,
        giveaway_completed: "GiveawayCompleted | None" = None,
        giveaway_created: "GiveawayCreated | None" = None,
        giveaway_winners: "GiveawayWinners | None" = None,
        users_shared: UsersShared | None = None,
        link_preview_options: LinkPreviewOptions | None = None,
        external_reply: "ExternalReplyInfo | None" = None,
        quote: "TextQuote | None" = None,
        forward_origin: "MessageOrigin | None" = None,
        reply_to_story: Story | None = None,
        boost_added: ChatBoostAdded | None = None,
        sender_boost_count: int | None = None,
        business_connection_id: str | None = None,
        sender_business_bot: User | None = None,
        is_from_offline: bool | None = None,
        chat_background_set: ChatBackground | None = None,
        effect_id: str | None = None,
        show_caption_above_media: bool | None = None,
        paid_media: PaidMediaInfo | None = None,
        refunded_payment: RefundedPayment | None = None,
        gift: GiftInfo | None = None,
        unique_gift: UniqueGiftInfo | None = None,
        paid_message_price_changed: PaidMessagePriceChanged | None = None,
        paid_star_count: int | None = None,
        direct_message_price_changed: DirectMessagePriceChanged | None = None,
        checklist: Checklist | None = None,
        checklist_tasks_done: ChecklistTasksDone | None = None,
        checklist_tasks_added: ChecklistTasksAdded | None = None,
        is_paid_post: bool | None = None,
        direct_messages_topic: DirectMessagesTopic | None = None,
        reply_to_checklist_task_id: int | None = None,
        suggested_post_declined: "SuggestedPostDeclined | None" = None,
        suggested_post_paid: "SuggestedPostPaid | None" = None,
        suggested_post_refunded: "SuggestedPostRefunded | None" = None,
        suggested_post_info: "SuggestedPostInfo | None" = None,
        suggested_post_approved: "SuggestedPostApproved | None" = None,
        suggested_post_approval_failed: "SuggestedPostApprovalFailed | None" = None,
        gift_upgrade_sent: GiftInfo | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(chat=chat, message_id=message_id, date=date, api_kwargs=api_kwargs)

        with self._unfrozen():
            # Required
            self.message_id: int = message_id
            # Optionals
            self.from_user: User | None = from_user
            self.sender_chat: Chat | None = sender_chat
            self.date: dtm.datetime = date
            self.chat: Chat = chat
            self.is_automatic_forward: bool | None = is_automatic_forward
            self.reply_to_message: Message | None = reply_to_message
            self.edit_date: dtm.datetime | None = edit_date
            self.has_protected_content: bool | None = has_protected_content
            self.text: str | None = text
            self.entities: tuple[MessageEntity, ...] = parse_sequence_arg(entities)
            self.caption_entities: tuple[MessageEntity, ...] = parse_sequence_arg(caption_entities)
            self.audio: Audio | None = audio
            self.game: Game | None = game
            self.document: Document | None = document
            self.photo: tuple[PhotoSize, ...] = parse_sequence_arg(photo)
            self.sticker: Sticker | None = sticker
            self.video: Video | None = video
            self.voice: Voice | None = voice
            self.video_note: VideoNote | None = video_note
            self.caption: str | None = caption
            self.contact: Contact | None = contact
            self.location: Location | None = location
            self.venue: Venue | None = venue
            self.new_chat_members: tuple[User, ...] = parse_sequence_arg(new_chat_members)
            self.left_chat_member: User | None = left_chat_member
            self.new_chat_title: str | None = new_chat_title
            self.new_chat_photo: tuple[PhotoSize, ...] = parse_sequence_arg(new_chat_photo)
            self.delete_chat_photo: bool | None = bool(delete_chat_photo)
            self.group_chat_created: bool | None = bool(group_chat_created)
            self.supergroup_chat_created: bool | None = bool(supergroup_chat_created)
            self.migrate_to_chat_id: int | None = migrate_to_chat_id
            self.migrate_from_chat_id: int | None = migrate_from_chat_id
            self.channel_chat_created: bool | None = bool(channel_chat_created)
            self.message_auto_delete_timer_changed: MessageAutoDeleteTimerChanged | None = (
                message_auto_delete_timer_changed
            )
            self.pinned_message: MaybeInaccessibleMessage | None = pinned_message
            self.invoice: Invoice | None = invoice
            self.successful_payment: SuccessfulPayment | None = successful_payment
            self.connected_website: str | None = connected_website
            self.author_signature: str | None = author_signature
            self.media_group_id: str | None = media_group_id
            self.animation: Animation | None = animation
            self.passport_data: PassportData | None = passport_data
            self.poll: Poll | None = poll
            self.dice: Dice | None = dice
            self.via_bot: User | None = via_bot
            self.proximity_alert_triggered: ProximityAlertTriggered | None = (
                proximity_alert_triggered
            )
            self.video_chat_scheduled: VideoChatScheduled | None = video_chat_scheduled
            self.video_chat_started: VideoChatStarted | None = video_chat_started
            self.video_chat_ended: VideoChatEnded | None = video_chat_ended
            self.video_chat_participants_invited: VideoChatParticipantsInvited | None = (
                video_chat_participants_invited
            )
            self.reply_markup: InlineKeyboardMarkup | None = reply_markup
            self.web_app_data: WebAppData | None = web_app_data
            self.is_topic_message: bool | None = is_topic_message
            self.message_thread_id: int | None = message_thread_id
            self.forum_topic_created: ForumTopicCreated | None = forum_topic_created
            self.forum_topic_closed: ForumTopicClosed | None = forum_topic_closed
            self.forum_topic_reopened: ForumTopicReopened | None = forum_topic_reopened
            self.forum_topic_edited: ForumTopicEdited | None = forum_topic_edited
            self.general_forum_topic_hidden: GeneralForumTopicHidden | None = (
                general_forum_topic_hidden
            )
            self.general_forum_topic_unhidden: GeneralForumTopicUnhidden | None = (
                general_forum_topic_unhidden
            )
            self.write_access_allowed: WriteAccessAllowed | None = write_access_allowed
            self.has_media_spoiler: bool | None = has_media_spoiler
            self.checklist: Checklist | None = checklist
            self.users_shared: UsersShared | None = users_shared
            self.chat_shared: ChatShared | None = chat_shared
            self.story: Story | None = story
            self.giveaway: Giveaway | None = giveaway
            self.giveaway_completed: GiveawayCompleted | None = giveaway_completed
            self.giveaway_created: GiveawayCreated | None = giveaway_created
            self.giveaway_winners: GiveawayWinners | None = giveaway_winners
            self.link_preview_options: LinkPreviewOptions | None = link_preview_options
            self.external_reply: ExternalReplyInfo | None = external_reply
            self.quote: TextQuote | None = quote
            self.forward_origin: MessageOrigin | None = forward_origin
            self.reply_to_story: Story | None = reply_to_story
            self.boost_added: ChatBoostAdded | None = boost_added
            self.sender_boost_count: int | None = sender_boost_count
            self.business_connection_id: str | None = business_connection_id
            self.sender_business_bot: User | None = sender_business_bot
            self.is_from_offline: bool | None = is_from_offline
            self.chat_background_set: ChatBackground | None = chat_background_set
            self.checklist_tasks_done: ChecklistTasksDone | None = checklist_tasks_done
            self.checklist_tasks_added: ChecklistTasksAdded | None = checklist_tasks_added
            self.effect_id: str | None = effect_id
            self.show_caption_above_media: bool | None = show_caption_above_media
            self.paid_media: PaidMediaInfo | None = paid_media
            self.refunded_payment: RefundedPayment | None = refunded_payment
            self.gift: GiftInfo | None = gift
            self.unique_gift: UniqueGiftInfo | None = unique_gift
            self.paid_message_price_changed: PaidMessagePriceChanged | None = (
                paid_message_price_changed
            )
            self.paid_star_count: int | None = paid_star_count
            self.direct_message_price_changed: DirectMessagePriceChanged | None = (
                direct_message_price_changed
            )
            self.is_paid_post: bool | None = is_paid_post
            self.direct_messages_topic: DirectMessagesTopic | None = direct_messages_topic
            self.reply_to_checklist_task_id: int | None = reply_to_checklist_task_id
            self.suggested_post_declined: SuggestedPostDeclined | None = suggested_post_declined
            self.suggested_post_paid: SuggestedPostPaid | None = suggested_post_paid
            self.suggested_post_refunded: SuggestedPostRefunded | None = suggested_post_refunded
            self.suggested_post_info: SuggestedPostInfo | None = suggested_post_info
            self.suggested_post_approved: SuggestedPostApproved | None = suggested_post_approved
            self.suggested_post_approval_failed: SuggestedPostApprovalFailed | None = (
                suggested_post_approval_failed
            )
            self.gift_upgrade_sent: GiftInfo | None = gift_upgrade_sent

            self._effective_attachment = DEFAULT_NONE

            self._id_attrs = (self.message_id, self.chat)

    @property
    def chat_id(self) -> int:
        """:obj:`int`: Shortcut for :attr:`telegram.Chat.id` for :attr:`chat`."""
        return self.chat.id

    @property
    def id(self) -> int:
        """
        :obj:`int`: Shortcut for :attr:`message_id`.

            .. versionadded:: 20.0
        """
        return self.message_id

    @property
    def link(self) -> str | None:
        """:obj:`str`: Convenience property. If the chat of the message is not
        a private chat or normal group, returns a t.me link of the message.

            .. versionchanged:: 20.3
                For messages that are replies or part of a forum topic, the link now points
                to the corresponding thread view.
        """
        if self.chat.type not in [Chat.PRIVATE, Chat.GROUP]:
            # the else block gets rid of leading -100 for supergroups:
            to_link = self.chat.username if self.chat.username else f"c/{str(self.chat.id)[4:]}"
            baselink = f"https://t.me/{to_link}/{self.message_id}"

            # adds the thread for topics and replies
            if (self.is_topic_message and self.message_thread_id) or self.reply_to_message:
                baselink = f"{baselink}?thread={self.message_thread_id}"
            return baselink
        return None

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "Message":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["from_user"] = de_json_optional(data.pop("from", None), User, bot)
        data["sender_chat"] = de_json_optional(data.get("sender_chat"), Chat, bot)
        data["entities"] = de_list_optional(data.get("entities"), MessageEntity, bot)
        data["caption_entities"] = de_list_optional(
            data.get("caption_entities"), MessageEntity, bot
        )
        data["reply_to_message"] = de_json_optional(data.get("reply_to_message"), Message, bot)
        data["edit_date"] = from_timestamp(data.get("edit_date"), tzinfo=loc_tzinfo)
        data["audio"] = de_json_optional(data.get("audio"), Audio, bot)
        data["document"] = de_json_optional(data.get("document"), Document, bot)
        data["animation"] = de_json_optional(data.get("animation"), Animation, bot)
        data["game"] = de_json_optional(data.get("game"), Game, bot)
        data["photo"] = de_list_optional(data.get("photo"), PhotoSize, bot)
        data["sticker"] = de_json_optional(data.get("sticker"), Sticker, bot)
        data["story"] = de_json_optional(data.get("story"), Story, bot)
        data["video"] = de_json_optional(data.get("video"), Video, bot)
        data["voice"] = de_json_optional(data.get("voice"), Voice, bot)
        data["video_note"] = de_json_optional(data.get("video_note"), VideoNote, bot)
        data["contact"] = de_json_optional(data.get("contact"), Contact, bot)
        data["location"] = de_json_optional(data.get("location"), Location, bot)
        data["venue"] = de_json_optional(data.get("venue"), Venue, bot)
        data["new_chat_members"] = de_list_optional(data.get("new_chat_members"), User, bot)
        data["left_chat_member"] = de_json_optional(data.get("left_chat_member"), User, bot)
        data["new_chat_photo"] = de_list_optional(data.get("new_chat_photo"), PhotoSize, bot)
        data["message_auto_delete_timer_changed"] = de_json_optional(
            data.get("message_auto_delete_timer_changed"), MessageAutoDeleteTimerChanged, bot
        )
        data["pinned_message"] = de_json_optional(
            data.get("pinned_message"), MaybeInaccessibleMessage, bot
        )
        data["invoice"] = de_json_optional(data.get("invoice"), Invoice, bot)
        data["successful_payment"] = de_json_optional(
            data.get("successful_payment"), SuccessfulPayment, bot
        )
        data["passport_data"] = de_json_optional(data.get("passport_data"), PassportData, bot)
        data["poll"] = de_json_optional(data.get("poll"), Poll, bot)
        data["dice"] = de_json_optional(data.get("dice"), Dice, bot)
        data["via_bot"] = de_json_optional(data.get("via_bot"), User, bot)
        data["proximity_alert_triggered"] = de_json_optional(
            data.get("proximity_alert_triggered"), ProximityAlertTriggered, bot
        )
        data["reply_markup"] = de_json_optional(
            data.get("reply_markup"), InlineKeyboardMarkup, bot
        )
        data["video_chat_scheduled"] = de_json_optional(
            data.get("video_chat_scheduled"), VideoChatScheduled, bot
        )
        data["video_chat_started"] = de_json_optional(
            data.get("video_chat_started"), VideoChatStarted, bot
        )
        data["video_chat_ended"] = de_json_optional(
            data.get("video_chat_ended"), VideoChatEnded, bot
        )
        data["video_chat_participants_invited"] = de_json_optional(
            data.get("video_chat_participants_invited"), VideoChatParticipantsInvited, bot
        )
        data["web_app_data"] = de_json_optional(data.get("web_app_data"), WebAppData, bot)
        data["forum_topic_closed"] = de_json_optional(
            data.get("forum_topic_closed"), ForumTopicClosed, bot
        )
        data["forum_topic_created"] = de_json_optional(
            data.get("forum_topic_created"), ForumTopicCreated, bot
        )
        data["forum_topic_reopened"] = de_json_optional(
            data.get("forum_topic_reopened"), ForumTopicReopened, bot
        )
        data["forum_topic_edited"] = de_json_optional(
            data.get("forum_topic_edited"), ForumTopicEdited, bot
        )
        data["general_forum_topic_hidden"] = de_json_optional(
            data.get("general_forum_topic_hidden"), GeneralForumTopicHidden, bot
        )
        data["general_forum_topic_unhidden"] = de_json_optional(
            data.get("general_forum_topic_unhidden"), GeneralForumTopicUnhidden, bot
        )
        data["write_access_allowed"] = de_json_optional(
            data.get("write_access_allowed"), WriteAccessAllowed, bot
        )
        data["users_shared"] = de_json_optional(data.get("users_shared"), UsersShared, bot)
        data["chat_shared"] = de_json_optional(data.get("chat_shared"), ChatShared, bot)
        data["chat_background_set"] = de_json_optional(
            data.get("chat_background_set"), ChatBackground, bot
        )
        data["paid_media"] = de_json_optional(data.get("paid_media"), PaidMediaInfo, bot)
        data["refunded_payment"] = de_json_optional(
            data.get("refunded_payment"), RefundedPayment, bot
        )
        data["gift"] = de_json_optional(data.get("gift"), GiftInfo, bot)
        data["unique_gift"] = de_json_optional(data.get("unique_gift"), UniqueGiftInfo, bot)
        data["paid_message_price_changed"] = de_json_optional(
            data.get("paid_message_price_changed"), PaidMessagePriceChanged, bot
        )

        # Unfortunately, this needs to be here due to cyclic imports
        from telegram._giveaway import (  # pylint: disable=C0415  # noqa: PLC0415
            Giveaway,
            GiveawayCompleted,
            GiveawayCreated,
            GiveawayWinners,
        )
        from telegram._messageorigin import (  # pylint: disable=C0415  # noqa: PLC0415
            MessageOrigin,
        )
        from telegram._reply import (  # pylint: disable=import-outside-toplevel  # noqa: PLC0415
            ExternalReplyInfo,
            TextQuote,
        )
        from telegram._suggestedpost import (  # pylint: disable=import-outside-toplevel  # noqa: PLC0415
            SuggestedPostApprovalFailed,
            SuggestedPostApproved,
            SuggestedPostDeclined,
            SuggestedPostInfo,
            SuggestedPostPaid,
            SuggestedPostRefunded,
        )

        data["giveaway"] = de_json_optional(data.get("giveaway"), Giveaway, bot)
        data["giveaway_completed"] = de_json_optional(
            data.get("giveaway_completed"), GiveawayCompleted, bot
        )
        data["giveaway_created"] = de_json_optional(
            data.get("giveaway_created"), GiveawayCreated, bot
        )
        data["giveaway_winners"] = de_json_optional(
            data.get("giveaway_winners"), GiveawayWinners, bot
        )
        data["link_preview_options"] = de_json_optional(
            data.get("link_preview_options"), LinkPreviewOptions, bot
        )
        data["external_reply"] = de_json_optional(
            data.get("external_reply"), ExternalReplyInfo, bot
        )
        data["quote"] = de_json_optional(data.get("quote"), TextQuote, bot)
        data["forward_origin"] = de_json_optional(data.get("forward_origin"), MessageOrigin, bot)
        data["reply_to_story"] = de_json_optional(data.get("reply_to_story"), Story, bot)
        data["boost_added"] = de_json_optional(data.get("boost_added"), ChatBoostAdded, bot)
        data["sender_business_bot"] = de_json_optional(data.get("sender_business_bot"), User, bot)
        data["direct_message_price_changed"] = de_json_optional(
            data.get("direct_message_price_changed"), DirectMessagePriceChanged, bot
        )
        data["checklist"] = de_json_optional(data.get("checklist"), Checklist, bot)
        data["checklist_tasks_done"] = de_json_optional(
            data.get("checklist_tasks_done"), ChecklistTasksDone, bot
        )
        data["checklist_tasks_added"] = de_json_optional(
            data.get("checklist_tasks_added"), ChecklistTasksAdded, bot
        )
        data["direct_messages_topic"] = de_json_optional(
            data.get("direct_messages_topic"), DirectMessagesTopic, bot
        )
        data["suggested_post_declined"] = de_json_optional(
            data.get("suggested_post_declined"), SuggestedPostDeclined, bot
        )
        data["suggested_post_paid"] = de_json_optional(
            data.get("suggested_post_paid"), SuggestedPostPaid, bot
        )
        data["suggested_post_refunded"] = de_json_optional(
            data.get("suggested_post_refunded"), SuggestedPostRefunded, bot
        )
        data["suggested_post_info"] = de_json_optional(
            data.get("suggested_post_info"), SuggestedPostInfo, bot
        )
        data["suggested_post_approved"] = de_json_optional(
            data.get("suggested_post_approved"), SuggestedPostApproved, bot
        )
        data["suggested_post_approval_failed"] = de_json_optional(
            data.get("suggested_post_approval_failed"), SuggestedPostApprovalFailed, bot
        )
        data["gift_upgrade_sent"] = de_json_optional(data.get("gift_upgrade_sent"), GiftInfo, bot)

        api_kwargs = {}
        # This is a deprecated field that TG still returns for backwards compatibility
        # Let's filter it out to speed up the de-json process
        for key in (
            "user_shared",
            "forward_from",
            "forward_from_chat",
            "forward_from_message_id",
            "forward_signature",
            "forward_sender_name",
            "forward_date",
        ):
            if entry := data.get(key):
                api_kwargs = {key: entry}

        return super()._de_json(  # type: ignore[return-value]
            data=data, bot=bot, api_kwargs=api_kwargs
        )

    @property
    def effective_attachment(
        self,
    ) -> (
        Animation
        | Audio
        | Contact
        | Dice
        | Document
        | Game
        | Invoice
        | Location
        | PassportData
        | Sequence[PhotoSize]
        | PaidMediaInfo
        | Poll
        | Sticker
        | Story
        | SuccessfulPayment
        | Venue
        | Video
        | VideoNote
        | Voice
        | None
    ):
        """If the message is a user generated content which is not a plain text message, this
        property is set to this content. It may be one of

        * :class:`telegram.Audio`
        * :class:`telegram.Dice`
        * :class:`telegram.Contact`
        * :class:`telegram.Document`
        * :class:`telegram.Animation`
        * :class:`telegram.Game`
        * :class:`telegram.Invoice`
        * :class:`telegram.Location`
        * :class:`telegram.PassportData`
        * list[:class:`telegram.PhotoSize`]
        * :class:`telegram.PaidMediaInfo`
        * :class:`telegram.Poll`
        * :class:`telegram.Sticker`
        * :class:`telegram.Story`
        * :class:`telegram.SuccessfulPayment`
        * :class:`telegram.Venue`
        * :class:`telegram.Video`
        * :class:`telegram.VideoNote`
        * :class:`telegram.Voice`

        Otherwise :obj:`None` is returned.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        .. versionchanged:: 20.0
            :attr:`dice`, :attr:`passport_data` and :attr:`poll` are now also considered to be an
            attachment.

        .. versionchanged:: 21.4
            :attr:`paid_media` is now also considered to be an attachment.

        .. deprecated:: 21.4
            :attr:`successful_payment` will be removed in future major versions.

        """
        if not isinstance(self._effective_attachment, DefaultValue):
            return self._effective_attachment

        for attachment_type in MessageAttachmentType:
            if self[attachment_type]:
                self._effective_attachment = self[attachment_type]  # type: ignore[assignment]
                if attachment_type == MessageAttachmentType.SUCCESSFUL_PAYMENT:
                    warn(
                        PTBDeprecationWarning(
                            "21.4",
                            "successful_payment will no longer be considered an attachment in"
                            " future major versions",
                        ),
                        stacklevel=2,
                    )
                break
        else:
            self._effective_attachment = None

        return self._effective_attachment  # type: ignore[return-value]

    def _do_quote(
        self, do_quote: bool | None, allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE
    ) -> ReplyParameters | None:
        """Modify kwargs for replying with or without quoting."""
        # `Defaults` handling for allow_sending_without_reply is not necessary, as
        # `ReplyParameters` have special defaults handling in (ExtBot)._insert_defaults
        if do_quote is not None:
            if do_quote:
                return ReplyParameters(
                    self.message_id, allow_sending_without_reply=allow_sending_without_reply
                )

        else:
            # Unfortunately we need some ExtBot logic here because it's hard to move shortcut
            # logic into ExtBot
            if hasattr(self.get_bot(), "defaults") and self.get_bot().defaults:  # type: ignore
                default_quote = self.get_bot().defaults.do_quote  # type: ignore[attr-defined]
            else:
                default_quote = None
            if (default_quote is None and self.chat.type != Chat.PRIVATE) or default_quote:
                return ReplyParameters(
                    self.message_id, allow_sending_without_reply=allow_sending_without_reply
                )

        return None

    def compute_quote_position_and_entities(
        self, quote: str, index: int | None = None
    ) -> tuple[int, tuple[MessageEntity, ...] | None]:
        """
        Use this function to compute position and entities of a quote in the message text or
        caption. Useful for filling the parameters
        :paramref:`~telegram.ReplyParameters.quote_position` and
        :paramref:`~telegram.ReplyParameters.quote_entities` of :class:`telegram.ReplyParameters`
        when replying to a message.

        Example:

            Given a message with the text ``"Hello, world! Hello, world!"``, the following code
            will return the position and entities of the second occurrence of ``"Hello, world!"``.

            .. code-block:: python

                message.compute_quote_position_and_entities("Hello, world!", 1)

        .. versionadded:: 20.8

        Args:
            quote (:obj:`str`): Part of the message which is to be quoted. This is
                expected to have plain text without formatting entities.
            index (:obj:`int`, optional): 0-based index of the occurrence of the quote in the
                message. If not specified, the first occurrence is used.

        Returns:
            tuple[:obj:`int`, :obj:`None` | tuple[:class:`~telegram.MessageEntity`, ...]]: On
            success, a tuple containing information about quote position and entities is returned.

        Raises:
            RuntimeError: If the message has neither :attr:`text` nor :attr:`caption`.
            ValueError: If the requested index of quote doesn't exist in the message.
        """
        if not (text := (self.text or self.caption)):
            raise RuntimeError("This message has neither text nor caption.")

        # Telegram wants the position in UTF-16 code units, so we have to calculate in that space
        utf16_text = text.encode(TextEncoding.UTF_16_LE)
        utf16_quote = quote.encode(TextEncoding.UTF_16_LE)
        effective_index = index or 0

        matches = list(re.finditer(re.escape(utf16_quote), utf16_text))
        if (length := len(matches)) < effective_index + 1:
            raise ValueError(
                f"You requested the {index}-th occurrence of '{quote}', but this text appears "
                f"only {length} times."
            )

        position = len(utf16_text[: matches[effective_index].start()]) // 2
        length = len(utf16_quote) // 2
        end_position = position + length

        entities = []
        for entity in self.entities or self.caption_entities:
            if position <= entity.offset + entity.length and entity.offset <= end_position:
                # shift the offset by the position of the quote
                offset = max(0, entity.offset - position)
                # trim the entity length to the length of the overlap with the quote
                e_length = min(end_position, entity.offset + entity.length) - max(
                    position, entity.offset
                )
                if e_length <= 0:
                    continue

                # create a new entity with the correct offset and length
                # looping over slots rather manually accessing the attributes
                # is more future-proof
                kwargs = {attr: getattr(entity, attr) for attr in entity.__slots__}
                kwargs["offset"] = offset
                kwargs["length"] = e_length
                entities.append(MessageEntity(**kwargs))

        return position, tuple(entities) or None

    def build_reply_arguments(
        self,
        quote: str | None = None,
        quote_index: int | None = None,
        target_chat_id: int | (str | None) = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
    ) -> _ReplyKwargs:
        """
        Builds a dictionary with the keys ``chat_id`` and ``reply_parameters``. This dictionary can
        be used to reply to a message with the given quote and target chat.

        Examples:

            Usage with :meth:`telegram.Bot.send_message`:

            .. code-block:: python

                await bot.send_message(
                    text="This is a reply",
                    **message.build_reply_arguments(quote="Quoted Text")
                )

            Usage with :meth:`reply_text`, replying in the same chat:

            .. code-block:: python

                await message.reply_text(
                    "This is a reply",
                    do_quote=message.build_reply_arguments(quote="Quoted Text")
                )

            Usage with :meth:`reply_text`, replying in a different chat:

            .. code-block:: python

                await message.reply_text(
                    "This is a reply",
                    do_quote=message.build_reply_arguments(
                        quote="Quoted Text",
                        target_chat_id=-100123456789
                    )
                )

        .. versionadded:: 20.8

        Args:
            quote (:obj:`str`, optional): Passed in :meth:`compute_quote_position_and_entities`
                as parameter :paramref:`~compute_quote_position_and_entities.quote` to compute
                quote entities. Defaults to :obj:`None`.
            quote_index (:obj:`int`, optional): Passed in
                :meth:`compute_quote_position_and_entities` as parameter
                :paramref:`~compute_quote_position_and_entities.quote_index` to compute quote
                position. Defaults to :obj:`None`.
            target_chat_id (:obj:`int` | :obj:`str`, optional): |chat_id_channel|
                Defaults to :attr:`chat_id`.
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Will be applied only if the reply happens in the same chat and forum topic.
            message_thread_id (:obj:`int`, optional): |message_thread_id|

        Returns:
            :obj:`dict`:
        """
        target_chat_is_self = target_chat_id in (None, self.chat_id, f"@{self.chat.username}")

        if target_chat_is_self and message_thread_id in (
            None,
            self.message_thread_id,
        ):
            # defaults handling will take place in `Bot._insert_defaults`
            effective_aswr: ODVInput[bool] = allow_sending_without_reply
        else:
            effective_aswr = None

        quote_position, quote_entities = (
            self.compute_quote_position_and_entities(quote, quote_index) if quote else (None, None)
        )
        return {  # type: ignore[typeddict-item]
            "reply_parameters": ReplyParameters(
                chat_id=None if target_chat_is_self else self.chat_id,
                message_id=self.message_id,
                quote=quote,
                quote_position=quote_position,
                quote_entities=quote_entities,
                allow_sending_without_reply=effective_aswr,
            ),
            "chat_id": target_chat_id or self.chat_id,
        }

    async def _parse_quote_arguments(
        self,
        do_quote: bool | _ReplyKwargs | None,
        reply_to_message_id: int | None,
        reply_parameters: "ReplyParameters | None",
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
    ) -> tuple[str | int, ReplyParameters]:
        if allow_sending_without_reply is not DEFAULT_NONE and reply_parameters is not None:
            raise ValueError(
                "`allow_sending_without_reply` and `reply_parameters` are mutually exclusive."
            )
        if reply_to_message_id is not None and reply_parameters is not None:
            raise ValueError(
                "`reply_to_message_id` and `reply_parameters` are mutually exclusive."
            )

        chat_id: str | int = self.chat_id

        # reply_parameters and reply_to_message_id overrule the do_quote parameter
        if reply_parameters is not None:
            effective_reply_parameters = reply_parameters
        elif reply_to_message_id is not None:
            effective_reply_parameters = ReplyParameters(
                message_id=reply_to_message_id,
                allow_sending_without_reply=allow_sending_without_reply,
            )
        elif isinstance(do_quote, dict):
            if allow_sending_without_reply is not DEFAULT_NONE:
                raise ValueError(
                    "`allow_sending_without_reply` and `dict`-value input for `do_quote` are "
                    "mutually exclusive."
                )

            effective_reply_parameters = do_quote["reply_parameters"]
            chat_id = do_quote["chat_id"]
        else:
            effective_reply_parameters = self._do_quote(do_quote, allow_sending_without_reply)

        return chat_id, effective_reply_parameters

    def _parse_message_thread_id(
        self,
        chat_id: str | int,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
    ) -> int | None:
        # values set by user have the highest priority
        if not isinstance(message_thread_id, DefaultValue):
            return message_thread_id

        # self.message_thread_id can be used for send_*.param.message_thread_id only if the
        # thread is a forum topic (in supergroups or private chats). It does not work if the
        # thread is a chain of replies to a message in a normal group. In that case,
        # self.message_thread_id is just the message_id of the first message in the chain.
        if not self.is_topic_message:
            return None

        # Setting message_thread_id=self.message_thread_id only makes sense if we're replying in
        # the same chat.
        return self.message_thread_id if chat_id in {self.chat_id, self.chat.username} else None

    def _extract_direct_messages_topic_id(self) -> int | None:
        """Return the topic id of the direct messages chat, if it is present."""
        return self.direct_messages_topic.topic_id if self.direct_messages_topic else None

    async def reply_text(
        self,
        text: str,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        link_preview_options: ODVInput["LinkPreviewOptions"] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        disable_web_page_preview: bool | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_message(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_message`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            link_preview_options=link_preview_options,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            entities=entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_text_draft(
        self,
        draft_id: int,
        text: str,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        entities: Sequence["MessageEntity"] | None = None,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.send_message_draft(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_message_draft`.

        Note:
            |reply_same_thread|

        .. versionadded:: 22.6

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        message_thread_id = self._parse_message_thread_id(self.chat_id, message_thread_id)
        return await self.get_bot().send_message_draft(
            chat_id=self.chat_id,
            draft_id=draft_id,
            text=text,
            parse_mode=parse_mode,
            entities=entities,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def reply_markdown(
        self,
        text: str,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        link_preview_options: ODVInput["LinkPreviewOptions"] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        disable_web_page_preview: bool | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

            await bot.send_message(
                update.effective_message.chat_id,
                message_thread_id=update.effective_message.message_thread_id,
                parse_mode=ParseMode.MARKDOWN,
                business_connection_id=self.business_connection_id,
                direct_messages_topic_id=self.direct_messages_topic.topic_id,
                *args,
                **kwargs,
            )

        Sends a message with Markdown version 1 formatting.

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_message`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Note:
            :tg-const:`telegram.constants.ParseMode.MARKDOWN` is a legacy mode, retained by
            Telegram for backward compatibility. You should use :meth:`reply_markdown_v2` instead.

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.
        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=disable_web_page_preview,
            link_preview_options=link_preview_options,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            entities=entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_markdown_v2(
        self,
        text: str,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        link_preview_options: ODVInput["LinkPreviewOptions"] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        disable_web_page_preview: bool | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

            await bot.send_message(
                update.effective_message.chat_id,
                message_thread_id=update.effective_message.message_thread_id,
                parse_mode=ParseMode.MARKDOWN_V2,
                direct_messages_topic_id=self.direct_messages_topic.topic_id,
                business_connection_id=self.business_connection_id,
                *args,
                **kwargs,
            )

        Sends a message with markdown version 2 formatting.

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_message`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.
        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=disable_web_page_preview,
            link_preview_options=link_preview_options,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            entities=entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_html(
        self,
        text: str,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        link_preview_options: ODVInput["LinkPreviewOptions"] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        disable_web_page_preview: bool | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

            await bot.send_message(
                update.effective_message.chat_id,
                message_thread_id=update.effective_message.message_thread_id,
                parse_mode=ParseMode.HTML,
                direct_messages_topic_id=self.direct_messages_topic.topic_id,
                business_connection_id=self.business_connection_id,
                *args,
                **kwargs,
            )

        Sends a message with HTML formatting.

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_message`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.
        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=disable_web_page_preview,
            link_preview_options=link_preview_options,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            entities=entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_media_group(
        self,
        media: Sequence[
            "InputMediaAudio | InputMediaDocument | InputMediaPhoto | InputMediaVideo"
        ],
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
    ) -> tuple["Message", ...]:
        """Shortcut for::

             await bot.send_media_group(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_media_group`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            tuple[:class:`telegram.Message`]: An array of the sent Messages.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_media_group(
            chat_id=chat_id,
            media=media,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
        )

    async def reply_photo(
        self,
        photo: "FileInput | PhotoSize",
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        has_spoiler: bool | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        show_caption_above_media: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_photo(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_photo`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            has_spoiler=has_spoiler,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            show_caption_above_media=show_caption_above_media,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_audio(
        self,
        audio: "FileInput | Audio",
        duration: TimePeriod | None = None,
        performer: str | None = None,
        title: str | None = None,
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_audio(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_audio`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_audio(
            chat_id=chat_id,
            audio=audio,
            duration=duration,
            performer=performer,
            title=title,
            caption=caption,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            thumbnail=thumbnail,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_document(
        self,
        document: "FileInput | Document",
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        disable_content_type_detection: bool | None = None,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_document(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_document`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_document(
            chat_id=chat_id,
            document=document,
            filename=filename,
            caption=caption,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            parse_mode=parse_mode,
            api_kwargs=api_kwargs,
            disable_content_type_detection=disable_content_type_detection,
            caption_entities=caption_entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            thumbnail=thumbnail,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_animation(
        self,
        animation: "FileInput | Animation",
        duration: TimePeriod | None = None,
        width: int | None = None,
        height: int | None = None,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        has_spoiler: bool | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        show_caption_above_media: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_animation(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_animation`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_animation(
            chat_id=chat_id,
            animation=animation,
            duration=duration,
            width=width,
            height=height,
            caption=caption,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            caption_entities=caption_entities,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            has_spoiler=has_spoiler,
            thumbnail=thumbnail,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            show_caption_above_media=show_caption_above_media,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_sticker(
        self,
        sticker: "FileInput | Sticker",
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        emoji: str | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_sticker(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_sticker`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_sticker(
            chat_id=chat_id,
            sticker=sticker,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            emoji=emoji,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_video(
        self,
        video: "FileInput | Video",
        duration: TimePeriod | None = None,
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        width: int | None = None,
        height: int | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        supports_streaming: bool | None = None,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        has_spoiler: bool | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        show_caption_above_media: bool | None = None,
        cover: "FileInput | None" = None,
        start_timestamp: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_video(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_video`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_video(
            chat_id=chat_id,
            video=video,
            duration=duration,
            caption=caption,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            width=width,
            height=height,
            parse_mode=parse_mode,
            supports_streaming=supports_streaming,
            api_kwargs=api_kwargs,
            caption_entities=caption_entities,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            has_spoiler=has_spoiler,
            thumbnail=thumbnail,
            cover=cover,
            start_timestamp=start_timestamp,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            show_caption_above_media=show_caption_above_media,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_video_note(
        self,
        video_note: "FileInput | VideoNote",
        duration: TimePeriod | None = None,
        length: int | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_video_note(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_video_note`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_video_note(
            chat_id=chat_id,
            video_note=video_note,
            duration=duration,
            length=length,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            thumbnail=thumbnail,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_voice(
        self,
        voice: "FileInput | Voice",
        duration: TimePeriod | None = None,
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_voice(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_voice`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_voice(
            chat_id=chat_id,
            voice=voice,
            duration=duration,
            caption=caption,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            parse_mode=parse_mode,
            api_kwargs=api_kwargs,
            caption_entities=caption_entities,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_location(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        live_period: TimePeriod | None = None,
        horizontal_accuracy: float | None = None,
        heading: int | None = None,
        proximity_alert_radius: int | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        location: "Location | None" = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_location(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_location`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_location(
            chat_id=chat_id,
            latitude=latitude,
            longitude=longitude,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            location=location,
            live_period=live_period,
            api_kwargs=api_kwargs,
            horizontal_accuracy=horizontal_accuracy,
            heading=heading,
            proximity_alert_radius=proximity_alert_radius,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_venue(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        title: str | None = None,
        address: str | None = None,
        foursquare_id: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        foursquare_type: str | None = None,
        google_place_id: str | None = None,
        google_place_type: str | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        venue: "Venue | None" = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_venue(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_venue`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_venue(
            chat_id=chat_id,
            latitude=latitude,
            longitude=longitude,
            title=title,
            address=address,
            foursquare_id=foursquare_id,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            venue=venue,
            foursquare_type=foursquare_type,
            api_kwargs=api_kwargs,
            google_place_id=google_place_id,
            google_place_type=google_place_type,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_contact(
        self,
        phone_number: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        vcard: str | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        contact: "Contact | None" = None,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_contact(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_contact`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_contact(
            chat_id=chat_id,
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            contact=contact,
            vcard=vcard,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            allow_paid_broadcast=allow_paid_broadcast,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_poll(
        self,
        question: str,
        options: Sequence["str | InputPollOption"],
        is_anonymous: bool | None = None,
        type: str | None = None,  # pylint: disable=redefined-builtin
        allows_multiple_answers: bool | None = None,
        correct_option_id: CorrectOptionID | None = None,
        is_closed: bool | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        explanation: str | None = None,
        explanation_parse_mode: ODVInput[str] = DEFAULT_NONE,
        open_period: TimePeriod | None = None,
        close_date: int | (dtm.datetime | None) = None,
        explanation_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        question_parse_mode: ODVInput[str] = DEFAULT_NONE,
        question_entities: Sequence["MessageEntity"] | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_poll(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_poll`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_poll(
            chat_id=chat_id,
            question=question,
            options=options,
            is_anonymous=is_anonymous,
            type=type,
            allows_multiple_answers=allows_multiple_answers,
            correct_option_id=correct_option_id,
            is_closed=is_closed,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            explanation=explanation,
            explanation_parse_mode=explanation_parse_mode,
            open_period=open_period,
            close_date=close_date,
            api_kwargs=api_kwargs,
            explanation_entities=explanation_entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=self.business_connection_id,
            question_parse_mode=question_parse_mode,
            question_entities=question_entities,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
        )

    async def reply_dice(
        self,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        emoji: str | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_dice(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_dice`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_dice(
            chat_id=chat_id,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            emoji=emoji,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def reply_checklist(
        self,
        checklist: InputChecklist,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_effect_id: str | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_checklist(
                 business_connection_id=self.business_connection_id,
                 chat_id=update.effective_message.chat_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_checklist`.

        .. versionadded:: 22.3

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        return await self.get_bot().send_checklist(
            business_connection_id=self.business_connection_id,
            chat_id=chat_id,  # type: ignore[arg-type]
            checklist=checklist,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_effect_id=message_effect_id,
        )

    async def reply_chat_action(
        self,
        action: str,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.send_chat_action(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_chat_action`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionadded:: 13.2

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().send_chat_action(
            chat_id=self.chat_id,
            message_thread_id=self._parse_message_thread_id(self.chat_id, message_thread_id),
            action=action,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=self.business_connection_id,
        )

    async def reply_game(
        self,
        game_short_name: str,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_game(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=self.business_connection_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_game`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        .. versionadded:: 13.2

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_game(
            chat_id=chat_id,  # type: ignore[arg-type]
            game_short_name=game_short_name,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=self.business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
        )

    async def reply_invoice(
        self,
        title: str,
        description: str,
        payload: str,
        currency: str,
        prices: Sequence["LabeledPrice"],
        provider_token: str | None = None,
        start_parameter: str | None = None,
        photo_url: str | None = None,
        photo_size: int | None = None,
        photo_width: int | None = None,
        photo_height: int | None = None,
        need_name: bool | None = None,
        need_phone_number: bool | None = None,
        need_email: bool | None = None,
        need_shipping_address: bool | None = None,
        is_flexible: bool | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        provider_data: str | (object | None) = None,
        send_phone_number_to_provider: bool | None = None,
        send_email_to_provider: bool | None = None,
        max_tip_amount: int | None = None,
        suggested_tip_amounts: Sequence[int] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_invoice(
                 update.effective_message.chat_id,
                 message_thread_id=update.effective_message.message_thread_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs,
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_invoice`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Warning:
            As of API 5.2 :paramref:`start_parameter <telegram.Bot.send_invoice.start_parameter>`
            is an optional argument and therefore the
            order of the arguments had to be changed. Use keyword arguments to make sure that the
            arguments are passed correctly.

        .. versionadded:: 13.2

        .. versionchanged:: 13.5
            As of Bot API 5.2, the parameter
            :paramref:`start_parameter <telegram.Bot.send_invoice.start_parameter>` is optional.

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token=provider_token,
            currency=currency,
            prices=prices,
            start_parameter=start_parameter,
            photo_url=photo_url,
            photo_size=photo_size,
            photo_width=photo_width,
            photo_height=photo_height,
            need_name=need_name,
            need_phone_number=need_phone_number,
            need_email=need_email,
            need_shipping_address=need_shipping_address,
            is_flexible=is_flexible,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            provider_data=provider_data,
            send_phone_number_to_provider=send_phone_number_to_provider,
            send_email_to_provider=send_email_to_provider,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            max_tip_amount=max_tip_amount,
            suggested_tip_amounts=suggested_tip_amounts,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
        )

    async def forward(
        self,
        chat_id: int | str,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        video_start_timestamp: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        message_effect_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.forward_message(
                 from_chat_id=update.effective_message.chat_id,
                 message_id=update.effective_message.message_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.forward_message`.

        Note:
            Since the release of Bot API 5.5 it can be impossible to forward messages from
            some chats. Use the attributes :attr:`telegram.Message.has_protected_content` and
            :attr:`telegram.ChatFullInfo.has_protected_content` to check this.

            As a workaround, it is still possible to use :meth:`copy`. However, this
            behaviour is undocumented and might be changed by Telegram.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message forwarded.

        """
        return await self.get_bot().forward_message(
            chat_id=chat_id,
            from_chat_id=self.chat_id,
            message_id=self.message_id,
            video_start_timestamp=video_start_timestamp,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            suggested_post_parameters=suggested_post_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            message_effect_id=message_effect_id,
        )

    async def copy(
        self,
        chat_id: int | str,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        show_caption_above_media: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        video_start_timestamp: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        message_effect_id: str | None = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "MessageId":
        """Shortcut for::

             await bot.copy_message(
                 chat_id=chat_id,
                 from_chat_id=update.effective_message.chat_id,
                 message_id=update.effective_message.message_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.copy_message`.

        Returns:
            :class:`telegram.MessageId`: On success, returns the MessageId of the sent message.

        """
        return await self.get_bot().copy_message(
            chat_id=chat_id,
            from_chat_id=self.chat_id,
            message_id=self.message_id,
            caption=caption,
            video_start_timestamp=video_start_timestamp,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            allow_sending_without_reply=allow_sending_without_reply,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            show_caption_above_media=show_caption_above_media,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
            message_effect_id=message_effect_id,
        )

    async def reply_copy(
        self,
        from_chat_id: str | int,
        message_id: int,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        show_caption_above_media: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        video_start_timestamp: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        message_effect_id: str | None = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "MessageId":
        """Shortcut for::

             await bot.copy_message(
                 chat_id=message.chat.id,
                 message_thread_id=update.effective_message.message_thread_id,
                 message_id=message_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.copy_message`.

        .. versionchanged:: 21.1
                |reply_same_thread|

        .. versionchanged:: 22.0
            |quote_removed|

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

                .. versionadded:: 20.8

        Returns:
            :class:`telegram.MessageId`: On success, returns the MessageId of the sent message.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().copy_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            caption=caption,
            video_start_timestamp=video_start_timestamp,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            show_caption_above_media=show_caption_above_media,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
            message_effect_id=message_effect_id,
        )

    async def reply_paid_media(
        self,
        star_count: int,
        media: Sequence["InputPaidMedia"],
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        show_caption_above_media: bool | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        reply_markup: "ReplyMarkup | None" = None,
        payload: str | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        message_thread_id: ODVInput[int] = DEFAULT_NONE,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        do_quote: bool | (_ReplyKwargs | None) = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_paid_media(
                 chat_id=message.chat.id,
                 message_thread_id=update.effective_message.message_thread_id,
                 business_connection_id=message.business_connection_id,
                 direct_messages_topic_id=self.direct_messages_topic.topic_id,
                 *args,
                 **kwargs
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_paid_media`.

        .. versionadded:: 21.7

        Keyword Args:
            do_quote (:obj:`bool` | :obj:`dict`, optional): |do_quote|

        Returns:
            :class:`telegram.Message`: On success, the sent message is returned.

        """
        chat_id, effective_reply_parameters = await self._parse_quote_arguments(
            do_quote, reply_to_message_id, reply_parameters, allow_sending_without_reply
        )
        message_thread_id = self._parse_message_thread_id(chat_id, message_thread_id)
        return await self.get_bot().send_paid_media(
            chat_id=chat_id,
            caption=caption,
            star_count=star_count,
            media=media,
            payload=payload,
            business_connection_id=self.business_connection_id,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            disable_notification=disable_notification,
            reply_parameters=effective_reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            show_caption_above_media=show_caption_above_media,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=self._extract_direct_messages_topic_id(),
            suggested_post_parameters=suggested_post_parameters,
            message_thread_id=message_thread_id,
        )

    async def edit_text(
        self,
        text: str,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        entities: Sequence["MessageEntity"] | None = None,
        link_preview_options: ODVInput["LinkPreviewOptions"] = DEFAULT_NONE,
        *,
        disable_web_page_preview: bool | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Shortcut for::

             await bot.edit_message_text(
                 chat_id=message.chat_id,
                 message_id=message.message_id,
                 business_connection_id=message.business_connection_id,
                 *args, **kwargs
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.edit_message_text`.

        Note:
            You can only edit messages that the bot sent itself (i.e. of the ``bot.send_*`` family
            of methods) or channel posts, if the bot is an admin in that channel. However, this
            behaviour is undocumented and might be changed by Telegram.

        .. versionchanged:: 21.4
           Now also passes :attr:`business_connection_id`.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise ``True`` is returned.

        """
        return await self.get_bot().edit_message_text(
            chat_id=self.chat_id,
            message_id=self.message_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            link_preview_options=link_preview_options,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            entities=entities,
            inline_message_id=None,
            business_connection_id=self.business_connection_id,
        )

    async def edit_caption(
        self,
        caption: str | None = None,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        show_caption_above_media: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Shortcut for::

             await bot.edit_message_caption(
                 chat_id=message.chat_id,
                 message_id=message.message_id,
                 business_connection_id=message.business_connection_id,
                 *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_message_caption`.

        Note:
            You can only edit messages that the bot sent itself (i.e. of the ``bot.send_*`` family
            of methods) or channel posts, if the bot is an admin in that channel. However, this
            behaviour is undocumented and might be changed by Telegram.

        .. versionchanged:: 21.4
           Now also passes :attr:`business_connection_id`.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise ``True`` is returned.

        """
        return await self.get_bot().edit_message_caption(
            chat_id=self.chat_id,
            message_id=self.message_id,
            caption=caption,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            parse_mode=parse_mode,
            api_kwargs=api_kwargs,
            caption_entities=caption_entities,
            inline_message_id=None,
            show_caption_above_media=show_caption_above_media,
            business_connection_id=self.business_connection_id,
        )

    async def edit_checklist(
        self,
        checklist: InputChecklist,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.edit_message_checklist(
                 business_connection_id=message.business_connection_id,
                 chat_id=message.chat_id,
                 message_id=message.message_id,
                 *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_message_checklist`.

        .. versionadded:: 22.3

        Note:
            You can only edit messages that the bot sent itself (i.e. of the ``bot.send_*`` family
            of methods) or channel posts, if the bot is an admin in that channel. However, this
            behaviour is undocumented and might be changed by Telegram.

        Returns:
            :class:`telegram.Message`: On success, the edited Message is returned.

        """
        return await self.get_bot().edit_message_checklist(
            business_connection_id=self.business_connection_id,
            chat_id=self.chat_id,
            message_id=self.message_id,
            checklist=checklist,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_media(
        self,
        media: "InputMedia",
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Shortcut for::

             await bot.edit_message_media(
                 chat_id=message.chat_id,
                 message_id=message.message_id,
                 business_connection_id=message.business_connection_id,
                 *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_message_media`.

        Note:
            You can only edit messages that the bot sent itself(i.e. of the ``bot.send_*`` family
            of methods) or channel posts, if the bot is an admin in that channel. However, this
            behaviour is undocumented and might be changed by Telegram.

        .. versionchanged:: 21.4
           Now also passes :attr:`business_connection_id`.

        Returns:
            :class:`telegram.Message`: On success, if edited message is not an inline message, the
            edited Message is returned, otherwise ``True`` is returned.

        """
        return await self.get_bot().edit_message_media(
            media=media,
            chat_id=self.chat_id,
            message_id=self.message_id,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            inline_message_id=None,
            business_connection_id=self.business_connection_id,
        )

    async def edit_reply_markup(
        self,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Shortcut for::

             await bot.edit_message_reply_markup(
                 chat_id=message.chat_id,
                 message_id=message.message_id,
                 business_connection_id=message.business_connection_id,
                 *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_message_reply_markup`.

        Note:
            You can only edit messages that the bot sent itself (i.e. of the ``bot.send_*`` family
            of methods) or channel posts, if the bot is an admin in that channel. However, this
            behaviour is undocumented and might be changed by Telegram.

        .. versionchanged:: 21.4
           Now also passes :attr:`business_connection_id`.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise ``True`` is returned.
        """
        return await self.get_bot().edit_message_reply_markup(
            chat_id=self.chat_id,
            message_id=self.message_id,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            inline_message_id=None,
            business_connection_id=self.business_connection_id,
        )

    async def edit_live_location(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        horizontal_accuracy: float | None = None,
        heading: int | None = None,
        proximity_alert_radius: int | None = None,
        live_period: TimePeriod | None = None,
        *,
        location: "Location | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Shortcut for::

             await bot.edit_message_live_location(
                 chat_id=message.chat_id,
                 message_id=message.message_id,
                 business_connection_id=message.business_connection_id,
                 *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_message_live_location`.

        Note:
            You can only edit messages that the bot sent itself (i.e. of the ``bot.send_*`` family
            of methods) or channel posts, if the bot is an admin in that channel. However, this
            behaviour is undocumented and might be changed by Telegram.

        .. versionchanged:: 21.4
           Now also passes :attr:`business_connection_id`.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise :obj:`True` is returned.
        """
        return await self.get_bot().edit_message_live_location(
            chat_id=self.chat_id,
            message_id=self.message_id,
            latitude=latitude,
            longitude=longitude,
            location=location,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            horizontal_accuracy=horizontal_accuracy,
            heading=heading,
            proximity_alert_radius=proximity_alert_radius,
            live_period=live_period,
            inline_message_id=None,
            business_connection_id=self.business_connection_id,
        )

    async def stop_live_location(
        self,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Shortcut for::

             await bot.stop_message_live_location(
                 chat_id=message.chat_id,
                 message_id=message.message_id,
                 business_connection_id=message.business_connection_id,
                 *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.stop_message_live_location`.

        Note:
            You can only edit messages that the bot sent itself (i.e. of the ``bot.send_*`` family
            of methods) or channel posts, if the bot is an admin in that channel. However, this
            behaviour is undocumented and might be changed by Telegram.

        .. versionchanged:: 21.4
           Now also passes :attr:`business_connection_id`.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise :obj:`True` is returned.
        """
        return await self.get_bot().stop_message_live_location(
            chat_id=self.chat_id,
            message_id=self.message_id,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            inline_message_id=None,
            business_connection_id=self.business_connection_id,
        )

    async def set_game_score(
        self,
        user_id: int,
        score: int,
        force: bool | None = None,
        disable_edit_message: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Shortcut for::

             await bot.set_game_score(
                 chat_id=message.chat_id, message_id=message.message_id, *args, **kwargs
             )

        For the documentation of the arguments, please see :meth:`telegram.Bot.set_game_score`.

        Note:
            You can only edit messages that the bot sent itself (i.e. of the ``bot.send_*`` family
            of methods) or channel posts, if the bot is an admin in that channel. However, this
            behaviour is undocumented and might be changed by Telegram.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise :obj:`True` is returned.
        """
        return await self.get_bot().set_game_score(
            chat_id=self.chat_id,
            message_id=self.message_id,
            user_id=user_id,
            score=score,
            force=force,
            disable_edit_message=disable_edit_message,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            inline_message_id=None,
        )

    async def get_game_high_scores(
        self,
        user_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple["GameHighScore", ...]:
        """Shortcut for::

             await bot.get_game_high_scores(
                 chat_id=message.chat_id, message_id=message.message_id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_game_high_scores`.

        Note:
            You can only edit messages that the bot sent itself (i.e. of the ``bot.send_*`` family
            of methods) or channel posts, if the bot is an admin in that channel. However, this
            behaviour is undocumented and might be changed by Telegram.

        Returns:
            tuple[:class:`telegram.GameHighScore`]
        """
        return await self.get_bot().get_game_high_scores(
            chat_id=self.chat_id,
            message_id=self.message_id,
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            inline_message_id=None,
        )

    async def delete(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for either::

              await bot.delete_message(
                  chat_id=message.chat_id, message_id=message.message_id, *args, **kwargs
              )

        or::

              await bot.delete_business_messages(
                  business_connection_id=self.business_connection_id,
                  message_ids=[self.message_id],
                  *args,
                  **kwargs,
              )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.delete_message` and :meth:`telegram.Bot.delete_business_messages`.

        .. versionchanged:: 22.4
           Calls either :meth:`telegram.Bot.delete_message`
           or :meth:`telegram.Bot.delete_business_messages` based
           on :attr:`business_connection_id`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        if self.business_connection_id:
            return await self.get_bot().delete_business_messages(
                business_connection_id=self.business_connection_id,
                message_ids=[self.message_id],
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            )
        return await self.get_bot().delete_message(
            chat_id=self.chat_id,
            message_id=self.message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def stop_poll(
        self,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Poll:
        """Shortcut for::

              await bot.stop_poll(
                  chat_id=message.chat_id,
                  message_id=message.message_id,
                  business_connection_id=message.business_connection_id,
                  *args, **kwargs
              )

        For the documentation of the arguments, please see :meth:`telegram.Bot.stop_poll`.

        .. versionchanged:: 21.4
           Now also passes :attr:`business_connection_id`.

        Returns:
            :class:`telegram.Poll`: On success, the stopped Poll with the final results is
            returned.

        """
        return await self.get_bot().stop_poll(
            chat_id=self.chat_id,
            message_id=self.message_id,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=self.business_connection_id,
        )

    async def pin(
        self,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

              await bot.pin_chat_message(
                  chat_id=message.chat_id,
                  message_id=message.message_id,
                  business_connection_id=message.business_connection_id,
                  *args, **kwargs
              )

        For the documentation of the arguments, please see :meth:`telegram.Bot.pin_chat_message`.

        .. versionchanged:: 21.5
            Now also passes :attr:`business_connection_id` to
            :meth:`telegram.Bot.pin_chat_message`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().pin_chat_message(
            chat_id=self.chat_id,
            message_id=self.message_id,
            business_connection_id=self.business_connection_id,
            disable_notification=disable_notification,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unpin(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

              await bot.unpin_chat_message(
                  chat_id=message.chat_id,
                  message_id=message.message_id,
                  business_connection_id=message.business_connection_id,
                  *args, **kwargs
              )

        For the documentation of the arguments, please see :meth:`telegram.Bot.unpin_chat_message`.

        .. versionchanged:: 21.5
            Now also passes :attr:`business_connection_id` to
            :meth:`telegram.Bot.pin_chat_message`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().unpin_chat_message(
            chat_id=self.chat_id,
            message_id=self.message_id,
            business_connection_id=self.business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_forum_topic(
        self,
        name: str | None = None,
        icon_custom_emoji_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.edit_forum_topic(
                chat_id=message.chat_id, message_thread_id=message.message_thread_id, *args,
                **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().edit_forum_topic(
            chat_id=self.chat_id,
            message_thread_id=self.message_thread_id,
            name=name,
            icon_custom_emoji_id=icon_custom_emoji_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def close_forum_topic(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.close_forum_topic(
                chat_id=message.chat_id, message_thread_id=message.message_thread_id, *args,
                **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.close_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().close_forum_topic(
            chat_id=self.chat_id,
            message_thread_id=self.message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def reopen_forum_topic(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

            await bot.reopen_forum_topic(
                chat_id=message.chat_id, message_thread_id=message.message_thread_id, *args,
                **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.reopen_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().reopen_forum_topic(
            chat_id=self.chat_id,
            message_thread_id=self.message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_forum_topic(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.delete_forum_topic(
                chat_id=message.chat_id, message_thread_id=message.message_thread_id, *args,
                **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.delete_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().delete_forum_topic(
            chat_id=self.chat_id,
            message_thread_id=self.message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unpin_all_forum_topic_messages(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.unpin_all_forum_topic_messages(
                chat_id=message.chat_id, message_thread_id=message.message_thread_id, *args,
                **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.unpin_all_forum_topic_messages`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().unpin_all_forum_topic_messages(
            chat_id=self.chat_id,
            message_thread_id=self.message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_reaction(
        self,
        reaction: "Sequence[ReactionType] | ReactionType | Sequence[str] | str | None" = None,
        is_big: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.set_message_reaction(chat_id=message.chat_id, message_id=message.message_id,
                *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.set_message_reaction`.

        .. versionadded:: 20.8

        Returns:
            :obj:`bool` On success, :obj:`True` is returned.
        """
        return await self.get_bot().set_message_reaction(
            chat_id=self.chat_id,
            message_id=self.message_id,
            reaction=reaction,
            is_big=is_big,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def read_business_message(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.read_business_message(
                chat_id=message.chat_id,
                message_id=message.message_id,
                business_connection_id=message.business_connection_id,
                *args, **kwargs
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.read_business_message`.

        .. versionadded:: 22.1

        Returns:
            :obj:`bool` On success, :obj:`True` is returned.
        """
        return await self.get_bot().read_business_message(
            chat_id=self.chat_id,
            message_id=self.message_id,
            business_connection_id=self.business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def approve_suggested_post(
        self,
        send_date: int | dtm.datetime | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.approve_suggested_post(
                 chat_id=message.chat_id,
                 message_id=message.message_id,
                 *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.approve_suggested_post`.

        .. versionadded:: 22.4

        Returns:
            :obj:`bool` On success, :obj:`True` is returned.
        """
        return await self.get_bot().approve_suggested_post(
            chat_id=self.chat_id,
            message_id=self.message_id,
            send_date=send_date,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def decline_suggested_post(
        self,
        comment: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.decline_suggested_post(
                 chat_id=message.chat_id,
                 message_id=message.message_id,
                 *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.decline_suggested_post`.

        .. versionadded:: 22.4

        Returns:
            :obj:`bool` On success, :obj:`True` is returned.
        """
        return await self.get_bot().decline_suggested_post(
            chat_id=self.chat_id,
            message_id=self.message_id,
            comment=comment,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    def parse_entity(self, entity: MessageEntity) -> str:
        """Returns the text from a given :class:`telegram.MessageEntity`.

        Note:
            This method is present because Telegram calculates the offset and length in
            UTF-16 codepoint pairs, which some versions of Python don't handle automatically.
            (That is, you can't just slice ``Message.text`` with the offset and length.)

        Args:
            entity (:class:`telegram.MessageEntity`): The entity to extract the text from. It must
                be an entity that belongs to this message.

        Returns:
            :obj:`str`: The text of the given entity.

        Raises:
            RuntimeError: If the message has no text.

        """
        if not self.text:
            raise RuntimeError("This Message has no 'text'.")

        return parse_message_entity(self.text, entity)

    def parse_caption_entity(self, entity: MessageEntity) -> str:
        """Returns the text from a given :class:`telegram.MessageEntity`.

        Note:
            This method is present because Telegram calculates the offset and length in
            UTF-16 codepoint pairs, which some versions of Python don't handle automatically.
            (That is, you can't just slice ``Message.caption`` with the offset and length.)

        Args:
            entity (:class:`telegram.MessageEntity`): The entity to extract the text from. It must
                be an entity that belongs to this message.

        Returns:
            :obj:`str`: The text of the given entity.

        Raises:
            RuntimeError: If the message has no caption.

        """
        if not self.caption:
            raise RuntimeError("This Message has no 'caption'.")

        return parse_message_entity(self.caption, entity)

    def parse_entities(self, types: list[str | None] | None = None) -> dict[MessageEntity, str]:
        """
        Returns a :obj:`dict` that maps :class:`telegram.MessageEntity` to :obj:`str`.
        It contains entities from this message filtered by their
        :attr:`telegram.MessageEntity.type` attribute as the key, and the text that each entity
        belongs to as the value of the :obj:`dict`.

        Note:
            This method should always be used instead of the :attr:`entities` attribute, since it
            calculates the correct substring from the message text based on UTF-16 codepoints.
            See :attr:`parse_entity` for more info.

        Args:
            types (list[:obj:`str`], optional): List of :class:`telegram.MessageEntity` types as
                strings. If the ``type`` attribute of an entity is contained in this list, it will
                be returned. Defaults to a list of all types. All types can be found as constants
                in :class:`telegram.MessageEntity`.

        Returns:
            dict[:class:`telegram.MessageEntity`, :obj:`str`]: A dictionary of entities mapped to
            the text that belongs to them, calculated based on UTF-16 codepoints.

        """
        return parse_message_entities(self.text, self.entities, types=types)

    def parse_caption_entities(
        self, types: list[str | None] | None = None
    ) -> dict[MessageEntity, str]:
        """
        Returns a :obj:`dict` that maps :class:`telegram.MessageEntity` to :obj:`str`.
        It contains entities from this message's caption filtered by their
        :attr:`telegram.MessageEntity.type` attribute as the key, and the text that each entity
        belongs to as the value of the :obj:`dict`.

        Note:
            This method should always be used instead of the :attr:`caption_entities` attribute,
            since it calculates the correct substring from the message text based on UTF-16
            codepoints. See :attr:`parse_entity` for more info.

        Args:
            types (list[:obj:`str`], optional): List of :class:`telegram.MessageEntity` types as
                strings. If the ``type`` attribute of an entity is contained in this list, it will
                be returned. Defaults to a list of all types. All types can be found as constants
                in :class:`telegram.MessageEntity`.

        Returns:
            dict[:class:`telegram.MessageEntity`, :obj:`str`]: A dictionary of entities mapped to
            the text that belongs to them, calculated based on UTF-16 codepoints.

        """
        return parse_message_entities(self.caption, self.caption_entities, types=types)

    @classmethod
    def _parse_html(
        cls,
        message_text: str | None,
        entities: dict[MessageEntity, str],
        urled: bool = False,
        offset: int = 0,
    ) -> str | None:
        if message_text is None:
            return None

        utf_16_text = message_text.encode(TextEncoding.UTF_16_LE)
        html_text = ""
        last_offset = 0

        sorted_entities = sorted(entities.items(), key=lambda item: item[0].offset)
        parsed_entities = []

        for entity, text in sorted_entities:
            if entity in parsed_entities:
                continue

            nested_entities = {
                e: t
                for (e, t) in sorted_entities
                if e.offset >= entity.offset
                and e.offset + e.length <= entity.offset + entity.length
                and e != entity
            }
            parsed_entities.extend(list(nested_entities.keys()))

            if nested_entities:
                escaped_text = cls._parse_html(
                    text, nested_entities, urled=urled, offset=entity.offset
                )
            else:
                escaped_text = escape(text)

            if entity.type == MessageEntity.TEXT_LINK:
                insert = f'<a href="{entity.url}">{escaped_text}</a>'
            elif entity.type == MessageEntity.TEXT_MENTION and entity.user:
                insert = f'<a href="tg://user?id={entity.user.id}">{escaped_text}</a>'
            elif entity.type == MessageEntity.URL and urled:
                insert = f'<a href="{escaped_text}">{escaped_text}</a>'
            elif entity.type == MessageEntity.BLOCKQUOTE:
                insert = f"<blockquote>{escaped_text}</blockquote>"
            elif entity.type == MessageEntity.EXPANDABLE_BLOCKQUOTE:
                insert = f"<blockquote expandable>{escaped_text}</blockquote>"
            elif entity.type == MessageEntity.BOLD:
                insert = f"<b>{escaped_text}</b>"
            elif entity.type == MessageEntity.ITALIC:
                insert = f"<i>{escaped_text}</i>"
            elif entity.type == MessageEntity.CODE:
                insert = f"<code>{escaped_text}</code>"
            elif entity.type == MessageEntity.PRE:
                if entity.language:
                    insert = f'<pre><code class="{entity.language}">{escaped_text}</code></pre>'
                else:
                    insert = f"<pre>{escaped_text}</pre>"
            elif entity.type == MessageEntity.UNDERLINE:
                insert = f"<u>{escaped_text}</u>"
            elif entity.type == MessageEntity.STRIKETHROUGH:
                insert = f"<s>{escaped_text}</s>"
            elif entity.type == MessageEntity.SPOILER:
                insert = f'<span class="tg-spoiler">{escaped_text}</span>'
            elif entity.type == MessageEntity.CUSTOM_EMOJI:
                insert = f'<tg-emoji emoji-id="{entity.custom_emoji_id}">{escaped_text}</tg-emoji>'
            else:
                insert = escaped_text

            # Make sure to escape the text that is not part of the entity
            # if we're in a nested entity, this is still required, since in that case this
            # text is part of the parent entity
            html_text += (
                escape(
                    utf_16_text[last_offset * 2 : (entity.offset - offset) * 2].decode(
                        TextEncoding.UTF_16_LE
                    )
                )
                + insert
            )

            last_offset = entity.offset - offset + entity.length

        # see comment above
        html_text += escape(utf_16_text[last_offset * 2 :].decode(TextEncoding.UTF_16_LE))

        return html_text

    @property
    def text_html(self) -> str:
        """Creates an HTML-formatted string from the markup entities found in the message.

        Use this if you want to retrieve the message text with the entities formatted as HTML in
        the same way the original message was formatted.

        Warning:
            |text_html|

        .. versionchanged:: 13.10
           Spoiler entities are now formatted as HTML.

        .. versionchanged:: 20.3
           Custom emoji entities are now supported.

        .. versionchanged:: 20.8
           Blockquote entities are now supported.

        Returns:
            :obj:`str`: Message text with entities formatted as HTML.

        """
        return self._parse_html(self.text, self.parse_entities(), urled=False)

    @property
    def text_html_urled(self) -> str:
        """Creates an HTML-formatted string from the markup entities found in the message.

        Use this if you want to retrieve the message text with the entities formatted as HTML.
        This also formats :attr:`telegram.MessageEntity.URL` as a hyperlink.

        Warning:
            |text_html|

        .. versionchanged:: 13.10
           Spoiler entities are now formatted as HTML.

        .. versionchanged:: 20.3
           Custom emoji entities are now supported.

        .. versionchanged:: 20.8
           Blockquote entities are now supported.

        Returns:
            :obj:`str`: Message text with entities formatted as HTML.

        """
        return self._parse_html(self.text, self.parse_entities(), urled=True)

    @property
    def caption_html(self) -> str:
        """Creates an HTML-formatted string from the markup entities found in the message's
        caption.

        Use this if you want to retrieve the message caption with the caption entities formatted as
        HTML in the same way the original message was formatted.

        Warning:
            |text_html|

        .. versionchanged:: 13.10
           Spoiler entities are now formatted as HTML.

        .. versionchanged:: 20.3
           Custom emoji entities are now supported.

        .. versionchanged:: 20.8
           Blockquote entities are now supported.

        Returns:
            :obj:`str`: Message caption with caption entities formatted as HTML.
        """
        return self._parse_html(self.caption, self.parse_caption_entities(), urled=False)

    @property
    def caption_html_urled(self) -> str:
        """Creates an HTML-formatted string from the markup entities found in the message's
        caption.

        Use this if you want to retrieve the message caption with the caption entities formatted as
        HTML. This also formats :attr:`telegram.MessageEntity.URL` as a hyperlink.

        Warning:
            |text_html|

        .. versionchanged:: 13.10
           Spoiler entities are now formatted as HTML.

        .. versionchanged:: 20.3
           Custom emoji entities are now supported.

        .. versionchanged:: 20.8
           Blockquote entities are now supported.

        Returns:
            :obj:`str`: Message caption with caption entities formatted as HTML.
        """
        return self._parse_html(self.caption, self.parse_caption_entities(), urled=True)

    @classmethod
    def _parse_markdown(
        cls,
        message_text: str | None,
        entities: dict[MessageEntity, str],
        urled: bool = False,
        version: MarkdownVersion = 1,
        offset: int = 0,
    ) -> str | None:
        if version == 1:
            for entity_type in (
                MessageEntity.EXPANDABLE_BLOCKQUOTE,
                MessageEntity.BLOCKQUOTE,
                MessageEntity.CUSTOM_EMOJI,
                MessageEntity.SPOILER,
                MessageEntity.STRIKETHROUGH,
                MessageEntity.UNDERLINE,
            ):
                if any(entity.type == entity_type for entity in entities):
                    name = entity_type.name.title().replace("_", " ")  # type:ignore[attr-defined]
                    raise ValueError(f"{name} entities are not supported for Markdown version 1")

        if message_text is None:
            return None

        utf_16_text = message_text.encode(TextEncoding.UTF_16_LE)
        markdown_text = ""
        last_offset = 0

        sorted_entities = sorted(entities.items(), key=lambda item: item[0].offset)
        parsed_entities = []

        for entity, text in sorted_entities:
            if entity in parsed_entities:
                continue

            nested_entities = {
                e: t
                for (e, t) in sorted_entities
                if e.offset >= entity.offset
                and e.offset + e.length <= entity.offset + entity.length
                and e != entity
            }
            parsed_entities.extend(list(nested_entities.keys()))

            if nested_entities:
                if version < 2:
                    raise ValueError("Nested entities are not supported for Markdown version 1")

                escaped_text = cls._parse_markdown(
                    text,
                    nested_entities,
                    urled=urled,
                    offset=entity.offset,
                    version=version,
                )
            else:
                escaped_text = escape_markdown(text, version=version)

            if entity.type == MessageEntity.TEXT_LINK:
                if version == 1:
                    url = entity.url
                else:
                    # Links need special escaping. Also can't have entities nested within
                    url = escape_markdown(
                        entity.url, version=version, entity_type=MessageEntity.TEXT_LINK
                    )
                insert = f"[{escaped_text}]({url})"
            elif entity.type == MessageEntity.TEXT_MENTION and entity.user:
                insert = f"[{escaped_text}](tg://user?id={entity.user.id})"
            elif entity.type == MessageEntity.URL and urled:
                link = text if version == 1 else escaped_text
                insert = f"[{link}]({text})"
            elif entity.type == MessageEntity.BOLD:
                insert = f"*{escaped_text}*"
            elif entity.type == MessageEntity.ITALIC:
                insert = f"_{escaped_text}_"
            elif entity.type == MessageEntity.CODE:
                # Monospace needs special escaping. Also can't have entities nested within
                insert = f"`{escape_markdown(text, version, MessageEntity.CODE)}`"
            elif entity.type == MessageEntity.PRE:
                # Monospace needs special escaping. Also can't have entities nested within
                code = escape_markdown(text, version=version, entity_type=MessageEntity.PRE)
                if entity.language:
                    prefix = f"```{entity.language}\n"
                elif code.startswith("\\"):
                    prefix = "```"
                else:
                    prefix = "```\n"
                insert = f"{prefix}{code}```"
            elif entity.type == MessageEntity.UNDERLINE:
                insert = f"__{escaped_text}__"
            elif entity.type == MessageEntity.STRIKETHROUGH:
                insert = f"~{escaped_text}~"
            elif entity.type == MessageEntity.SPOILER:
                insert = f"||{escaped_text}||"
            elif entity.type in (MessageEntity.BLOCKQUOTE, MessageEntity.EXPANDABLE_BLOCKQUOTE):
                insert = ">" + "\n>".join(escaped_text.splitlines())
                if entity.type == MessageEntity.EXPANDABLE_BLOCKQUOTE:
                    insert = f"{insert}||"
            elif entity.type == MessageEntity.CUSTOM_EMOJI:
                # This should never be needed because ids are numeric but the documentation
                # specifically mentions it so here we are
                custom_emoji_id = escape_markdown(
                    entity.custom_emoji_id,
                    version=version,
                    entity_type=MessageEntity.CUSTOM_EMOJI,
                )
                insert = f"![{escaped_text}](tg://emoji?id={custom_emoji_id})"
            else:
                insert = escaped_text

            # Make sure to escape the text that is not part of the entity
            # if we're in a nested entity, this is still required, since in that case this
            # text is part of the parent entity
            markdown_text += (
                escape_markdown(
                    utf_16_text[last_offset * 2 : (entity.offset - offset) * 2].decode(
                        TextEncoding.UTF_16_LE
                    ),
                    version=version,
                )
                + insert
            )

            last_offset = entity.offset - offset + entity.length

        # see comment above
        markdown_text += escape_markdown(
            utf_16_text[last_offset * 2 :].decode(TextEncoding.UTF_16_LE),
            version=version,
        )

        return markdown_text

    @property
    def text_markdown(self) -> str:
        """Creates an Markdown-formatted string from the markup entities found in the message
        using :class:`telegram.constants.ParseMode.MARKDOWN`.

        Use this if you want to retrieve the message text with the entities formatted as Markdown
        in the same way the original message was formatted.

        Warning:
            |text_markdown|

        Note:
            :tg-const:`telegram.constants.ParseMode.MARKDOWN` is a legacy mode, retained by
            Telegram for backward compatibility. You should use :meth:`text_markdown_v2` instead.

        .. versionchanged:: 20.5
            |custom_emoji_no_md1_support|

        .. versionchanged:: 20.8
            |blockquote_no_md1_support|

        Returns:
            :obj:`str`: Message text with entities formatted as Markdown.

        Raises:
            :exc:`ValueError`: If the message contains underline, strikethrough, spoiler,
                blockquote or nested entities.

        """
        return self._parse_markdown(self.text, self.parse_entities(), urled=False)

    @property
    def text_markdown_v2(self) -> str:
        """Creates an Markdown-formatted string from the markup entities found in the message
        using :class:`telegram.constants.ParseMode.MARKDOWN_V2`.

        Use this if you want to retrieve the message text with the entities formatted as Markdown
        in the same way the original message was formatted.

        Warning:
            |text_markdown|

        .. versionchanged:: 13.10
           Spoiler entities are now formatted as Markdown V2.

        .. versionchanged:: 20.3
           Custom emoji entities are now supported.

        .. versionchanged:: 20.8
           Blockquote entities are now supported.

        Returns:
            :obj:`str`: Message text with entities formatted as Markdown.
        """
        return self._parse_markdown(self.text, self.parse_entities(), urled=False, version=2)

    @property
    def text_markdown_urled(self) -> str:
        """Creates an Markdown-formatted string from the markup entities found in the message
        using :class:`telegram.constants.ParseMode.MARKDOWN`.

        Use this if you want to retrieve the message text with the entities formatted as Markdown.
        This also formats :attr:`telegram.MessageEntity.URL` as a hyperlink.

        Warning:
            |text_markdown|

        Note:
            :tg-const:`telegram.constants.ParseMode.MARKDOWN` is a legacy mode, retained by
            Telegram for backward compatibility. You should use :meth:`text_markdown_v2_urled`
            instead.

        .. versionchanged:: 20.5
            |custom_emoji_no_md1_support|

        .. versionchanged:: 20.8
            |blockquote_no_md1_support|

        Returns:
            :obj:`str`: Message text with entities formatted as Markdown.

        Raises:
            :exc:`ValueError`: If the message contains underline, strikethrough, spoiler,
                blockquote or nested entities.

        """
        return self._parse_markdown(self.text, self.parse_entities(), urled=True)

    @property
    def text_markdown_v2_urled(self) -> str:
        """Creates an Markdown-formatted string from the markup entities found in the message
        using :class:`telegram.constants.ParseMode.MARKDOWN_V2`.

        Use this if you want to retrieve the message text with the entities formatted as Markdown.
        This also formats :attr:`telegram.MessageEntity.URL` as a hyperlink.

        Warning:
            |text_markdown|

        .. versionchanged:: 13.10
           Spoiler entities are now formatted as Markdown V2.

        .. versionchanged:: 20.3
           Custom emoji entities are now supported.

        .. versionchanged:: 20.8
           Blockquote entities are now supported.

        Returns:
            :obj:`str`: Message text with entities formatted as Markdown.
        """
        return self._parse_markdown(self.text, self.parse_entities(), urled=True, version=2)

    @property
    def caption_markdown(self) -> str:
        """Creates an Markdown-formatted string from the markup entities found in the message's
        caption using :class:`telegram.constants.ParseMode.MARKDOWN`.

        Use this if you want to retrieve the message caption with the caption entities formatted as
        Markdown in the same way the original message was formatted.

        Warning:
            |text_markdown|

        Note:
            :tg-const:`telegram.constants.ParseMode.MARKDOWN` is a legacy mode, retained by
            Telegram for backward compatibility. You should use :meth:`caption_markdown_v2`
        .. versionchanged:: 20.5
            |custom_emoji_no_md1_support|

        .. versionchanged:: 20.8
            |blockquote_no_md1_support|

        Returns:
            :obj:`str`: Message caption with caption entities formatted as Markdown.

        Raises:
            :exc:`ValueError`: If the message contains underline, strikethrough, spoiler,
                blockquote or nested entities.

        """
        return self._parse_markdown(self.caption, self.parse_caption_entities(), urled=False)

    @property
    def caption_markdown_v2(self) -> str:
        """Creates an Markdown-formatted string from the markup entities found in the message's
        caption using :class:`telegram.constants.ParseMode.MARKDOWN_V2`.

        Use this if you want to retrieve the message caption with the caption entities formatted as
        Markdown in the same way the original message was formatted.

        Warning:
            |text_markdown|

        .. versionchanged:: 13.10
           Spoiler entities are now formatted as Markdown V2.

        .. versionchanged:: 20.3
           Custom emoji entities are now supported.

        .. versionchanged:: 20.8
           Blockquote entities are now supported.

        Returns:
            :obj:`str`: Message caption with caption entities formatted as Markdown.
        """
        return self._parse_markdown(
            self.caption, self.parse_caption_entities(), urled=False, version=2
        )

    @property
    def caption_markdown_urled(self) -> str:
        """Creates an Markdown-formatted string from the markup entities found in the message's
        caption using :class:`telegram.constants.ParseMode.MARKDOWN`.

        Use this if you want to retrieve the message caption with the caption entities formatted as
        Markdown. This also formats :attr:`telegram.MessageEntity.URL` as a hyperlink.

        Warning:
            |text_markdown|

        Note:
            :tg-const:`telegram.constants.ParseMode.MARKDOWN` is a legacy mode, retained by
            Telegram for backward compatibility. You should use
            :meth:`caption_markdown_v2_urled` instead.

        .. versionchanged:: 20.5
            |custom_emoji_no_md1_support|

        .. versionchanged:: 20.8
            |blockquote_no_md1_support|

        Returns:
            :obj:`str`: Message caption with caption entities formatted as Markdown.

        Raises:
            :exc:`ValueError`: If the message contains underline, strikethrough, spoiler,
                blockquote or nested entities.

        """
        return self._parse_markdown(self.caption, self.parse_caption_entities(), urled=True)

    @property
    def caption_markdown_v2_urled(self) -> str:
        """Creates an Markdown-formatted string from the markup entities found in the message's
        caption using :class:`telegram.constants.ParseMode.MARKDOWN_V2`.

        Use this if you want to retrieve the message caption with the caption entities formatted as
        Markdown. This also formats :attr:`telegram.MessageEntity.URL` as a hyperlink.

        Warning:
            |text_markdown|

        .. versionchanged:: 13.10
           Spoiler entities are now formatted as Markdown V2.

        .. versionchanged:: 20.3
           Custom emoji entities are now supported.

        .. versionchanged:: 20.8
           Blockquote entities are now supported.

        Returns:
            :obj:`str`: Message caption with caption entities formatted as Markdown.
        """
        return self._parse_markdown(
            self.caption, self.parse_caption_entities(), urled=True, version=2
        )
