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
"""This module contains an object that represents a Telegram ChatPermission."""

from typing import TYPE_CHECKING

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class ChatPermissions(TelegramObject):
    """Describes actions that a non-administrator user is allowed to take in a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`can_send_messages`,
    :attr:`can_send_polls`, :attr:`can_send_other_messages`, :attr:`can_add_web_page_previews`,
    :attr:`can_change_info`, :attr:`can_invite_users`, :attr:`can_pin_messages`,
    :attr:`can_send_audios`, :attr:`can_send_documents`, :attr:`can_send_photos`,
    :attr:`can_send_videos`, :attr:`can_send_video_notes`, :attr:`can_send_voice_notes`, and
    :attr:`can_manage_topics` are equal.

    .. versionchanged:: 20.0
        :attr:`can_manage_topics` is considered as well when comparing objects of
        this type in terms of equality.
    .. versionchanged:: 20.5

        * :attr:`can_send_audios`, :attr:`can_send_documents`, :attr:`can_send_photos`,
          :attr:`can_send_videos`, :attr:`can_send_video_notes` and :attr:`can_send_voice_notes`
          are considered as well when comparing objects of this type in terms of equality.
        * Removed deprecated argument and attribute ``can_send_media_messages``.


    Note:
        Though not stated explicitly in the official docs, Telegram changes not only the
        permissions that are set, but also sets all the others to :obj:`False`. However, since not
        documented, this behavior may change unbeknown to PTB.

    Args:
        can_send_messages (:obj:`bool`, optional): :obj:`True`, if the user is allowed to send text
            messages, contacts, locations and venues.
        can_send_polls (:obj:`bool`, optional): :obj:`True`, if the user is allowed to send polls.
        can_send_other_messages (:obj:`bool`, optional): :obj:`True`, if the user is allowed to
            send animations, games, stickers and use inline bots.
        can_add_web_page_previews (:obj:`bool`, optional): :obj:`True`, if the user is allowed to
            add web page previews to their messages.
        can_change_info (:obj:`bool`, optional): :obj:`True`, if the user is allowed to change the
            chat title, photo and other settings. Ignored in public supergroups.
        can_invite_users (:obj:`bool`, optional): :obj:`True`, if the user is allowed to invite new
            users to the chat.
        can_pin_messages (:obj:`bool`, optional): :obj:`True`, if the user is allowed to pin
            messages. Ignored in public supergroups.
        can_manage_topics (:obj:`bool`, optional): :obj:`True`, if the user is allowed
            to create forum topics. If omitted defaults to the value of
            :attr:`can_pin_messages`.

            .. versionadded:: 20.0
        can_send_audios (:obj:`bool`): :obj:`True`, if the user is allowed to send audios.

            .. versionadded:: 20.1
        can_send_documents (:obj:`bool`): :obj:`True`, if the user is allowed to send documents.

            .. versionadded:: 20.1
        can_send_photos (:obj:`bool`): :obj:`True`, if the user is allowed to send photos.

            .. versionadded:: 20.1
        can_send_videos (:obj:`bool`): :obj:`True`, if the user is allowed to send videos.

            .. versionadded:: 20.1
        can_send_video_notes (:obj:`bool`): :obj:`True`, if the user is allowed to send video
            notes.

            .. versionadded:: 20.1
        can_send_voice_notes (:obj:`bool`): :obj:`True`, if the user is allowed to send voice
            notes.

            .. versionadded:: 20.1

    Attributes:
        can_send_messages (:obj:`bool`): Optional. :obj:`True`, if the user is allowed to send text
            messages, contacts, locations and venues.
        can_send_polls (:obj:`bool`): Optional. :obj:`True`, if the user is allowed to send polls,
            implies :attr:`can_send_messages`.
        can_send_other_messages (:obj:`bool`): Optional. :obj:`True`, if the user is allowed to
            send animations, games, stickers and use inline bots.
        can_add_web_page_previews (:obj:`bool`): Optional. :obj:`True`, if the user is allowed to
            add web page previews to their messages.
        can_change_info (:obj:`bool`): Optional. :obj:`True`, if the user is allowed to change the
            chat title, photo and other settings. Ignored in public supergroups.
        can_invite_users (:obj:`bool`): Optional. :obj:`True`, if the user is allowed to invite
            new users to the chat.
        can_pin_messages (:obj:`bool`): Optional. :obj:`True`, if the user is allowed to pin
            messages. Ignored in public supergroups.
        can_manage_topics (:obj:`bool`): Optional. :obj:`True`, if the user is allowed
            to create forum topics. If omitted defaults to the value of
            :attr:`can_pin_messages`.

            .. versionadded:: 20.0
        can_send_audios (:obj:`bool`): :obj:`True`, if the user is allowed to send audios.

            .. versionadded:: 20.1
        can_send_documents (:obj:`bool`): :obj:`True`, if the user is allowed to send documents.

            .. versionadded:: 20.1
        can_send_photos (:obj:`bool`): :obj:`True`, if the user is allowed to send photos.

            .. versionadded:: 20.1
        can_send_videos (:obj:`bool`): :obj:`True`, if the user is allowed to send videos.

            .. versionadded:: 20.1
        can_send_video_notes (:obj:`bool`): :obj:`True`, if the user is allowed to send video
            notes.

            .. versionadded:: 20.1
        can_send_voice_notes (:obj:`bool`): :obj:`True`, if the user is allowed to send voice
            notes.

            .. versionadded:: 20.1

    """

    __slots__ = (
        "can_add_web_page_previews",
        "can_change_info",
        "can_invite_users",
        "can_manage_topics",
        "can_pin_messages",
        "can_send_audios",
        "can_send_documents",
        "can_send_messages",
        "can_send_other_messages",
        "can_send_photos",
        "can_send_polls",
        "can_send_video_notes",
        "can_send_videos",
        "can_send_voice_notes",
    )

    def __init__(
        self,
        can_send_messages: bool | None = None,
        can_send_polls: bool | None = None,
        can_send_other_messages: bool | None = None,
        can_add_web_page_previews: bool | None = None,
        can_change_info: bool | None = None,
        can_invite_users: bool | None = None,
        can_pin_messages: bool | None = None,
        can_manage_topics: bool | None = None,
        can_send_audios: bool | None = None,
        can_send_documents: bool | None = None,
        can_send_photos: bool | None = None,
        can_send_videos: bool | None = None,
        can_send_video_notes: bool | None = None,
        can_send_voice_notes: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.can_send_messages: bool | None = can_send_messages
        self.can_send_polls: bool | None = can_send_polls
        self.can_send_other_messages: bool | None = can_send_other_messages
        self.can_add_web_page_previews: bool | None = can_add_web_page_previews
        self.can_change_info: bool | None = can_change_info
        self.can_invite_users: bool | None = can_invite_users
        self.can_pin_messages: bool | None = can_pin_messages
        self.can_manage_topics: bool | None = can_manage_topics
        self.can_send_audios: bool | None = can_send_audios
        self.can_send_documents: bool | None = can_send_documents
        self.can_send_photos: bool | None = can_send_photos
        self.can_send_videos: bool | None = can_send_videos
        self.can_send_video_notes: bool | None = can_send_video_notes
        self.can_send_voice_notes: bool | None = can_send_voice_notes

        self._id_attrs = (
            self.can_send_messages,
            self.can_send_polls,
            self.can_send_other_messages,
            self.can_add_web_page_previews,
            self.can_change_info,
            self.can_invite_users,
            self.can_pin_messages,
            self.can_manage_topics,
            self.can_send_audios,
            self.can_send_documents,
            self.can_send_photos,
            self.can_send_videos,
            self.can_send_video_notes,
            self.can_send_voice_notes,
        )

        self._freeze()

    @classmethod
    def all_permissions(cls) -> "ChatPermissions":
        """
        This method returns an :class:`ChatPermissions` instance with all attributes
        set to :obj:`True`. This is e.g. useful when unrestricting a chat member with
        :meth:`telegram.Bot.restrict_chat_member`.

        .. versionadded:: 20.0

        """
        return cls(*(14 * (True,)))

    @classmethod
    def no_permissions(cls) -> "ChatPermissions":
        """
        This method returns an :class:`ChatPermissions` instance
        with all attributes set to :obj:`False`.

        .. versionadded:: 20.0
        """
        return cls(*(14 * (False,)))

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChatPermissions":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        api_kwargs = {}
        # This is a deprecated field that TG still returns for backwards compatibility
        # Let's filter it out to speed up the de-json process
        if data.get("can_send_media_messages") is not None:
            api_kwargs["can_send_media_messages"] = data.pop("can_send_media_messages")

        return super()._de_json(data=data, bot=bot, api_kwargs=api_kwargs)
