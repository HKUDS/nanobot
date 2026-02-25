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
"""This module contains the CallbackQueryHandler class."""

import asyncio
import re
from collections.abc import Callable
from re import Match, Pattern
from typing import TYPE_CHECKING, Any, TypeVar, cast

from telegram import Update
from telegram._utils.defaultvalue import DEFAULT_TRUE
from telegram._utils.types import DVType
from telegram.ext._handlers.basehandler import BaseHandler
from telegram.ext._utils.types import CCT, HandlerCallback

if TYPE_CHECKING:
    from telegram.ext import Application

RT = TypeVar("RT")


class CallbackQueryHandler(BaseHandler[Update, CCT, RT]):
    """Handler class to handle Telegram
    :attr:`callback queries <telegram.Update.callback_query>`. Optionally based on a regex.

    Read the documentation of the :mod:`re` module for more information.

    Note:
        * If your bot allows arbitrary objects as
          :paramref:`~telegram.InlineKeyboardButton.callback_data`, it may happen that the
          original :attr:`~telegram.InlineKeyboardButton.callback_data` for the incoming
          :class:`telegram.CallbackQuery` can not be found. This is the case when either a
          malicious client tempered with the :attr:`telegram.CallbackQuery.data` or the data was
          simply dropped from cache or not persisted. In these
          cases, an instance of :class:`telegram.ext.InvalidCallbackData` will be set as
          :attr:`telegram.CallbackQuery.data`.

          .. versionadded:: 13.6

        * If neither :paramref:`pattern` nor :paramref:`game_pattern` is set, `any`
          ``CallbackQuery`` will be handled. If only :paramref:`pattern` is set, queries with
          :attr:`~telegram.CallbackQuery.game_short_name` will `not` be considered and vice versa.
          If both patterns are set, queries with either :attr:
          `~telegram.CallbackQuery.game_short_name` or :attr:`~telegram.CallbackQuery.data`
          matching the defined pattern will be handled

          .. versionadded:: 21.5

    Warning:
        When setting :paramref:`block` to :obj:`False`, you cannot rely on adding custom
        attributes to :class:`telegram.ext.CallbackContext`. See its docs for more info.

    Args:
        callback (:term:`coroutine function`): The callback function for this handler. Will be
            called when :meth:`check_update` has determined that an update should be processed by
            this handler. Callback signature::

                async def callback(update: Update, context: CallbackContext)

            The return value of the callback is usually ignored except for the special case of
            :class:`telegram.ext.ConversationHandler`.
        pattern (:obj:`str` | :func:`re.Pattern <re.compile>` | :obj:`callable` | :obj:`type`, \
            optional):
            Pattern to test :attr:`telegram.CallbackQuery.data` against. If a string or a regex
            pattern is passed, :func:`re.match` is used on :attr:`telegram.CallbackQuery.data` to
            determine if an update should be handled by this handler. If your bot allows arbitrary
            objects as :paramref:`~telegram.InlineKeyboardButton.callback_data`, non-strings will
            be accepted. To filter arbitrary objects you may pass:

            - a callable, accepting exactly one argument, namely the
              :attr:`telegram.CallbackQuery.data`. It must return :obj:`True` or
              :obj:`False`/:obj:`None` to indicate, whether the update should be handled.
            - a :obj:`type`. If :attr:`telegram.CallbackQuery.data` is an instance of that type
              (or a subclass), the update will be handled.

            If :attr:`telegram.CallbackQuery.data` is :obj:`None`, the
            :class:`telegram.CallbackQuery` update will not be handled.

            .. seealso:: :wiki:`Arbitrary callback_data <Arbitrary-callback_data>`

            .. versionchanged:: 13.6
               Added support for arbitrary callback data.
        game_pattern (:obj:`str` | :func:`re.Pattern <re.compile>` | optional)
            Pattern to test :attr:`telegram.CallbackQuery.game_short_name` against. If a string or
            a regex pattern is passed, :func:`re.match` is used on
            :attr:`telegram.CallbackQuery.game_short_name` to determine if an update should be
            handled by this handler.

            .. versionadded:: 21.5
        block (:obj:`bool`, optional): Determines whether the return value of the callback should
            be awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`. Defaults to :obj:`True`.

            .. seealso:: :wiki:`Concurrency`

    Attributes:
        callback (:term:`coroutine function`): The callback function for this handler.
        pattern (:func:`re.Pattern <re.compile>` | :obj:`callable` | :obj:`type`): Optional.
            Regex pattern, callback or type to test :attr:`telegram.CallbackQuery.data` against.

            .. versionchanged:: 13.6
               Added support for arbitrary callback data.
        game_pattern (:func:`re.Pattern <re.compile>`): Optional.
            Regex pattern to test :attr:`telegram.CallbackQuery.game_short_name`
        block (:obj:`bool`): Determines whether the return value of the callback should be
            awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`.

    """

    __slots__ = ("game_pattern", "pattern")

    def __init__(
        self: "CallbackQueryHandler[CCT, RT]",
        callback: HandlerCallback[Update, CCT, RT],
        pattern: str | Pattern[str] | type | Callable[[object], bool] | None = None,
        game_pattern: str | Pattern[str] | None = None,
        block: DVType[bool] = DEFAULT_TRUE,
    ):
        super().__init__(callback, block=block)

        if callable(pattern) and asyncio.iscoroutinefunction(pattern):
            raise TypeError(
                "The `pattern` must not be a coroutine function! Use an ordinary function instead."
            )
        if isinstance(pattern, str):
            pattern = re.compile(pattern)

        if isinstance(game_pattern, str):
            game_pattern = re.compile(game_pattern)
        self.pattern: str | Pattern[str] | type | Callable[[object], bool] | None = pattern
        self.game_pattern: str | Pattern[str] | None = game_pattern

    def check_update(self, update: object) -> bool | object | None:
        """Determines whether an update should be passed to this handler's :attr:`callback`.

        Args:
            update (:class:`telegram.Update` | :obj:`object`): Incoming update.

        Returns:
            :obj:`bool`

        """
        # pylint: disable=too-many-return-statements
        if not (isinstance(update, Update) and update.callback_query):
            return None

        callback_data = update.callback_query.data
        game_short_name = update.callback_query.game_short_name

        if not any([self.pattern, self.game_pattern]):
            return True

        # we check for .data or .game_short_name from update to filter based on whats coming
        # this gives xor-like behavior
        if callback_data:
            if not self.pattern:
                return False
            if isinstance(self.pattern, type):
                return isinstance(callback_data, self.pattern)
            if callable(self.pattern):
                return self.pattern(callback_data)
            if not isinstance(callback_data, str):
                return False
            if match := re.match(self.pattern, callback_data):
                return match

        elif game_short_name:
            if not self.game_pattern:
                return False
            if match := re.match(self.game_pattern, game_short_name):
                return match
        else:
            return True
        return False

    def collect_additional_context(
        self,
        context: CCT,
        update: Update,  # noqa: ARG002
        application: "Application[Any, CCT, Any, Any, Any, Any]",  # noqa: ARG002
        check_result: bool | Match[str],
    ) -> None:
        """Add the result of ``re.match(pattern, update.callback_query.data)`` to
        :attr:`CallbackContext.matches` as list with one element.
        """
        if self.pattern:
            check_result = cast("Match", check_result)
            context.matches = [check_result]
