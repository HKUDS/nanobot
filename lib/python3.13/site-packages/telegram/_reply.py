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
"""This modules contains objects that represents Telegram Replies"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._chat import Chat
from telegram._checklists import Checklist
from telegram._dice import Dice
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
from telegram._games.game import Game
from telegram._giveaway import Giveaway, GiveawayWinners
from telegram._linkpreviewoptions import LinkPreviewOptions
from telegram._messageentity import MessageEntity
from telegram._messageorigin import MessageOrigin
from telegram._paidmedia import PaidMediaInfo
from telegram._payment.invoice import Invoice
from telegram._poll import Poll
from telegram._story import Story
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional, de_list_optional, parse_sequence_arg
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import JSONDict, ODVInput

if TYPE_CHECKING:
    from telegram import Bot


class ExternalReplyInfo(TelegramObject):
    """
    This object contains information about a message that is being replied to, which may
    come from another chat or forum topic.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`origin` is equal.

    .. versionadded:: 20.8

    Args:
        origin (:class:`telegram.MessageOrigin`): Origin of the message replied to by the given
            message.
        chat (:class:`telegram.Chat`, optional): Chat the original message belongs to. Available
            only if the chat is a supergroup or a channel.
        message_id (:obj:`int`, optional): Unique message identifier inside the original chat.
            Available only if the original chat is a supergroup or a channel.
        link_preview_options (:class:`telegram.LinkPreviewOptions`, optional): Options used for
            link preview generation for the original message, if it is a text message
        animation (:class:`telegram.Animation`, optional): Message is an animation, information
            about the animation.
        audio (:class:`telegram.Audio`, optional): Message is an audio file, information about the
            file.
        document (:class:`telegram.Document`, optional): Message is a general file, information
            about the file.
        photo (Sequence[:class:`telegram.PhotoSize`], optional): Message is a photo, available
            sizes of the photo.
        sticker (:class:`telegram.Sticker`, optional): Message is a sticker, information about the
            sticker.
        story (:class:`telegram.Story`, optional): Message is a forwarded story.
        video (:class:`telegram.Video`, optional): Message is a video, information about the video.
        video_note (:class:`telegram.VideoNote`, optional): Message is a `video note
            <https://telegram.org/blog/video-messages-and-telescope>`_, information about the video
            message.
        voice (:class:`telegram.Voice`, optional): Message is a voice message, information about
            the file.
        has_media_spoiler (:obj:`bool`, optional): :obj:`True`, if the message media is covered by
            a spoiler animation.
        checklist (:class:`telegram.Checklist`, optional): Message is a checklist.

            .. versionadded:: 22.3
        contact (:class:`telegram.Contact`, optional): Message is a shared contact, information
            about the contact.
        dice (:class:`telegram.Dice`, optional): Message is a dice with random value.
        game (:Class:`telegram.Game`. optional): Message is a game, information about the game.
            :ref:`More about games >> <games-tree>`.
        giveaway (:class:`telegram.Giveaway`, optional): Message is a scheduled giveaway,
            information about the giveaway.
        giveaway_winners (:class:`telegram.GiveawayWinners`, optional): A giveaway with public
            winners was completed.
        invoice (:class:`telegram.Invoice`, optional): Message is an invoice for a payment,
            information about the invoice. :ref:`More about payments >> <payments-tree>`.
        location (:class:`telegram.Location`, optional): Message is a shared location, information
            about the location.
        poll (:class:`telegram.Poll`, optional): Message is a native poll, information about the
            poll.
        venue (:class:`telegram.Venue`, optional): Message is a venue, information about the venue.
        paid_media (:class:`telegram.PaidMedia`, optional): Message contains paid media;
            information about the paid media.

            .. versionadded:: 21.4

    Attributes:
        origin (:class:`telegram.MessageOrigin`): Origin of the message replied to by the given
            message.
        chat (:class:`telegram.Chat`): Optional. Chat the original message belongs to. Available
            only if the chat is a supergroup or a channel.
        message_id (:obj:`int`): Optional. Unique message identifier inside the original chat.
            Available only if the original chat is a supergroup or a channel.
        link_preview_options (:class:`telegram.LinkPreviewOptions`): Optional. Options used for
            link preview generation for the original message, if it is a text message.
        animation (:class:`telegram.Animation`): Optional. Message is an animation, information
            about the animation.
        audio (:class:`telegram.Audio`): Optional. Message is an audio file, information about the
            file.
        document (:class:`telegram.Document`): Optional. Message is a general file, information
            about the file.
        photo (tuple[:class:`telegram.PhotoSize`]): Optional. Message is a photo, available sizes
            of the photo.
        sticker (:class:`telegram.Sticker`): Optional. Message is a sticker, information about the
            sticker.
        story (:class:`telegram.Story`): Optional. Message is a forwarded story.
        video (:class:`telegram.Video`): Optional. Message is a video, information about the video.
        video_note (:class:`telegram.VideoNote`): Optional. Message is a `video note
            <https://telegram.org/blog/video-messages-and-telescope>`_, information about the video
            message.
        voice (:class:`telegram.Voice`): Optional. Message is a voice message, information about
            the file.
        has_media_spoiler (:obj:`bool`): Optional. :obj:`True`, if the message media is covered by
            a spoiler animation.
        checklist (:class:`telegram.Checklist`): Optional. Message is a checklist.

            .. versionadded:: 22.3
        contact (:class:`telegram.Contact`): Optional. Message is a shared contact, information
            about the contact.
        dice (:class:`telegram.Dice`): Optional. Message is a dice with random value.
        game (:Class:`telegram.Game`): Optional. Message is a game, information about the game.
            :ref:`More about games >> <games-tree>`.
        giveaway (:class:`telegram.Giveaway`): Optional. Message is a scheduled giveaway,
            information about the giveaway.
        giveaway_winners (:class:`telegram.GiveawayWinners`): Optional. A giveaway with public
            winners was completed.
        invoice (:class:`telegram.Invoice`): Optional. Message is an invoice for a payment,
            information about the invoice. :ref:`More about payments >> <payments-tree>`.
        location (:class:`telegram.Location`): Optional. Message is a shared location, information
            about the location.
        poll (:class:`telegram.Poll`): Optional. Message is a native poll, information about the
            poll.
        venue (:class:`telegram.Venue`): Optional. Message is a venue, information about the venue.
        paid_media (:class:`telegram.PaidMedia`): Optional. Message contains paid media;
            information about the paid media.

            .. versionadded:: 21.4
    """

    __slots__ = (
        "animation",
        "audio",
        "chat",
        "checklist",
        "contact",
        "dice",
        "document",
        "game",
        "giveaway",
        "giveaway_winners",
        "has_media_spoiler",
        "invoice",
        "link_preview_options",
        "location",
        "message_id",
        "origin",
        "paid_media",
        "photo",
        "poll",
        "sticker",
        "story",
        "venue",
        "video",
        "video_note",
        "voice",
    )

    def __init__(
        self,
        origin: MessageOrigin,
        chat: Chat | None = None,
        message_id: int | None = None,
        link_preview_options: LinkPreviewOptions | None = None,
        animation: Animation | None = None,
        audio: Audio | None = None,
        document: Document | None = None,
        photo: Sequence[PhotoSize] | None = None,
        sticker: Sticker | None = None,
        story: Story | None = None,
        video: Video | None = None,
        video_note: VideoNote | None = None,
        voice: Voice | None = None,
        has_media_spoiler: bool | None = None,
        contact: "Contact | None" = None,
        dice: Dice | None = None,
        game: Game | None = None,
        giveaway: Giveaway | None = None,
        giveaway_winners: GiveawayWinners | None = None,
        invoice: Invoice | None = None,
        location: "Location | None" = None,
        poll: Poll | None = None,
        venue: Venue | None = None,
        paid_media: PaidMediaInfo | None = None,
        checklist: Checklist | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        self.origin: MessageOrigin = origin
        self.chat: Chat | None = chat
        self.message_id: int | None = message_id
        self.link_preview_options: LinkPreviewOptions | None = link_preview_options
        self.animation: Animation | None = animation
        self.audio: Audio | None = audio
        self.document: Document | None = document
        self.photo: tuple[PhotoSize, ...] | None = parse_sequence_arg(photo)
        self.sticker: Sticker | None = sticker
        self.story: Story | None = story
        self.video: Video | None = video
        self.video_note: VideoNote | None = video_note
        self.voice: Voice | None = voice
        self.has_media_spoiler: bool | None = has_media_spoiler
        self.checklist: Checklist | None = checklist
        self.contact: Contact | None = contact
        self.dice: Dice | None = dice
        self.game: Game | None = game
        self.giveaway: Giveaway | None = giveaway
        self.giveaway_winners: GiveawayWinners | None = giveaway_winners
        self.invoice: Invoice | None = invoice
        self.location: Location | None = location
        self.poll: Poll | None = poll
        self.venue: Venue | None = venue
        self.paid_media: PaidMediaInfo | None = paid_media

        self._id_attrs = (self.origin,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ExternalReplyInfo":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["origin"] = de_json_optional(data.get("origin"), MessageOrigin, bot)
        data["chat"] = de_json_optional(data.get("chat"), Chat, bot)
        data["link_preview_options"] = de_json_optional(
            data.get("link_preview_options"), LinkPreviewOptions, bot
        )
        data["animation"] = de_json_optional(data.get("animation"), Animation, bot)
        data["audio"] = de_json_optional(data.get("audio"), Audio, bot)
        data["document"] = de_json_optional(data.get("document"), Document, bot)
        data["photo"] = de_list_optional(data.get("photo"), PhotoSize, bot)
        data["sticker"] = de_json_optional(data.get("sticker"), Sticker, bot)
        data["story"] = de_json_optional(data.get("story"), Story, bot)
        data["video"] = de_json_optional(data.get("video"), Video, bot)
        data["video_note"] = de_json_optional(data.get("video_note"), VideoNote, bot)
        data["voice"] = de_json_optional(data.get("voice"), Voice, bot)
        data["contact"] = de_json_optional(data.get("contact"), Contact, bot)
        data["dice"] = de_json_optional(data.get("dice"), Dice, bot)
        data["game"] = de_json_optional(data.get("game"), Game, bot)
        data["giveaway"] = de_json_optional(data.get("giveaway"), Giveaway, bot)
        data["giveaway_winners"] = de_json_optional(
            data.get("giveaway_winners"), GiveawayWinners, bot
        )
        data["invoice"] = de_json_optional(data.get("invoice"), Invoice, bot)
        data["location"] = de_json_optional(data.get("location"), Location, bot)
        data["poll"] = de_json_optional(data.get("poll"), Poll, bot)
        data["venue"] = de_json_optional(data.get("venue"), Venue, bot)
        data["paid_media"] = de_json_optional(data.get("paid_media"), PaidMediaInfo, bot)
        data["checklist"] = de_json_optional(data.get("checklist"), Checklist, bot)

        return super().de_json(data=data, bot=bot)


class TextQuote(TelegramObject):
    """
    This object contains information about the quoted part of a message that is replied to
    by the given message.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`text` and :attr:`position` are equal.

    .. versionadded:: 20.8

    Args:
        text (:obj:`str`): Text of the quoted part of a message that is replied to by the given
            message.
        position (:obj:`int`): Approximate quote position in the original message in UTF-16 code
            units as specified by the sender.
        entities (Sequence[:class:`telegram.MessageEntity`], optional): Special entities that
            appear
            in the quote. Currently, only bold, italic, underline, strikethrough, spoiler, and
            custom_emoji entities are kept in quotes.
        is_manual (:obj:`bool`, optional): :obj:`True`, if the quote was chosen manually by the
            message sender. Otherwise, the quote was added automatically by the server.

    Attributes:
        text (:obj:`str`): Text of the quoted part of a message that is replied to by the given
            message.
        position (:obj:`int`): Approximate quote position in the original message in UTF-16 code
            units as specified by the sender.
        entities (tuple[:class:`telegram.MessageEntity`]): Optional. Special entities that appear
            in the quote. Currently, only bold, italic, underline, strikethrough, spoiler, and
            custom_emoji entities are kept in quotes.
        is_manual (:obj:`bool`): Optional. :obj:`True`, if the quote was chosen manually by the
            message sender. Otherwise, the quote was added automatically by the server.
    """

    __slots__ = (
        "entities",
        "is_manual",
        "position",
        "text",
    )

    def __init__(
        self,
        text: str,
        position: int,
        entities: Sequence[MessageEntity] | None = None,
        is_manual: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        self.text: str = text
        self.position: int = position
        self.entities: tuple[MessageEntity, ...] | None = parse_sequence_arg(entities)
        self.is_manual: bool | None = is_manual

        self._id_attrs = (
            self.text,
            self.position,
        )

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "TextQuote":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["entities"] = de_list_optional(data.get("entities"), MessageEntity, bot)

        return super().de_json(data=data, bot=bot)


class ReplyParameters(TelegramObject):
    """
    Describes reply parameters for the message that is being sent.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`message_id` is equal.

    .. versionadded:: 20.8

    .. versionchanged:: 22.5
        The :paramref:`checklist_task_id` parameter has been moved to the last position to
        maintain backward compatibility with versions prior to 22.4.
        This resolves a breaking change accidentally introduced in version 22.4. See the changelog
        for version 22.5 for more information.

    Args:
        message_id (:obj:`int`): Identifier of the message that will be replied to in the current
            chat, or in the chat :paramref:`chat_id` if it is specified.
        chat_id (:obj:`int` | :obj:`str`, optional): If the message to be replied to is from a
            different chat, |chat_id_channel|
            Not supported for messages sent on behalf of a business account and messages from
            channel direct messages chats.
        allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply| Can be
            used only for replies in the same chat and forum topic.
        quote (:obj:`str`, optional): Quoted part of the message to be replied to; 0-1024
            characters after entities parsing. The quote must be an exact substring of the message
            to be replied to, including bold, italic, underline, strikethrough, spoiler, and
            custom_emoji entities. The message will fail to send if the quote isn't found in the
            original message.
        quote_parse_mode (:obj:`str`, optional): Mode for parsing entities in the quote. See
            :wiki:`formatting options <Code-snippets#message-formatting-bold-italic-code->` for
            more details.
        quote_entities (Sequence[:class:`telegram.MessageEntity`], optional): A JSON-serialized
            list
            of special entities that appear in the quote. It can be specified instead of
            :paramref:`quote_parse_mode`.
        quote_position (:obj:`int`, optional): Position of the quote in the original message in
            UTF-16 code units.
        checklist_task_id (:obj:`int`, optional): Identifier of the specific checklist task to be
            replied to.

            .. versionadded:: 22.4

    Attributes:
        message_id (:obj:`int`): Identifier of the message that will be replied to in the current
            chat, or in the chat :paramref:`chat_id` if it is specified.
        chat_id (:obj:`int` | :obj:`str`): Optional. If the message to be replied to is from a
            different chat, |chat_id_channel|
            Not supported for messages sent on behalf of a business account and messages from
            channel direct messages chats.
        allow_sending_without_reply (:obj:`bool`): Optional. |allow_sending_without_reply| Can be
            used only for replies in the same chat and forum topic.
        quote (:obj:`str`): Optional. Quoted part of the message to be replied to; 0-1024
            characters after entities parsing. The quote must be an exact substring of the message
            to be replied to, including bold, italic, underline, strikethrough, spoiler, and
            custom_emoji entities. The message will fail to send if the quote isn't found in the
            original message.
        quote_parse_mode (:obj:`str`): Optional. Mode for parsing entities in the quote. See
            :wiki:`formatting options <Code-snippets#message-formatting-bold-italic-code->` for
            more details.
        quote_entities (tuple[:class:`telegram.MessageEntity`]): Optional. A JSON-serialized list
            of special entities that appear in the quote. It can be specified instead of
            :paramref:`quote_parse_mode`.
        quote_position (:obj:`int`): Optional. Position of the quote in the original message in
            UTF-16 code units.
        checklist_task_id (:obj:`int`): Optional. Identifier of the specific checklist task to be
            replied to.

            .. versionadded:: 22.4
    """

    __slots__ = (
        "allow_sending_without_reply",
        "chat_id",
        "checklist_task_id",
        "message_id",
        "quote",
        "quote_entities",
        "quote_parse_mode",
        "quote_position",
    )

    def __init__(
        self,
        message_id: int,
        chat_id: int | str | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        quote: str | None = None,
        quote_parse_mode: ODVInput[str] = DEFAULT_NONE,
        quote_entities: Sequence[MessageEntity] | None = None,
        quote_position: int | None = None,
        checklist_task_id: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        self.message_id: int = message_id
        self.chat_id: int | str | None = chat_id
        self.allow_sending_without_reply: ODVInput[bool] = allow_sending_without_reply
        self.quote: str | None = quote
        self.quote_parse_mode: ODVInput[str] = quote_parse_mode
        self.quote_entities: tuple[MessageEntity, ...] | None = parse_sequence_arg(quote_entities)
        self.quote_position: int | None = quote_position
        self.checklist_task_id: int | None = checklist_task_id

        self._id_attrs = (self.message_id,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ReplyParameters":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["quote_entities"] = tuple(
            de_list_optional(data.get("quote_entities"), MessageEntity, bot)
        )

        return super().de_json(data=data, bot=bot)
