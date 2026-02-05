#!/usr/bin/env python
# pylint: disable=too-many-arguments
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
"""This module contains an object that represents a Telegram InlineQuery."""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._files.location import Location
from telegram._inline.inlinequeryresultsbutton import InlineQueryResultsButton
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import JSONDict, ODVInput, TimePeriod

if TYPE_CHECKING:
    from telegram import Bot, InlineQueryResult


class InlineQuery(TelegramObject):
    """
    This object represents an incoming inline query. When the user sends an empty query, your bot
    could return some default or trending results.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`id` is equal.

    .. figure:: https://core.telegram.org/file/464001466/10e4a/r4FKyQ7gw5g.134366/f2\
        606a53d683374703
        :align: center

        Inline queries on Telegram

    .. seealso::
        The :class:`telegram.InlineQueryResult` classes represent the media the user can choose
        from (see above figure).

    Note:
        In Python :keyword:`from` is a reserved word. Use :paramref:`from_user` instead.

    .. versionchanged:: 20.0
        The following are now keyword-only arguments in Bot methods:
        ``{read, write, connect, pool}_timeout``, :paramref:`answer.api_kwargs`,
        ``auto_pagination``. Use a named argument for those,
        and notice that some positional arguments changed position as a result.

    .. versionchanged:: 22.0
        Removed constants ``MIN_START_PARAMETER_LENGTH`` and ``MAX_START_PARAMETER_LENGTH``.
        Use :attr:`telegram.constants.InlineQueryResultsButtonLimit.MIN_START_PARAMETER_LENGTH` and
        :attr:`telegram.constants.InlineQueryResultsButtonLimit.MAX_START_PARAMETER_LENGTH`
        instead.

    Args:
        id (:obj:`str`): Unique identifier for this query.
        from_user (:class:`telegram.User`): Sender.
        query (:obj:`str`): Text of the query (up to
            :tg-const:`telegram.InlineQuery.MAX_QUERY_LENGTH` characters).
        offset (:obj:`str`): Offset of the results to be returned, can be controlled by the bot.
        chat_type (:obj:`str`, optional): Type of the chat, from which the inline query was sent.
            Can be either :tg-const:`telegram.Chat.SENDER` for a private chat with the inline query
            sender, :tg-const:`telegram.Chat.PRIVATE`, :tg-const:`telegram.Chat.GROUP`,
            :tg-const:`telegram.Chat.SUPERGROUP` or :tg-const:`telegram.Chat.CHANNEL`. The chat
            type should be always known for requests sent from official clients and most
            third-party clients, unless the request was sent from a secret chat.

            .. versionadded:: 13.5
        location (:class:`telegram.Location`, optional): Sender location, only for bots that
            request user location.

    Attributes:
        id (:obj:`str`): Unique identifier for this query.
        from_user (:class:`telegram.User`): Sender.
        query (:obj:`str`): Text of the query (up to
            :tg-const:`telegram.InlineQuery.MAX_QUERY_LENGTH` characters).
        offset (:obj:`str`): Offset of the results to be returned, can be controlled by the bot.
        chat_type (:obj:`str`): Optional. Type of the chat, from which the inline query was sent.
            Can be either :tg-const:`telegram.Chat.SENDER` for a private chat with the inline query
            sender, :tg-const:`telegram.Chat.PRIVATE`, :tg-const:`telegram.Chat.GROUP`,
            :tg-const:`telegram.Chat.SUPERGROUP` or :tg-const:`telegram.Chat.CHANNEL`. The chat
            type should be always known for requests sent from official clients and most
            third-party clients, unless the request was sent from a secret chat.

            .. versionadded:: 13.5
        location (:class:`telegram.Location`): Optional. Sender location, only for bots that
            request user location.

    """

    __slots__ = ("chat_type", "from_user", "id", "location", "offset", "query")

    def __init__(
        self,
        id: str,  # pylint: disable=redefined-builtin
        from_user: User,
        query: str,
        offset: str,
        location: "Location | None" = None,
        chat_type: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.id: str = id
        self.from_user: User = from_user
        self.query: str = query
        self.offset: str = offset

        # Optional
        self.location: Location | None = location
        self.chat_type: str | None = chat_type

        self._id_attrs = (self.id,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "InlineQuery":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["from_user"] = de_json_optional(data.pop("from", None), User, bot)
        data["location"] = de_json_optional(data.get("location"), Location, bot)

        return super().de_json(data=data, bot=bot)

    async def answer(
        self,
        results: (
            Sequence["InlineQueryResult"] | Callable[[int], Sequence["InlineQueryResult"] | None]
        ),
        cache_time: TimePeriod | None = None,
        is_personal: bool | None = None,
        next_offset: str | None = None,
        button: InlineQueryResultsButton | None = None,
        *,
        current_offset: str | None = None,
        auto_pagination: bool = False,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Shortcut for::

            await bot.answer_inline_query(
                update.inline_query.id,
                *args,
                current_offset=self.offset if auto_pagination else None,
                **kwargs
            )

        For the documentation of the arguments, please see
        :meth:`telegram.Bot.answer_inline_query`.

        .. versionchanged:: 20.0
            Raises :class:`ValueError` instead of :class:`TypeError`.

        Keyword Args:
            auto_pagination (:obj:`bool`, optional): If set to :obj:`True`, :attr:`offset` will be
                passed as
                :paramref:`current_offset <telegram.Bot.answer_inline_query.current_offset>` to
                :meth:`telegram.Bot.answer_inline_query`.
                Defaults to :obj:`False`.

        Raises:
            ValueError: If both :paramref:`~telegram.Bot.answer_inline_query.current_offset` and
                :paramref:`auto_pagination` are supplied.
        """
        if current_offset and auto_pagination:
            raise ValueError("current_offset and auto_pagination are mutually exclusive!")
        return await self.get_bot().answer_inline_query(
            inline_query_id=self.id,
            current_offset=self.offset if auto_pagination else current_offset,
            results=results,
            cache_time=cache_time,
            is_personal=is_personal,
            next_offset=next_offset,
            button=button,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    MAX_RESULTS: Final[int] = constants.InlineQueryLimit.RESULTS
    """:const:`telegram.constants.InlineQueryLimit.RESULTS`

    .. versionadded:: 13.2
    """
    MAX_OFFSET_LENGTH: Final[int] = constants.InlineQueryLimit.MAX_OFFSET_LENGTH
    """:const:`telegram.constants.InlineQueryLimit.MAX_OFFSET_LENGTH`

    .. versionadded:: 20.0
    """
    MAX_QUERY_LENGTH: Final[int] = constants.InlineQueryLimit.MAX_QUERY_LENGTH
    """:const:`telegram.constants.InlineQueryLimit.MAX_QUERY_LENGTH`

    .. versionadded:: 20.0
    """
