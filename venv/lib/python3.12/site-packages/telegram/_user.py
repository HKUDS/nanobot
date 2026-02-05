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
"""This module contains an object that represents a Telegram User."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._inline.inlinekeyboardbutton import InlineKeyboardButton
from telegram._menubutton import MenuButton
from telegram._telegramobject import TelegramObject
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import (
    CorrectOptionID,
    JSONDict,
    ODVInput,
    TimePeriod,
)
from telegram._utils.usernames import get_full_name, get_link, get_name
from telegram.helpers import mention_html as helpers_mention_html
from telegram.helpers import mention_markdown as helpers_mention_markdown

if TYPE_CHECKING:
    from telegram import (
        Animation,
        Audio,
        Contact,
        Document,
        Gift,
        InlineKeyboardMarkup,
        InputMediaAudio,
        InputMediaDocument,
        InputMediaPhoto,
        InputMediaVideo,
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
        UserProfilePhotos,
        Venue,
        Video,
        VideoNote,
        Voice,
    )
    from telegram._utils.types import FileInput, ReplyMarkup


class User(TelegramObject):
    """This object represents a Telegram user or bot.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`id` is equal.

    .. versionchanged:: 20.0
        The following are now keyword-only arguments in Bot methods:
        ``location``, ``filename``, ``venue``, ``contact``,
        ``{read, write, connect, pool}_timeout`` ``api_kwargs``. Use a named argument for those,
        and notice that some positional arguments changed position as a result.

    Args:
        id (:obj:`int`): Unique identifier for this user or bot.
        is_bot (:obj:`bool`): :obj:`True`, if this user is a bot.
        first_name (:obj:`str`): User's or bot's first name.
        last_name (:obj:`str`, optional): User's or bot's last name.
        username (:obj:`str`, optional): User's or bot's username.
        language_code (:obj:`str`, optional): IETF language tag of the user's language.
        can_join_groups (:obj:`str`, optional): :obj:`True`, if the bot can be invited to groups.
            Returned only in :meth:`telegram.Bot.get_me`.
        can_read_all_group_messages (:obj:`str`, optional): :obj:`True`, if privacy mode is
            disabled for the bot. Returned only in :meth:`telegram.Bot.get_me`.
        supports_inline_queries (:obj:`str`, optional): :obj:`True`, if the bot supports inline
            queries. Returned only in :meth:`telegram.Bot.get_me`.

        is_premium (:obj:`bool`, optional): :obj:`True`, if this user is a Telegram Premium user.

            .. versionadded:: 20.0
        added_to_attachment_menu (:obj:`bool`, optional): :obj:`True`, if this user added
            the bot to the attachment menu.

            .. versionadded:: 20.0
        can_connect_to_business (:obj:`bool`, optional): :obj:`True`,  if the bot can be connected
            to a Telegram Business account to receive its messages. Returned only in
            :meth:`telegram.Bot.get_me`.

            .. versionadded:: 21.1
        has_main_web_app (:obj:`bool`, optional): :obj:`True`, if the bot has the main Web App.
            Returned only in :meth:`telegram.Bot.get_me`.

            .. versionadded:: 21.5
        has_topics_enabled (:obj:`bool`, optional): :obj:`True`, if the bot has forum topic mode
            enabled in private chats. Returned only in :meth:`telegram.Bot.get_me`.

            .. versionadded:: 22.6

    Attributes:
        id (:obj:`int`): Unique identifier for this user or bot.
        is_bot (:obj:`bool`): :obj:`True`, if this user is a bot.
        first_name (:obj:`str`): User's or bot's first name.
        last_name (:obj:`str`): Optional. User's or bot's last name.
        username (:obj:`str`): Optional. User's or bot's username.
        language_code (:obj:`str`): Optional. IETF language tag of the user's language.
        can_join_groups (:obj:`str`): Optional. :obj:`True`, if the bot can be invited to groups.
            Returned only in :attr:`telegram.Bot.get_me` requests.
        can_read_all_group_messages (:obj:`str`): Optional. :obj:`True`, if privacy mode is
            disabled for the bot. Returned only in :attr:`telegram.Bot.get_me` requests.
        supports_inline_queries (:obj:`str`): Optional. :obj:`True`, if the bot supports inline
            queries. Returned only in :attr:`telegram.Bot.get_me` requests.
        is_premium (:obj:`bool`): Optional. :obj:`True`, if this user is a Telegram
            Premium user.

            .. versionadded:: 20.0
        added_to_attachment_menu (:obj:`bool`): Optional. :obj:`True`, if this user added
            the bot to the attachment menu.

            .. versionadded:: 20.0
        can_connect_to_business (:obj:`bool`): Optional. :obj:`True`,  if the bot can be connected
            to a Telegram Business account to receive its messages. Returned only in
            :meth:`telegram.Bot.get_me`.

            .. versionadded:: 21.1
        has_main_web_app (:obj:`bool`) Optional. :obj:`True`, if the bot has the main Web App.
            Returned only in :meth:`telegram.Bot.get_me`.

            .. versionadded:: 21.5
        has_topics_enabled (:obj:`bool`): Optional. :obj:`True`, if the bot has forum topic mode
            enabled in private chats. Returned only in :meth:`telegram.Bot.get_me`.

            .. versionadded:: 22.6

    .. |user_chat_id_note| replace:: This shortcuts build on the assumption that :attr:`User.id`
        coincides with the :attr:`Chat.id` of the private chat with the user. This has been the
        case so far, but Telegram does not guarantee that this stays this way.
    """

    __slots__ = (
        "added_to_attachment_menu",
        "can_connect_to_business",
        "can_join_groups",
        "can_read_all_group_messages",
        "first_name",
        "has_main_web_app",
        "has_topics_enabled",
        "id",
        "is_bot",
        "is_premium",
        "language_code",
        "last_name",
        "supports_inline_queries",
        "username",
    )

    def __init__(
        self,
        id: int,
        first_name: str,
        is_bot: bool,
        last_name: str | None = None,
        username: str | None = None,
        language_code: str | None = None,
        can_join_groups: bool | None = None,
        can_read_all_group_messages: bool | None = None,
        supports_inline_queries: bool | None = None,
        is_premium: bool | None = None,
        added_to_attachment_menu: bool | None = None,
        can_connect_to_business: bool | None = None,
        has_main_web_app: bool | None = None,
        has_topics_enabled: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.id: int = id
        self.first_name: str = first_name
        self.is_bot: bool = is_bot
        # Optionals
        self.last_name: str | None = last_name
        self.username: str | None = username
        self.language_code: str | None = language_code
        self.can_join_groups: bool | None = can_join_groups
        self.can_read_all_group_messages: bool | None = can_read_all_group_messages
        self.supports_inline_queries: bool | None = supports_inline_queries
        self.is_premium: bool | None = is_premium
        self.added_to_attachment_menu: bool | None = added_to_attachment_menu
        self.can_connect_to_business: bool | None = can_connect_to_business
        self.has_main_web_app: bool | None = has_main_web_app
        self.has_topics_enabled: bool | None = has_topics_enabled

        self._id_attrs = (self.id,)

        self._freeze()

    @property
    def name(self) -> str:
        """:obj:`str`: Convenience property. If available, returns the user's :attr:`username`
        prefixed with "@". If :attr:`username` is not available, returns :attr:`full_name`.
        """
        return get_name(self)

    @property
    def full_name(self) -> str:
        """:obj:`str`: Convenience property. The user's :attr:`first_name`, followed by (if
        available) :attr:`last_name`.
        """
        return get_full_name(self)

    @property
    def link(self) -> str | None:
        """:obj:`str`: Convenience property. If :attr:`username` is available, returns a t.me link
        of the user.
        """
        return get_link(self)

    async def get_profile_photos(
        self,
        offset: int | None = None,
        limit: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "UserProfilePhotos":
        """Shortcut for::

             await bot.get_user_profile_photos(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_user_profile_photos`.

        Returns:
            :class:`telegram.UserProfilePhotos`

        """
        return await self.get_bot().get_user_profile_photos(
            user_id=self.id,
            offset=offset,
            limit=limit,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    def mention_markdown(self, name: str | None = None) -> str:
        """
        Note:
            :tg-const:`telegram.constants.ParseMode.MARKDOWN` is a legacy mode, retained by
            Telegram for backward compatibility. You should use :meth:`mention_markdown_v2`
            instead.

        Args:
            name (:obj:`str`): The name used as a link for the user. Defaults to :attr:`full_name`.

        Returns:
            :obj:`str`: The inline mention for the user as markdown (version 1).

        """
        if name:
            return helpers_mention_markdown(self.id, name)
        return helpers_mention_markdown(self.id, self.full_name)

    def mention_markdown_v2(self, name: str | None = None) -> str:
        """
        Args:
            name (:obj:`str`): The name used as a link for the user. Defaults to :attr:`full_name`.

        Returns:
            :obj:`str`: The inline mention for the user as markdown (version 2).

        """
        if name:
            return helpers_mention_markdown(self.id, name, version=2)
        return helpers_mention_markdown(self.id, self.full_name, version=2)

    def mention_html(self, name: str | None = None) -> str:
        """
        Args:
            name (:obj:`str`): The name used as a link for the user. Defaults to :attr:`full_name`.

        Returns:
            :obj:`str`: The inline mention for the user as HTML.

        """
        if name:
            return helpers_mention_html(self.id, name)
        return helpers_mention_html(self.id, self.full_name)

    def mention_button(self, name: str | None = None) -> InlineKeyboardButton:
        """Shortcut for::

            InlineKeyboardButton(text=name, url=f"tg://user?id={update.effective_user.id}")

        .. versionadded:: 13.9

        Args:
            name (:obj:`str`): The name used as a link for the user. Defaults to :attr:`full_name`.

        Returns:
            :class:`telegram.InlineKeyboardButton`: InlineButton with url set to the user mention
        """
        return InlineKeyboardButton(text=name or self.full_name, url=f"tg://user?id={self.id}")

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

              await bot.pin_chat_message(chat_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.pin_chat_message`.

        Note:
            |user_chat_id_note|

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
            business_connection_id=business_connection_id,
            api_kwargs=api_kwargs,
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

              await bot.unpin_chat_message(chat_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.unpin_chat_message`.

        Note:
            |user_chat_id_note|

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

              await bot.unpin_all_chat_messages(chat_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.unpin_all_chat_messages`.

        Note:
            |user_chat_id_note|

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
        disable_web_page_preview: bool | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message":
        """Shortcut for::

             await bot.send_message(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_message`.

        Note:
            |user_chat_id_note|

        Returns:
            :class:`telegram.Message`: On success, instance representing the message posted.

        """
        return await self.get_bot().send_message(
            chat_id=self.id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            link_preview_options=link_preview_options,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
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

             await bot.send_message_draft(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_message_draft`.

        Note:
            |user_chat_id_note|

        .. versionadded:: 22.6

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

             await bot.delete_message(update.effective_user.id, *argss, **kwargs)

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

             await bot.delete_messages(update.effective_user.id, *argss, **kwargs)

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

             await bot.send_photo(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_photo`.

        Note:
            |user_chat_id_note|

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

             await bot.send_media_group(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_media_group`.

        Note:
            |user_chat_id_note|

        Returns:
            tuple[:class:`telegram.Message`:] On success, a tuple of :class:`~telegram.Message`
            instances that were sent is returned.

        """
        return await self.get_bot().send_media_group(
            chat_id=self.id,
            media=media,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_parameters=reply_parameters,
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
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
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

             await bot.send_audio(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_audio`.

        Note:
            |user_chat_id_note|

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

             await bot.send_chat_action(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_chat_action`.

        Note:
            |user_chat_id_note|

        Returns:
            :obj:`True`: On success.

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

             await bot.send_contact(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_contact`.

        Note:
            |user_chat_id_note|

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

             await bot.send_dice(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_dice`.

        Note:
            |user_chat_id_note|

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

             await bot.send_document(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_document`.

        Note:
            |user_chat_id_note|

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

             await bot.send_game(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_game`.

        Note:
            |user_chat_id_note|

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

             await bot.send_invoice(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_invoice`.

        Warning:
            As of API 5.2 :paramref:`start_parameter <telegram.Bot.send_invoice.start_parameter>`
            is an optional argument and therefore the
            order of the arguments had to be changed. Use keyword arguments to make sure that the
            arguments are passed correctly.

        Note:
            |user_chat_id_note|

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
            reply_parameters=reply_parameters,
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

             await bot.send_location(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_location`.

        Note:
            |user_chat_id_note|

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

             await bot.send_animation(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_animation`.

        Note:
            |user_chat_id_note|

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

             await bot.send_sticker(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_sticker`.

        Note:
            |user_chat_id_note|

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

             await bot.send_video(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_video`.

        Note:
            |user_chat_id_note|

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

             await bot.send_venue(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_venue`.

        Note:
            |user_chat_id_note|

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

             await bot.send_video_note(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_video_note`.

        Note:
            |user_chat_id_note|

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
            api_kwargs=api_kwargs,
            allow_sending_without_reply=allow_sending_without_reply,
            filename=filename,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            thumbnail=thumbnail,
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

             await bot.send_voice(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_voice`.

        Note:
            |user_chat_id_note|

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

             await bot.send_poll(update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_poll`.

        Note:
            |user_chat_id_note|

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
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
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

             await bot.send_gift(user_id=update.effective_user.id, *args, **kwargs )

        For the documentation of the arguments, please see :meth:`telegram.Bot.send_gift`.

        .. versionadded:: 21.8

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().send_gift(
            chat_id=None,
            user_id=self.id,
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
        )

    async def gift_premium_subscription(
        self,
        month_count: int,
        star_count: int,
        text: str | None = None,
        text_parse_mode: ODVInput[str] = DEFAULT_NONE,
        text_entities: Sequence["MessageEntity"] | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.gift_premium_subscription(user_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.gift_premium_subscription`.

        .. versionadded:: 22.1

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().gift_premium_subscription(
            user_id=self.id,
            month_count=month_count,
            star_count=star_count,
            text=text,
            text_parse_mode=text_parse_mode,
            text_entities=text_entities,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
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

             await bot.copy_message(chat_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.copy_message`.

        Note:
            |user_chat_id_note|

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

             await bot.copy_message(from_chat_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Bot.copy_message`.

        Note:
            |user_chat_id_note|

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

             await bot.copy_messages(chat_id=update.effective_user.id, *argss, **kwargs)

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

             await bot.copy_messages(from_chat_id=update.effective_user.id, *argss, **kwargs)

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

             await bot.forward_message(chat_id=update.effective_user.id, *argss, **kwargs)

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

             await bot.forward_message(from_chat_id=update.effective_user.id, *argss, **kwargs)

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

             await bot.forward_messages(chat_id=update.effective_user.id, *argss, **kwargs)

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

             await bot.forward_messages(from_chat_id=update.effective_user.id, *argss, **kwargs)

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

    async def approve_join_request(
        self,
        chat_id: int | str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.approve_chat_join_request(user_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.approve_chat_join_request`.

        Note:
            |user_chat_id_note|

        .. versionadded:: 13.8

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().approve_chat_join_request(
            user_id=self.id,
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def decline_join_request(
        self,
        chat_id: int | str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.decline_chat_join_request(user_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.decline_chat_join_request`.

        Note:
            |user_chat_id_note|

        .. versionadded:: 13.8

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().decline_chat_join_request(
            user_id=self.id,
            chat_id=chat_id,
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

             await bot.set_chat_menu_button(chat_id=update.effective_user.id, *argss, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.set_chat_menu_button`.

        .. seealso:: :meth:`get_menu_button`

        Note:
            |user_chat_id_note|

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

             await bot.get_chat_menu_button(chat_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_chat_menu_button`.

        .. seealso:: :meth:`set_menu_button`

        Note:
            |user_chat_id_note|

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

    async def get_chat_boosts(
        self,
        chat_id: int | str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "UserChatBoosts":
        """Shortcut for::

             await bot.get_user_chat_boosts(user_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_user_chat_boosts`.

        .. versionadded:: 20.8

        Returns:
            :class:`telegram.UserChatBoosts`: On success, returns the boosts applied by the user.
        """
        return await self.get_bot().get_user_chat_boosts(
            chat_id=chat_id,
            user_id=self.id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def refund_star_payment(
        self,
        telegram_payment_charge_id: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.refund_star_payment(user_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.refund_star_payment`.

        .. versionadded:: 21.3

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().refund_star_payment(
            user_id=self.id,
            telegram_payment_charge_id=telegram_payment_charge_id,
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

             await bot.verify_user(user_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.verify_user`.

        .. versionadded:: 21.10

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().verify_user(
            user_id=self.id,
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

             await bot.remove_user_verification(user_id=update.effective_user.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.remove_user_verification`.

        .. versionadded:: 21.10

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        return await self.get_bot().remove_user_verification(
            user_id=self.id,
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
                from_chat_id=update.effective_user.id,
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

             await bot.get_user_gifts(user_id=update.effective_user.id)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_user_gifts`.

        .. versionadded:: 22.6

        Returns:
            :class:`telegram.OwnedGifts`: On success, returns the gifts owned by the user.
        """
        return await self.get_bot().get_user_gifts(
            user_id=self.id,
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
