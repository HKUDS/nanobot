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
# pylint: disable=redefined-builtin
"""This module contains an object that represents a Telegram CallbackQuery"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._inputchecklist import InputChecklist
from telegram._message import MaybeInaccessibleMessage, Message
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import JSONDict, ODVInput, TimePeriod

if TYPE_CHECKING:
    from telegram import (
        Bot,
        GameHighScore,
        InlineKeyboardMarkup,
        InputMedia,
        LinkPreviewOptions,
        MessageEntity,
        MessageId,
        ReplyParameters,
        SuggestedPostParameters,
    )
    from telegram._files.location import Location
    from telegram._utils.types import ReplyMarkup


class CallbackQuery(TelegramObject):
    """
    This object represents an incoming callback query from a callback button in an inline keyboard.

    If the button that originated the query was attached to a message sent by the bot, the field
    :attr:`message` will be present. If the button was attached to a message sent via the bot (in
    inline mode), the field :attr:`inline_message_id` will be present.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`id` is equal.

    Note:
        * In Python :keyword:`from` is a reserved word. Use :paramref:`from_user` instead.
        * Exactly one of the fields :attr:`data` or :attr:`game_short_name` will be present.
        * After the user presses an inline button, Telegram clients will display a progress bar
          until you call :attr:`answer`. It is, therefore, necessary to react
          by calling :attr:`telegram.Bot.answer_callback_query` even if no notification to the user
          is needed (e.g., without specifying any of the optional parameters).
        * If you're using :attr:`telegram.ext.ExtBot.callback_data_cache`, :attr:`data` may be
          an instance
          of :class:`telegram.ext.InvalidCallbackData`. This will be the case, if the data
          associated with the button triggering the :class:`telegram.CallbackQuery` was already
          deleted or if :attr:`data` was manipulated by a malicious client.

          .. versionadded:: 13.6

    Args:
        id (:obj:`str`): Unique identifier for this query.
        from_user (:class:`telegram.User`): Sender.
        chat_instance (:obj:`str`): Global identifier, uniquely corresponding to the chat to which
            the message with the callback button was sent. Useful for high scores in games.
        message (:class:`telegram.MaybeInaccessibleMessage`, optional): Message sent by the bot
            with the callback button that originated the query.

            .. versionchanged:: 20.8
               Accept objects of type :class:`telegram.MaybeInaccessibleMessage` since Bot API 7.0.
        data (:obj:`str`, optional): Data associated with the callback button. Be aware that the
            message, which originated the query, can contain no callback buttons with this data.
        inline_message_id (:obj:`str`, optional): Identifier of the message sent via the bot in
            inline mode, that originated the query.
        game_short_name (:obj:`str`, optional): Short name of a Game to be returned, serves as
            the unique identifier for the game.

    Attributes:
        id (:obj:`str`): Unique identifier for this query.
        from_user (:class:`telegram.User`): Sender.
        chat_instance (:obj:`str`): Global identifier, uniquely corresponding to the chat to which
            the message with the callback button was sent. Useful for high scores in games.
        message (:class:`telegram.MaybeInaccessibleMessage`): Optional. Message sent by the bot
            with the callback button that originated the query.

            .. versionchanged:: 20.8
               Objects may be of type :class:`telegram.MaybeInaccessibleMessage` since Bot API
               7.0.
        data (:obj:`str` | :obj:`object`): Optional. Data associated with the callback button.
            Be aware that the message, which originated the query, can contain no callback buttons
            with this data.

            Tip:
                The value here is the same as the value passed in
                :paramref:`telegram.InlineKeyboardButton.callback_data`.
        inline_message_id (:obj:`str`): Optional. Identifier of the message sent via the bot in
            inline mode, that originated the query.
        game_short_name (:obj:`str`): Optional. Short name of a Game to be returned, serves as
            the unique identifier for the game.


    """

    __slots__ = (
        "chat_instance",
        "data",
        "from_user",
        "game_short_name",
        "id",
        "inline_message_id",
        "message",
    )

    def __init__(
        self,
        id: str,
        from_user: User,
        chat_instance: str,
        message: MaybeInaccessibleMessage | None = None,
        data: str | None = None,
        inline_message_id: str | None = None,
        game_short_name: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.id: str = id
        self.from_user: User = from_user
        self.chat_instance: str = chat_instance
        # Optionals
        self.message: MaybeInaccessibleMessage | None = message
        self.data: str | None = data
        self.inline_message_id: str | None = inline_message_id
        self.game_short_name: str | None = game_short_name

        self._id_attrs = (self.id,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "CallbackQuery":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["from_user"] = de_json_optional(data.pop("from", None), User, bot)
        data["message"] = de_json_optional(data.get("message"), Message, bot)

        return super().de_json(data=data, bot=bot)

    async def answer(
        self,
        text: str | None = None,
        show_alert: bool | None = None,
        url: str | None = None,
        cache_time: TimePeriod | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

             await bot.answer_callback_query(update.callback_query.id, *args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.answer_callback_query`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        return await self.get_bot().answer_callback_query(
            callback_query_id=self.id,
            text=text,
            show_alert=show_alert,
            url=url,
            cache_time=cache_time,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    def _get_message(self, action: str = "edit") -> Message:
        """Helper method to get the message for the shortcut methods. Must be called only
        if :attr:`inline_message_id` is *not* set.
        """
        if not isinstance(self.message, Message):
            raise TypeError(f"Cannot {action} an inaccessible message")
        return self.message

    async def edit_message_text(
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
        """Shortcut for either::

            await update.callback_query.message.edit_text(*args, **kwargs)

        or::

            await bot.edit_message_text(
                inline_message_id=update.callback_query.inline_message_id, *args, **kwargs,
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_message_text` and :meth:`telegram.Message.edit_text`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise :obj:`True` is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.

        """
        if self.inline_message_id:
            return await self.get_bot().edit_message_text(
                inline_message_id=self.inline_message_id,
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
                chat_id=None,
                message_id=None,
                # inline messages can not be sent on behalf of a bcid
                business_connection_id=None,
            )
        return await self._get_message().edit_text(
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
        )

    async def edit_message_caption(
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
        """Shortcut for either::

            await update.callback_query.message.edit_caption(*args, **kwargs)

        or::

            await bot.edit_message_caption(
                inline_message_id=update.callback_query.inline_message_id, *args, **kwargs,
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_message_caption` and :meth:`telegram.Message.edit_caption`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise :obj:`True` is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.

        """
        if self.inline_message_id:
            return await self.get_bot().edit_message_caption(
                caption=caption,
                inline_message_id=self.inline_message_id,
                reply_markup=reply_markup,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                parse_mode=parse_mode,
                api_kwargs=api_kwargs,
                caption_entities=caption_entities,
                chat_id=None,
                message_id=None,
                show_caption_above_media=show_caption_above_media,
                # inline messages can not be sent on behalf of a bcid
                business_connection_id=None,
            )
        return await self._get_message().edit_caption(
            caption=caption,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            parse_mode=parse_mode,
            api_kwargs=api_kwargs,
            caption_entities=caption_entities,
            show_caption_above_media=show_caption_above_media,
        )

    async def edit_message_checklist(
        self,
        checklist: InputChecklist,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Shortcut for::

            await update.callback_query.message.edit_checklist(*args, **kwargs)

        For the documentation of the arguments, please see
        :meth:`telegram.Message.edit_checklist`.

        .. versionadded:: 22.3

        Returns:
            :class:`telegram.Message`: On success, the edited Message is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.

        """
        return await self._get_message().edit_checklist(
            checklist=checklist,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_message_reply_markup(
        self,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Shortcut for either::

            await update.callback_query.message.edit_reply_markup(*args, **kwargs)

        or::

            await bot.edit_message_reply_markup(
                inline_message_id=update.callback_query.inline_message_id, *args, **kwargs
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_message_reply_markup` and
        :meth:`telegram.Message.edit_reply_markup`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise :obj:`True` is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.

        """
        if self.inline_message_id:
            return await self.get_bot().edit_message_reply_markup(
                reply_markup=reply_markup,
                inline_message_id=self.inline_message_id,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
                chat_id=None,
                message_id=None,
                # inline messages can not be sent on behalf of a bcid
                business_connection_id=None,
            )
        return await self._get_message().edit_reply_markup(
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_message_media(
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
        """Shortcut for either::

            await update.callback_query.message.edit_media(*args, **kwargs)

        or::

            await bot.edit_message_media(
                inline_message_id=update.callback_query.inline_message_id, *args, **kwargs
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_message_media` and :meth:`telegram.Message.edit_media`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :class:`telegram.Message`: On success, if edited message is not an inline message, the
            edited Message is returned, otherwise :obj:`True` is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.

        """
        if self.inline_message_id:
            return await self.get_bot().edit_message_media(
                inline_message_id=self.inline_message_id,
                media=media,
                reply_markup=reply_markup,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
                chat_id=None,
                message_id=None,
                # inline messages can not be sent on behalf of a bcid
                business_connection_id=None,
            )
        return await self._get_message().edit_media(
            media=media,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_message_live_location(
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
        """Shortcut for either::

            await update.callback_query.message.edit_live_location(*args, **kwargs)

        or::

            await bot.edit_message_live_location(
                inline_message_id=update.callback_query.inline_message_id, *args, **kwargs
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.edit_message_live_location` and
        :meth:`telegram.Message.edit_live_location`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise :obj:`True` is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.

        """
        if self.inline_message_id:
            return await self.get_bot().edit_message_live_location(
                inline_message_id=self.inline_message_id,
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
                chat_id=None,
                message_id=None,
                # inline messages can not be sent on behalf of a bcid
                business_connection_id=None,
            )
        return await self._get_message().edit_live_location(
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
        )

    async def stop_message_live_location(
        self,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Shortcut for either::

            await update.callback_query.message.stop_live_location(*args, **kwargs)

        or::

            await bot.stop_message_live_location(
                inline_message_id=update.callback_query.inline_message_id, *args, **kwargs
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.stop_message_live_location` and
        :meth:`telegram.Message.stop_live_location`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise :obj:`True` is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.

        """
        if self.inline_message_id:
            return await self.get_bot().stop_message_live_location(
                inline_message_id=self.inline_message_id,
                reply_markup=reply_markup,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
                chat_id=None,
                message_id=None,
                # inline messages can not be sent on behalf of a bcid
                business_connection_id=None,
            )
        return await self._get_message().stop_live_location(
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
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
        """Shortcut for either::

           await update.callback_query.message.set_game_score(*args, **kwargs)

        or::

            await bot.set_game_score(
                inline_message_id=update.callback_query.inline_message_id, *args, **kwargs
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.set_game_score` and :meth:`telegram.Message.set_game_score`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :class:`telegram.Message`: On success, if edited message is sent by the bot, the
            edited Message is returned, otherwise :obj:`True` is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.

        """
        if self.inline_message_id:
            return await self.get_bot().set_game_score(
                inline_message_id=self.inline_message_id,
                user_id=user_id,
                score=score,
                force=force,
                disable_edit_message=disable_edit_message,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
                chat_id=None,
                message_id=None,
            )
        return await self._get_message().set_game_score(
            user_id=user_id,
            score=score,
            force=force,
            disable_edit_message=disable_edit_message,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
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
        """Shortcut for either::

            await update.callback_query.message.get_game_high_score(*args, **kwargs)

        or::

            await bot.get_game_high_scores(
                inline_message_id=update.callback_query.inline_message_id, *args, **kwargs
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.get_game_high_scores` and
        :meth:`telegram.Message.get_game_high_scores`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            tuple[:class:`telegram.GameHighScore`]

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.

        """
        if self.inline_message_id:
            return await self.get_bot().get_game_high_scores(
                inline_message_id=self.inline_message_id,
                user_id=user_id,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
                chat_id=None,
                message_id=None,
            )
        return await self._get_message().get_game_high_scores(
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_message(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

            await update.callback_query.message.delete(*args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Message.delete`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.

        """
        return await self._get_message(action="delete").delete(
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def pin_message(
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

            await update.callback_query.message.pin(*args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Message.pin`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.
        """
        return await self._get_message(action="pin").pin(
            disable_notification=disable_notification,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unpin_message(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

            await update.callback_query.message.unpin(*args, **kwargs)

        For the documentation of the arguments, please see :meth:`telegram.Message.unpin`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.
        """
        return await self._get_message(action="unpin").unpin(
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def copy_message(
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
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "MessageId":
        """Shortcut for::

            await update.callback_query.message.copy(
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id,
                direct_messages_topic_id=update.message.direct_messages_topic.topic_id,
                *args,
                **kwargs
            )

        For the documentation of the arguments, please see :meth:`telegram.Message.copy`.

        .. versionchanged:: 20.8
           Raises :exc:`TypeError` if :attr:`message` is not accessible.

        Returns:
            :class:`telegram.MessageId`: On success, returns the MessageId of the sent message.

        Raises:
            :exc:`TypeError` if :attr:`message` is not accessible.
        """
        return await self._get_message(action="copy").copy(
            chat_id=chat_id,
            caption=caption,
            parse_mode=parse_mode,
            video_start_timestamp=video_start_timestamp,
            caption_entities=caption_entities,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=allow_sending_without_reply,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            show_caption_above_media=show_caption_above_media,
            allow_paid_broadcast=allow_paid_broadcast,
            suggested_post_parameters=suggested_post_parameters,
            message_effect_id=message_effect_id,
        )

    MAX_ANSWER_TEXT_LENGTH: Final[int] = (
        constants.CallbackQueryLimit.ANSWER_CALLBACK_QUERY_TEXT_LENGTH
    )
    """
    :const:`telegram.constants.CallbackQueryLimit.ANSWER_CALLBACK_QUERY_TEXT_LENGTH`

    .. versionadded:: 13.2
    """
