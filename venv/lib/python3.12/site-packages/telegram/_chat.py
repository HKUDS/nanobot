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
"""This module contains an object that represents a Telegram Chat."""

import datetime as dtm
from collections.abc import Sequence
from html import escape
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._chatpermissions import ChatPermissions
from telegram._forumtopic import ForumTopic
from telegram._menubutton import MenuButton
from telegram._reaction import ReactionType
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import (
    CorrectOptionID,
    FileInput,
    JSONDict,
    ODVInput,
    TimePeriod,
)
from telegram._utils.usernames import get_full_name, get_link
from telegram.helpers import escape_markdown
from telegram.helpers import mention_html as helpers_mention_html
from telegram.helpers import mention_markdown as helpers_mention_markdown

if TYPE_CHECKING:
    from telegram import (
        Animation,
        Audio,
        ChatInviteLink,
        ChatMember,
        Contact,
        Document,
        Gift,
        InlineKeyboardMarkup,
        InputChecklist,
        InputMediaAudio,
        InputMediaDocument,
        InputMediaPhoto,
        InputMediaVideo,
        InputPaidMedia,
        InputPollOption,
        LabeledPrice,
        LinkPreviewOptions,
        Location,
        Message,
        MessageEntity,
        MessageId,
        OwnedGifts,
        PhotoSize,
        ReplyParameters,
        Sticker,
        Story,
        SuggestedPostParameters,
        UserChatBoosts,
        Venue,
        Video,
        VideoNote,
        Voice,
    )
    from telegram._utils.types import ReplyMarkup


class _ChatBase(TelegramObject):
    """Base class for :class:`telegram.Chat` and :class:`telegram.ChatFullInfo`.

    .. versionadded:: 21.3
    """

    __slots__ = (
        "first_name",
        "id",
        "is_direct_messages",
        "is_forum",
        "last_name",
        "title",
        "type",
        "username",
    )

    def __init__(
        self,
        id: int,
        type: str,
        title: str | None = None,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        is_forum: bool | None = None,
        is_direct_messages: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.id: int = id
        self.type: str = enum.get_member(constants.ChatType, type, type)
        # Optionals
        self.title: str | None = title
        self.username: str | None = username
        self.first_name: str | None = first_name
        self.last_name: str | None = last_name
        self.is_forum: bool | None = is_forum
        self.is_direct_messages: bool | None = is_direct_messages

        self._id_attrs = (self.id,)

        self._freeze()

    SENDER: Final[str] = constants.ChatType.SENDER
    """:const:`telegram.constants.ChatType.SENDER`

    .. versionadded:: 13.5
    """
    PRIVATE: Final[str] = constants.ChatType.PRIVATE
    """:const:`telegram.constants.ChatType.PRIVATE`"""
    GROUP: Final[str] = constants.ChatType.GROUP
    """:const:`telegram.constants.ChatType.GROUP`"""
    SUPERGROUP: Final[str] = constants.ChatType.SUPERGROUP
    """:const:`telegram.constants.ChatType.SUPERGROUP`"""
    CHANNEL: Final[str] = constants.ChatType.CHANNEL
    """:const:`telegram.constants.ChatType.CHANNEL`"""

    @property
    def effective_name(self) -> str | None:
        """
        :obj:`str`: Convenience property. Gives :attr:`~Chat.title` if not :obj:`None`,
        else :attr:`~Chat.full_name` if not :obj:`None`.

        .. versionadded:: 20.1
        """
        if self.title is not None:
            return self.title
        if self.full_name is not None:
            return self.full_name
        return None

    @property
    def full_name(self) -> str | None:
        """
        :obj:`str`: Convenience property. If :attr:`~Chat.first_name` is not :obj:`None`, gives
        :attr:`~Chat.first_name` followed by (if available) :attr:`~Chat.last_name`.

        Note:
            :attr:`full_name` will always be :obj:`None`, if the chat is a (super)group or
            channel.

        .. versionadded:: 13.2
        """
        return get_full_name(self)

    @property
    def link(self) -> str | None:
        """:obj:`str`: Convenience property. If the chat has a :attr:`~Chat.username`, returns a
        t.me link of the chat.
        """
        return get_link(self)

    def mention_markdown(self, name: str | None = None) -> str:
        """
        Note:
            :tg-const:`telegram.constants.ParseMode.MARKDOWN` is a legacy mode, retained by
            Telegram for backward compatibility. You should use :meth:`mention_markdown_v2`
            instead.

        .. versionadded:: 20.0

        Args:
            name (:obj:`str`): The name used as a link for the chat. Defaults to
                :attr:`~Chat.full_name`.

        Returns:
            :obj:`str`: The inline mention for the chat as markdown (version 1).

        Raises:
            :exc:`TypeError`: If the chat is a private chat and neither the :paramref:`name`
                nor the :attr:`~Chat.first_name` is set, then throw an :exc:`TypeError`.
                If the chat is a public chat and neither the :paramref:`name` nor the
                :attr:`~Chat.title` is set, then throw an :exc:`TypeError`. If chat is a
                private group chat, then throw an :exc:`TypeError`.

        """
        if self.type == self.PRIVATE:
            if name:
                return helpers_mention_markdown(self.id, name)
            if self.full_name:
                return helpers_mention_markdown(self.id, self.full_name)
            raise TypeError("Can not create a mention to a private chat without first name")
        if self.username:
            if name:
                return f"[{name}]({self.link})"
            if self.title:
                return f"[{self.title}]({self.link})"
            raise TypeError("Can not create a mention to a public chat without title")
        raise TypeError("Can not create a mention to a private group chat")

    def mention_markdown_v2(self, name: str | None = None) -> str:
        """
        .. versionadded:: 20.0

        Args:
            name (:obj:`str`): The name used as a link for the chat. Defaults to
                :attr:`~Chat.full_name`.

        Returns:
            :obj:`str`: The inline mention for the chat as markdown (version 2).

        Raises:
            :exc:`TypeError`: If the chat is a private chat and neither the :paramref:`name`
                nor the :attr:`~Chat.first_name` is set, then throw an :exc:`TypeError`.
                If the chat is a public chat and neither the :paramref:`name` nor the
                :attr:`~Chat.title` is set, then throw an :exc:`TypeError`. If chat is a
                private group chat, then throw an :exc:`TypeError`.

        """
        if self.type == self.PRIVATE:
            if name:
                return helpers_mention_markdown(self.id, name, version=2)
            if self.full_name:
                return helpers_mention_markdown(self.id, self.full_name, version=2)
            raise TypeError("Can not create a mention to a private chat without first name")
        if self.username:
            if name:
                return f"[{escape_markdown(name, version=2)}]({self.link})"
            if self.title:
                return f"[{escape_markdown(self.title, version=2)}]({self.link})"
            raise TypeError("Can not create a mention to a public chat without title")
        raise TypeError("Can not create a mention to a private group chat")

    def mention_html(self, name: str | None = None) -> str:
        """
        .. versionadded:: 20.0

        Args:
            name (:obj:`str`): The name used as a link for the chat. Defaults to :attr:`full_name`.

        Returns:
            :obj:`str`: The inline mention for the chat as HTML.

        Raises:
            :exc:`TypeError`: If the chat is a private chat and neither the :paramref:`name`
                nor the :attr:`~Chat.first_name` is set, then throw an :exc:`TypeError`.
                If the chat is a public chat and neither the :paramref:`name` nor the
                :attr:`~Chat.title` is set, then throw an :exc:`TypeError`.
                If chat is a private group chat, then throw an :exc:`TypeError`.

        """
        if self.type == self.PRIVATE:
            if name:
                return helpers_mention_html(self.id, name)
            if self.full_name:
                return helpers_mention_html(self.id, self.full_name)
            raise TypeError("Can not create a mention to a private chat without first name")
        if self.username:
            if name:
                return f'<a href="{self.link}">{escape(name)}</a>'
            if self.title:
                return f'<a href="{self.link}">{escape(self.title)}</a>'
            raise TypeError("Can not create a mention to a public chat without title")
        raise TypeError("Can not create a mention to a private group chat")

    async def leave(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.leave_chat(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.leave_chat`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().leave_chat(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_administrators(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple["ChatMember", ...]:
        """Shortcut for::

             await bot.get_chat_administrators(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_chat_administrators`.

        Returns:
            tuple[:class:`telegram.ChatMember`]: A tuple of administrators in a chat. An Array of
            :class:`telegram.ChatMember` objects that contains information about all
            chat administrators except other bots. If the chat is a group or a supergroup
            and no administrators were appointed, only the creator will be returned.

        """
        return await self.get_bot().get_chat_administrators(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_member_count(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> int:
        """Shortcut for::

             await bot.get_chat_member_count(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_chat_member_count`.

        Returns:
            :obj:`int`
        """
        return await self.get_bot().get_chat_member_count(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_member(
        self,
        user_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "ChatMember":
        """Shortcut for::

             await bot.get_chat_member(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.get_chat_member`.

        Returns:
            :class:`telegram.ChatMember`

        """
        return await self.get_bot().get_chat_member(
            chat_id=self.id,
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def ban_member(
        self,
        user_id: int,
        revoke_messages: bool | None = None,
        until_date: int | dtm.datetime | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.ban_chat_member(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.ban_chat_member`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().ban_chat_member(
            chat_id=self.id,
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            until_date=until_date,
            api_kwargs=api_kwargs,
            revoke_messages=revoke_messages,
        )

    async def ban_sender_chat(
        self,
        sender_chat_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.ban_chat_sender_chat(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.ban_chat_sender_chat`.

        .. versionadded:: 13.9

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().ban_chat_sender_chat(
            chat_id=self.id,
            sender_chat_id=sender_chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def ban_chat(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.ban_chat_sender_chat(
                 sender_chat_id=update.effective_chat.id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.ban_chat_sender_chat`.

        .. versionadded:: 13.9

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().ban_chat_sender_chat(
            chat_id=chat_id,
            sender_chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unban_sender_chat(
        self,
        sender_chat_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.unban_chat_sender_chat(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.unban_chat_sender_chat`.

        .. versionadded:: 13.9

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().unban_chat_sender_chat(
            chat_id=self.id,
            sender_chat_id=sender_chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unban_chat(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.unban_chat_sender_chat(
                 sender_chat_id=update.effective_chat.id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.unban_chat_sender_chat`.

        .. versionadded:: 13.9

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().unban_chat_sender_chat(
            chat_id=chat_id,
            sender_chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unban_member(
        self,
        user_id: int,
        only_if_banned: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.unban_chat_member(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.unban_chat_member`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().unban_chat_member(
            chat_id=self.id,
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            only_if_banned=only_if_banned,
        )

    async def promote_member(
        self,
        user_id: int,
        can_change_info: bool | None = None,
        can_post_messages: bool | None = None,
        can_edit_messages: bool | None = None,
        can_delete_messages: bool | None = None,
        can_invite_users: bool | None = None,
        can_restrict_members: bool | None = None,
        can_pin_messages: bool | None = None,
        can_promote_members: bool | None = None,
        is_anonymous: bool | None = None,
        can_manage_chat: bool | None = None,
        can_manage_video_chats: bool | None = None,
        can_manage_topics: bool | None = None,
        can_post_stories: bool | None = None,
        can_edit_stories: bool | None = None,
        can_delete_stories: bool | None = None,
        can_manage_direct_messages: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.promote_chat_member(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.promote_chat_member`.

        .. versionadded:: 13.2
        .. versionchanged:: 20.0
           The argument ``can_manage_voice_chats`` was renamed to
           :paramref:`~telegram.Bot.promote_chat_member.can_manage_video_chats` in accordance to
           Bot API 6.0.
        .. versionchanged:: 20.6
           The arguments `can_post_stories`, `can_edit_stories` and `can_delete_stories` were
           added.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().promote_chat_member(
            chat_id=self.id,
            user_id=user_id,
            can_change_info=can_change_info,
            can_post_messages=can_post_messages,
            can_edit_messages=can_edit_messages,
            can_delete_messages=can_delete_messages,
            can_invite_users=can_invite_users,
            can_restrict_members=can_restrict_members,
            can_pin_messages=can_pin_messages,
            can_promote_members=can_promote_members,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            is_anonymous=is_anonymous,
            can_manage_chat=can_manage_chat,
            can_manage_video_chats=can_manage_video_chats,
            can_manage_topics=can_manage_topics,
            can_post_stories=can_post_stories,
            can_edit_stories=can_edit_stories,
            can_delete_stories=can_delete_stories,
            can_manage_direct_messages=can_manage_direct_messages,
        )

    async def restrict_member(
        self,
        user_id: int,
        permissions: ChatPermissions,
        until_date: int | dtm.datetime | None = None,
        use_independent_chat_permissions: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.restrict_chat_member(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.restrict_chat_member`.

        .. versionadded:: 13.2

        .. versionadded:: 20.1
            Added :paramref:`~telegram.Bot.restrict_chat_member.use_independent_chat_permissions`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().restrict_chat_member(
            chat_id=self.id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date,
            use_independent_chat_permissions=use_independent_chat_permissions,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_permissions(
        self,
        permissions: ChatPermissions,
        use_independent_chat_permissions: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.set_chat_permissions(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.set_chat_permissions`.

        .. versionadded:: 20.1
            Added :paramref:`~telegram.Bot.set_chat_permissions.use_independent_chat_permissions`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().set_chat_permissions(
            chat_id=self.id,
            permissions=permissions,
            use_independent_chat_permissions=use_independent_chat_permissions,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_administrator_custom_title(
        self,
        user_id: int,
        custom_title: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.set_chat_administrator_custom_title(
                 update.effective_chat.id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.set_chat_administrator_custom_title`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().set_chat_administrator_custom_title(
            chat_id=self.id,
            user_id=user_id,
            custom_title=custom_title,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_photo(
        self,
        photo: FileInput,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.set_chat_photo(
                 chat_id=update.effective_chat.id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.set_chat_photo`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().set_chat_photo(
            chat_id=self.id,
            photo=photo,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_photo(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.delete_chat_photo(
                 chat_id=update.effective_chat.id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.delete_chat_photo`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().delete_chat_photo(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_title(
        self,
        title: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.set_chat_title(
                 chat_id=update.effective_chat.id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.set_chat_title`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().set_chat_title(
            chat_id=self.id,
            title=title,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_description(
        self,
        description: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.set_chat_description(
                 chat_id=update.effective_chat.id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.set_chat_description`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().set_chat_description(
            chat_id=self.id,
            description=description,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def pin_message(
        self,
        message_id: int,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

              await bot.pin_chat_message(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.pin_chat_message`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().pin_chat_message(
            chat_id=self.id,
            message_id=message_id,
            disable_notification=disable_notification,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
        )

    async def unpin_message(
        self,
        message_id: int | None = None,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

              await bot.unpin_chat_message(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.unpin_chat_message`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().unpin_chat_message(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            message_id=message_id,
            business_connection_id=business_connection_id,
        )

    async def unpin_all_messages(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

              await bot.unpin_all_chat_messages(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.unpin_all_chat_messages`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().unpin_all_chat_messages(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def send_message(
        self,
        text: str,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        link_preview_options: ODVInput["LinkPreviewOptions"] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        disable_web_page_preview: bool | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_message(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_message`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_message(
            chat_id=self.id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            link_preview_options=link_preview_options,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            entities=entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_message_draft(
        self,
        draft_id: int,
        text: str,
        message_thread_id: int | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        entities: Sequence["MessageEntity"] | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.send_message_draft(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_message_draft`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().send_message_draft(
            chat_id=self.id,
            draft_id=draft_id,
            text=text,
            message_thread_id=message_thread_id,
            parse_mode=parse_mode,
            entities=entities,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_message(
        self,
        message_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.delete_message(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.delete_message`.

        .. versionadded:: 20.8

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().delete_message(
            chat_id=self.id,
            message_id=message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_messages(
        self,
        message_ids: Sequence[int],
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.delete_messages(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.delete_messages`.

        .. versionadded:: 20.8

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().delete_messages(
            chat_id=self.id,
            message_ids=message_ids,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def send_media_group(
        self,
        media: Sequence[
            "InputMediaAudio | InputMediaDocument | InputMediaPhoto | InputMediaVideo"
        ],
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
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

             await bot.send_media_group(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_media_group`.

        Returns:
            tuple[:class:`telegram.Message`]: On success, a tuple of :class:`~telegram.Message`
            instances that were sent is returned.

        """
        return await self.get_bot().send_media_group(
            chat_id=self.id,
            media=media,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            reply_parameters=reply_parameters,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
        )

    async def send_chat_action(
        self,
        action: str,
        message_thread_id: int | None = None,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.send_chat_action(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_chat_action`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().send_chat_action(
            chat_id=self.id,
            action=action,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
        )

    send_action = send_chat_action
    """Alias for :attr:`send_chat_action`"""

    async def send_photo(
        self,
        photo: "FileInput | PhotoSize",
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        has_spoiler: bool | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        show_caption_above_media: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_photo(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_photo`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_photo(
            chat_id=self.id,
            photo=photo,
            caption=caption,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            allow_sending_without_reply=allow_sending_without_reply,
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
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            show_caption_above_media=show_caption_above_media,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_contact(
        self,
        phone_number: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        vcard: str | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        contact: "Contact | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_contact(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_contact`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_contact(
            chat_id=self.id,
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            contact=contact,
            vcard=vcard,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_audio(
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
        message_thread_id: int | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_audio(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_audio`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_audio(
            chat_id=self.id,
            audio=audio,
            duration=duration,
            performer=performer,
            title=title,
            caption=caption,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            allow_sending_without_reply=allow_sending_without_reply,
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
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_document(
        self,
        document: "FileInput | Document",
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        disable_content_type_detection: bool | None = None,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_document(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_document`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_document(
            chat_id=self.id,
            document=document,
            filename=filename,
            caption=caption,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            parse_mode=parse_mode,
            thumbnail=thumbnail,
            api_kwargs=api_kwargs,
            disable_content_type_detection=disable_content_type_detection,
            allow_sending_without_reply=allow_sending_without_reply,
            caption_entities=caption_entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_checklist(
        self,
        business_connection_id: str,
        checklist: "InputChecklist",
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_checklist(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_checklist`.

        .. versionadded:: 22.3

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_checklist(
            chat_id=self.id,
            business_connection_id=business_connection_id,
            checklist=checklist,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_effect_id=message_effect_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=allow_sending_without_reply,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def send_dice(
        self,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        emoji: str | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_dice(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_dice`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_dice(
            chat_id=self.id,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            emoji=emoji,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_game(
        self,
        game_short_name: str,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_game(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_game`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_game(
            chat_id=self.id,
            game_short_name=game_short_name,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
        )

    async def send_invoice(
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
        provider_data: str | object | None = None,
        send_phone_number_to_provider: bool | None = None,
        send_email_to_provider: bool | None = None,
        max_tip_amount: int | None = None,
        suggested_tip_amounts: Sequence[int] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_invoice(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_invoice`.

        Warning:
            As of API 5.2 :paramref:`start_parameter <telegram.Bot.send_invoice.start_parameter>`
            is an optional argument and therefore the
            order of the arguments had to be changed. Use keyword arguments to make sure that the
            arguments are passed correctly.

        .. versionchanged:: 13.5
            As of Bot API 5.2, the parameter
            :paramref:`start_parameter <telegram.Bot.send_invoice.start_parameter>` is optional.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_invoice(
            chat_id=self.id,
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
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            provider_data=provider_data,
            send_phone_number_to_provider=send_phone_number_to_provider,
            send_email_to_provider=send_email_to_provider,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            max_tip_amount=max_tip_amount,
            suggested_tip_amounts=suggested_tip_amounts,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_location(
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
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        location: "Location | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_location(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_location`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_location(
            chat_id=self.id,
            latitude=latitude,
            longitude=longitude,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
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
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_animation(
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
        message_thread_id: int | None = None,
        has_spoiler: bool | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        show_caption_above_media: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_animation(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_animation`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_animation(
            chat_id=self.id,
            animation=animation,
            duration=duration,
            width=width,
            height=height,
            caption=caption,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            caption_entities=caption_entities,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            has_spoiler=has_spoiler,
            thumbnail=thumbnail,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            show_caption_above_media=show_caption_above_media,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_sticker(
        self,
        sticker: "FileInput | Sticker",
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        emoji: str | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_sticker(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_sticker`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_sticker(
            chat_id=self.id,
            sticker=sticker,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            emoji=emoji,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_venue(
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
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        venue: "Venue | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_venue(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_venue`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_venue(
            chat_id=self.id,
            latitude=latitude,
            longitude=longitude,
            title=title,
            address=address,
            foursquare_id=foursquare_id,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
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
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_video(
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
        message_thread_id: int | None = None,
        has_spoiler: bool | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        show_caption_above_media: bool | None = None,
        cover: "FileInput | None" = None,
        start_timestamp: int | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_video(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_video`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_video(
            chat_id=self.id,
            video=video,
            duration=duration,
            caption=caption,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            width=width,
            height=height,
            parse_mode=parse_mode,
            supports_streaming=supports_streaming,
            thumbnail=thumbnail,
            cover=cover,
            start_timestamp=start_timestamp,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            caption_entities=caption_entities,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            has_spoiler=has_spoiler,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            show_caption_above_media=show_caption_above_media,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_video_note(
        self,
        video_note: "FileInput | VideoNote",
        duration: TimePeriod | None = None,
        length: int | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_video_note(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_video_note`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_video_note(
            chat_id=self.id,
            video_note=video_note,
            duration=duration,
            length=length,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            thumbnail=thumbnail,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_voice(
        self,
        voice: "FileInput | Voice",
        duration: TimePeriod | None = None,
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_voice(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_voice`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_voice(
            chat_id=self.id,
            voice=voice,
            duration=duration,
            caption=caption,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            parse_mode=parse_mode,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            caption_entities=caption_entities,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_poll(
        self,
        question: str,
        options: Sequence["str | InputPollOption"],
        is_anonymous: bool | None = None,
        type: str | None = None,
        allows_multiple_answers: bool | None = None,
        correct_option_id: CorrectOptionID | None = None,
        is_closed: bool | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        explanation: str | None = None,
        explanation_parse_mode: ODVInput[str] = DEFAULT_NONE,
        open_period: TimePeriod | None = None,
        close_date: int | dtm.datetime | None = None,
        explanation_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        question_parse_mode: ODVInput[str] = DEFAULT_NONE,
        question_entities: Sequence["MessageEntity"] | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_poll(update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_poll`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_poll(
            chat_id=self.id,
            question=question,
            options=options,
            is_anonymous=is_anonymous,
            type=type,  # pylint=pylint,
            allows_multiple_answers=allows_multiple_answers,
            correct_option_id=correct_option_id,
            is_closed=is_closed,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            explanation=explanation,
            explanation_parse_mode=explanation_parse_mode,
            open_period=open_period,
            close_date=close_date,
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            explanation_entities=explanation_entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            question_parse_mode=question_parse_mode,
            question_entities=question_entities,
        )

    async def send_copy(
        self,
        from_chat_id: str | int,
        message_id: int,
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
        direct_messages_topic_id: int | None = None,
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

             await bot.copy_message(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.copy_message`.

        .. seealso:: :meth:`copy_message`, :meth:`send_copies`, :meth:`copy_messages`.

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().copy_message(
            chat_id=self.id,
            from_chat_id=from_chat_id,
            message_id=message_id,
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
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
            message_effect_id=message_effect_id,
        )

    async def copy_message(
        self,
        chat_id: int | str,
        message_id: int,
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
        direct_messages_topic_id: int | None = None,
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

             await bot.copy_message(from_chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.copy_message`.

        .. seealso:: :meth:`send_copy`, :meth:`send_copies`, :meth:`copy_messages`.

        Returns:
            :class:`telegram.MessageId`: On success, returns the MessageId of the sent message.

        """
        return await self.get_bot().copy_message(
            from_chat_id=self.id,
            chat_id=chat_id,
            message_id=message_id,
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
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
            message_effect_id=message_effect_id,
        )

    async def send_copies(
        self,
        from_chat_id: str | int,
        message_ids: Sequence[int],
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        remove_caption: bool | None = None,
        direct_messages_topic_id: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple["MessageId", ...]:
        """Shortcut for::

             await bot.copy_messages(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.copy_messages`.

        .. seealso:: :meth:`copy_message`, :meth:`send_copy`, :meth:`copy_messages`.

        .. versionadded:: 20.8

        Returns:
            tuple[:class:`telegram.MessageId`]: On success, a tuple of :class:`~telegram.MessageId`
            of the sent messages is returned.

        """
        return await self.get_bot().copy_messages(
            chat_id=self.id,
            from_chat_id=from_chat_id,
            message_ids=message_ids,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            remove_caption=remove_caption,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            direct_messages_topic_id=direct_messages_topic_id,
        )

    async def copy_messages(
        self,
        chat_id: str | int,
        message_ids: Sequence[int],
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        remove_caption: bool | None = None,
        direct_messages_topic_id: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple["MessageId", ...]:
        """Shortcut for::

             await bot.copy_messages(from_chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.copy_messages`.

        .. seealso:: :meth:`copy_message`, :meth:`send_copy`, :meth:`send_copies`.

        .. versionadded:: 20.8

        Returns:
            tuple[:class:`telegram.MessageId`]: On success, a tuple of :class:`~telegram.MessageId`
            of the sent messages is returned.

        """
        return await self.get_bot().copy_messages(
            from_chat_id=self.id,
            chat_id=chat_id,
            message_ids=message_ids,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            remove_caption=remove_caption,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            direct_messages_topic_id=direct_messages_topic_id,
        )

    async def forward_from(
        self,
        from_chat_id: str | int,
        message_id: int,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        video_start_timestamp: int | None = None,
        direct_messages_topic_id: int | None = None,
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

             await bot.forward_message(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.forward_message`.

        .. seealso:: :meth:`forward_to`, :meth:`forward_messages_from`, :meth:`forward_messages_to`

        .. versionadded:: 20.0

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().forward_message(
            chat_id=self.id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            video_start_timestamp=video_start_timestamp,
            disable_notification=disable_notification,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
            message_effect_id=message_effect_id,
        )

    async def forward_to(
        self,
        chat_id: int | str,
        message_id: int,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        video_start_timestamp: int | None = None,
        direct_messages_topic_id: int | None = None,
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

             await bot.forward_message(from_chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.forward_message`.

        .. seealso:: :meth:`forward_from`, :meth:`forward_messages_from`,
            :meth:`forward_messages_to`

        .. versionadded:: 20.0

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().forward_message(
            from_chat_id=self.id,
            chat_id=chat_id,
            message_id=message_id,
            video_start_timestamp=video_start_timestamp,
            disable_notification=disable_notification,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
            message_effect_id=message_effect_id,
        )

    async def forward_messages_from(
        self,
        from_chat_id: str | int,
        message_ids: Sequence[int],
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple["MessageId", ...]:
        """Shortcut for::

             await bot.forward_messages(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.forward_messages`.

        .. seealso:: :meth:`forward_to`, :meth:`forward_from`, :meth:`forward_messages_to`.

        .. versionadded:: 20.8

        Returns:
            tuple[:class:`telegram.MessageId`]: On success, a tuple of :class:`~telegram.MessageId`
            of sent messages is returned.

        """
        return await self.get_bot().forward_messages(
            chat_id=self.id,
            from_chat_id=from_chat_id,
            message_ids=message_ids,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            direct_messages_topic_id=direct_messages_topic_id,
        )

    async def forward_messages_to(
        self,
        chat_id: int | str,
        message_ids: Sequence[int],
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple["MessageId", ...]:
        """Shortcut for::

             await bot.forward_messages(from_chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.forward_messages`.

        .. seealso:: :meth:`forward_from`, :meth:`forward_to`, :meth:`forward_messages_from`.

        .. versionadded:: 20.8

        Returns:
            tuple[:class:`telegram.MessageId`]: On success, a tuple of :class:`~telegram.MessageId`
            of sent messages is returned.

        """
        return await self.get_bot().forward_messages(
            from_chat_id=self.id,
            chat_id=chat_id,
            message_ids=message_ids,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            direct_messages_topic_id=direct_messages_topic_id,
        )

    async def export_invite_link(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> str:
        """Shortcut for::

             await bot.export_chat_invite_link(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.export_chat_invite_link`.

        .. versionadded:: 13.4

        Returns:
            :obj:`str`: New invite link on success.

        """
        return await self.get_bot().export_chat_invite_link(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def create_invite_link(
        self,
        expire_date: int | dtm.datetime | None = None,
        member_limit: int | None = None,
        name: str | None = None,
        creates_join_request: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "ChatInviteLink":
        """Shortcut for::

             await bot.create_chat_invite_link(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.create_chat_invite_link`.

        .. versionadded:: 13.4

        .. versionchanged:: 13.8
           Edited signature according to the changes of
           :meth:`telegram.Bot.create_chat_invite_link`.

        Returns:
            :class:`telegram.ChatInviteLink`

        """
        return await self.get_bot().create_chat_invite_link(
            chat_id=self.id,
            expire_date=expire_date,
            member_limit=member_limit,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            name=name,
            creates_join_request=creates_join_request,
        )

    async def edit_invite_link(
        self,
        invite_link: "str | ChatInviteLink",
        expire_date: int | dtm.datetime | None = None,
        member_limit: int | None = None,
        name: str | None = None,
        creates_join_request: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "ChatInviteLink":
        """Shortcut for::

             await bot.edit_chat_invite_link(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_chat_invite_link`.

        .. versionadded:: 13.4

        .. versionchanged:: 13.8
           Edited signature according to the changes of :meth:`telegram.Bot.edit_chat_invite_link`.

        Returns:
            :class:`telegram.ChatInviteLink`

        """
        return await self.get_bot().edit_chat_invite_link(
            chat_id=self.id,
            invite_link=invite_link,
            expire_date=expire_date,
            member_limit=member_limit,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            name=name,
            creates_join_request=creates_join_request,
        )

    async def revoke_invite_link(
        self,
        invite_link: "str | ChatInviteLink",
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "ChatInviteLink":
        """Shortcut for::

             await bot.revoke_chat_invite_link(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.revoke_chat_invite_link`.

        .. versionadded:: 13.4

        Returns:
            :class:`telegram.ChatInviteLink`

        """
        return await self.get_bot().revoke_chat_invite_link(
            chat_id=self.id,
            invite_link=invite_link,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def create_subscription_invite_link(
        self,
        subscription_period: TimePeriod,
        subscription_price: int,
        name: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "ChatInviteLink":
        """Shortcut for::

            await bot.create_chat_subscription_invite_link(
                chat_id=update.effective_chat.id, *args, **kwargs
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.create_chat_subscription_invite_link`.

        .. versionadded:: 21.5

        Returns:
            :class:`telegram.ChatInviteLink`
        """
        return await self.get_bot().create_chat_subscription_invite_link(
            chat_id=self.id,
            subscription_period=subscription_period,
            subscription_price=subscription_price,
            name=name,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_subscription_invite_link(
        self,
        invite_link: "str | ChatInviteLink",
        name: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "ChatInviteLink":
        """Shortcut for::

            await bot.edit_chat_subscription_invite_link(
                chat_id=update.effective_chat.id, *args, **kwargs
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_chat_subscription_invite_link`.

        .. versionadded:: 21.5

        Returns:
            :class:`telegram.ChatInviteLink`

        """
        return await self.get_bot().edit_chat_subscription_invite_link(
            chat_id=self.id,
            invite_link=invite_link,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            name=name,
        )

    async def approve_join_request(
        self,
        user_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.approve_chat_join_request(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.approve_chat_join_request`.

        .. versionadded:: 13.8

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().approve_chat_join_request(
            chat_id=self.id,
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def decline_join_request(
        self,
        user_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.decline_chat_join_request(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.decline_chat_join_request`.

        .. versionadded:: 13.8

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().decline_chat_join_request(
            chat_id=self.id,
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_menu_button(
        self,
        menu_button: MenuButton | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.set_chat_menu_button(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.set_chat_menu_button`.

        Caution:
            Can only work, if the chat is a private chat.

        .. seealso:: :meth:`get_menu_button`

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().set_chat_menu_button(
            chat_id=self.id,
            menu_button=menu_button,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def create_forum_topic(
        self,
        name: str,
        icon_color: int | None = None,
        icon_custom_emoji_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> ForumTopic:
        """Shortcut for::

             await bot.create_forum_topic(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.create_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :class:`telegram.ForumTopic`
        """
        return await self.get_bot().create_forum_topic(
            chat_id=self.id,
            name=name,
            icon_color=icon_color,
            icon_custom_emoji_id=icon_custom_emoji_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_forum_topic(
        self,
        message_thread_id: int,
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

             await bot.edit_forum_topic(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().edit_forum_topic(
            chat_id=self.id,
            message_thread_id=message_thread_id,
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
        message_thread_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.close_forum_topic(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.close_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().close_forum_topic(
            chat_id=self.id,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def reopen_forum_topic(
        self,
        message_thread_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.reopen_forum_topic(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.reopen_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().reopen_forum_topic(
            chat_id=self.id,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_forum_topic(
        self,
        message_thread_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.delete_forum_topic(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.delete_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().delete_forum_topic(
            chat_id=self.id,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unpin_all_forum_topic_messages(
        self,
        message_thread_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.unpin_all_forum_topic_messages(chat_id=update.effective_chat.id,
                *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.unpin_all_forum_topic_messages`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().unpin_all_forum_topic_messages(
            chat_id=self.id,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unpin_all_general_forum_topic_messages(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.unpin_all_general_forum_topic_messages(chat_id=update.effective_chat.id,
                *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.unpin_all_general_forum_topic_messages`.

        .. versionadded:: 20.5

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().unpin_all_general_forum_topic_messages(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_general_forum_topic(
        self,
        name: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.edit_general_forum_topic(
                chat_id=update.effective_chat.id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_general_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().edit_general_forum_topic(
            chat_id=self.id,
            name=name,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def close_general_forum_topic(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.close_general_forum_topic(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.close_general_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().close_general_forum_topic(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def reopen_general_forum_topic(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.reopen_general_forum_topic(
                chat_id=update.effective_chat.id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.reopen_general_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().reopen_general_forum_topic(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def hide_general_forum_topic(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.hide_general_forum_topic(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.hide_general_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().hide_general_forum_topic(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unhide_general_forum_topic(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.unhide_general_forum_topic (
                chat_id=update.effective_chat.id, *args, **kwargs
             )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.unhide_general_forum_topic`.

        .. versionadded:: 20.0

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().unhide_general_forum_topic(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_menu_button(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> MenuButton:
        """Shortcut for::

             await bot.get_chat_menu_button(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_chat_menu_button`.

        Caution:
            Can only work, if the chat is a private chat.

        .. seealso:: :meth:`set_menu_button`

        .. versionadded:: 20.0

        Returns:
            :class:`telegram.MenuButton`: On success, the current menu button is returned.
        """
        return await self.get_bot().get_chat_menu_button(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_user_chat_boosts(
        self,
        user_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "UserChatBoosts":
        """Shortcut for::

             await bot.get_user_chat_boosts(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_user_chat_boosts`.

        .. versionadded:: 20.8

        Returns:
            :class:`telegram.UserChatBoosts`: On success, returns the boosts applied in the chat.
        """
        return await self.get_bot().get_user_chat_boosts(
            chat_id=self.id,
            user_id=user_id,
            api_kwargs=api_kwargs,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
        )

    async def set_message_reaction(
        self,
        message_id: int,
        reaction: Sequence[ReactionType | str] | ReactionType | str | None = None,
        is_big: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.set_message_reaction(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.set_message_reaction`.

        .. versionadded:: 20.8

        Returns:
            :obj:`bool` On success, :obj:`True` is returned.
        """
        return await self.get_bot().set_message_reaction(
            chat_id=self.id,
            message_id=message_id,
            reaction=reaction,
            is_big=is_big,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def send_paid_media(
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
        business_connection_id: str | None = None,
        payload: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        message_thread_id: int | None = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_paid_media(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.send_paid_media`.

        .. versionadded:: 21.4

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.
        """
        return await self.get_bot().send_paid_media(
            chat_id=self.id,
            star_count=star_count,
            media=media,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            show_caption_above_media=show_caption_above_media,
            disable_notification=disable_notification,
            protect_content=protect_content,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            reply_to_message_id=reply_to_message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            payload=payload,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
            message_thread_id=message_thread_id,
        )

    async def send_gift(
        self,
        gift_id: "str | Gift",
        text: str | None = None,
        text_parse_mode: ODVInput[str] = DEFAULT_NONE,
        text_entities: Sequence["MessageEntity"] | None = None,
        pay_for_upgrade: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.send_gift(user_id=update.effective_chat.id, *args, **kwargs )

        or::

            await bot.send_gift(chat_id=update.effective_chat.id, *args, **kwargs )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_gift`.

        Caution:
            Will only work if the chat is a private or channel chat, see :attr:`type`.

        .. versionadded:: 21.8

        .. versionchanged:: 21.11

            Added support for channel chats.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().send_gift(
            gift_id=gift_id,
            text=text,
            text_parse_mode=text_parse_mode,
            text_entities=text_entities,
            pay_for_upgrade=pay_for_upgrade,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            **{"chat_id" if self.type == Chat.CHANNEL else "user_id": self.id},
        )

    async def transfer_gift(
        self,
        business_connection_id: str,
        owned_gift_id: str,
        star_count: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.transfer_gift(new_owner_chat_id=update.effective_chat.id, *args, **kwargs )

        For the documentation of the arguments, please see :meth:`telegram.Bot.transfer_gift`.

        .. versionadded:: 22.1

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().transfer_gift(
            new_owner_chat_id=self.id,
            business_connection_id=business_connection_id,
            owned_gift_id=owned_gift_id,
            star_count=star_count,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def verify(
        self,
        custom_description: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.verify_chat(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.verify_chat`.

        .. versionadded:: 21.10

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().verify_chat(
            chat_id=self.id,
            custom_description=custom_description,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def remove_verification(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.remove_chat_verification(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.remove_chat_verification`.

        .. versionadded:: 21.10

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().remove_chat_verification(
            chat_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def read_business_message(
        self,
        business_connection_id: str,
        message_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.read_business_message(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.read_business_message`.

        .. versionadded:: 22.1

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().read_business_message(
            chat_id=self.id,
            business_connection_id=business_connection_id,
            message_id=message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def approve_suggested_post(
        self,
        message_id: int,
        send_date: int | dtm.datetime | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Shortcut for::

             await bot.approve_suggested_post(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.approve_suggested_post`.

        .. versionadded:: 22.4

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().approve_suggested_post(
            chat_id=self.id,
            message_id=message_id,
            send_date=send_date,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def decline_suggested_post(
        self,
        message_id: int,
        comment: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Shortcut for::

             await bot.decline_suggested_post(chat_id=update.effective_chat.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.decline_suggested_post`.

        .. versionadded:: 22.4

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().decline_suggested_post(
            chat_id=self.id,
            message_id=message_id,
            comment=comment,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def repost_story(
        self,
        business_connection_id: str,
        from_story_id: int,
        active_period: TimePeriod,
        post_to_chat_page: bool | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Story":
        """Shortcut for::

             await bot.repost_story(
                from_chat_id=update.effective_chat.id,
                *args, **kwargs
            )

        For the documentation of the arguments, please see :meth:`telegram.Bot.repost_story`.

        .. versionadded:: 22.6

        Returns:
            :class:`Story`: On success, :class:`Story` is returned.

        """
        return await self.get_bot().repost_story(
            business_connection_id=business_connection_id,
            from_chat_id=self.id,
            from_story_id=from_story_id,
            active_period=active_period,
            post_to_chat_page=post_to_chat_page,
            protect_content=protect_content,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_gifts(
        self,
        exclude_unsaved: bool | None = None,
        exclude_saved: bool | None = None,
        exclude_unlimited: bool | None = None,
        exclude_limited_upgradable: bool | None = None,
        exclude_limited_non_upgradable: bool | None = None,
        exclude_from_blockchain: bool | None = None,
        exclude_unique: bool | None = None,
        sort_by_price: bool | None = None,
        offset: str | None = None,
        limit: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "OwnedGifts":
        """Shortcut for::

             await bot.get_chat_gifts(chat_id=update.effective_chat.id)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_chat_gifts`.

        .. versionadded:: 22.6

        Returns:
            :class:`telegram.OwnedGifts`: On success, returns the gifts owned by the chat.
        """
        return await self.get_bot().get_chat_gifts(
            chat_id=self.id,
            exclude_unsaved=exclude_unsaved,
            exclude_saved=exclude_saved,
            exclude_unlimited=exclude_unlimited,
            exclude_limited_upgradable=exclude_limited_upgradable,
            exclude_limited_non_upgradable=exclude_limited_non_upgradable,
            exclude_from_blockchain=exclude_from_blockchain,
            exclude_unique=exclude_unique,
            sort_by_price=sort_by_price,
            offset=offset,
            limit=limit,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )


class Chat(_ChatBase):
    """This object represents a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`id` is equal.

    .. versionchanged:: 20.0

        * Removed the deprecated methods ``kick_member`` and ``get_members_count``.
        * The following are now keyword-only arguments in Bot methods:
          ``location``, ``filename``, ``contact``, ``{read, write, connect, pool}_timeout``,
          ``api_kwargs``. Use a named argument for those,
          and notice that some positional arguments changed position as a result.

    .. versionchanged:: 20.0
        Removed the attribute ``all_members_are_administrators``. As long as Telegram provides
        this field for backwards compatibility, it is available through
        :attr:`~telegram.TelegramObject.api_kwargs`.

    .. versionchanged:: 21.3
        As per Bot API 7.3, most of the arguments and attributes of this class have now moved to
        :class:`telegram.ChatFullInfo`.

    Args:
        id (:obj:`int`): Unique identifier for this chat.
        type (:obj:`str`): Type of chat, can be either :attr:`PRIVATE`, :attr:`GROUP`,
            :attr:`SUPERGROUP` or :attr:`CHANNEL`.
        title (:obj:`str`, optional): Title, for supergroups, channels and group chats.
        username (:obj:`str`, optional): Username, for private chats, supergroups and channels if
            available.
        first_name (:obj:`str`, optional): First name of the other party in a private chat.
        last_name (:obj:`str`, optional): Last name of the other party in a private chat.
        is_forum (:obj:`bool`, optional): :obj:`True`, if the supergroup chat is a forum
            (has topics_ enabled).

            .. versionadded:: 20.0
        is_direct_messages (:obj:`bool`, optional): :obj:`True`, if the chat is the direct messages
            chat of a channel.

            .. versionadded:: 22.4

    Attributes:
        id (:obj:`int`): Unique identifier for this chat.
        type (:obj:`str`): Type of chat, can be either :attr:`PRIVATE`, :attr:`GROUP`,
            :attr:`SUPERGROUP` or :attr:`CHANNEL`.
        title (:obj:`str`): Optional. Title, for supergroups, channels and group chats.
        username (:obj:`str`): Optional. Username, for private chats, supergroups and channels if
            available.
        first_name (:obj:`str`): Optional. First name of the other party in a private chat.
        last_name (:obj:`str`): Optional. Last name of the other party in a private chat.
        is_forum (:obj:`bool`): Optional. :obj:`True`, if the supergroup chat is a forum
            (has topics_ enabled).

            .. versionadded:: 20.0
        is_direct_messages (:obj:`bool`): Optional. :obj:`True`, if the chat is the direct messages
            chat of a channel.

            .. versionadded:: 22.4

    .. _topics: https://telegram.org/blog/topics-in-groups-collectible-usernames#topics-in-groups
    """

    __slots__ = ()
