#!/usr/bin/env python
#
#  A library that provides a Python interface to the Telegram Bot API
#  Copyright (C) 2015-2026
#  Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser Public License for more details.
#
#  You should have received a copy of the GNU Lesser Public License
#  along with this program.  If not, see [http://www.gnu.org/licenses/].
"""This module contains a class that allows to rate limit requests to the Bot API."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any, Generic

from telegram._utils.types import JSONDict
from telegram.ext._utils.types import RLARGS


class BaseRateLimiter(ABC, Generic[RLARGS]):
    """
    Abstract interface class that allows to rate limit the requests that python-telegram-bot
    sends to the Telegram Bot API. An implementation of this class
    must implement all abstract methods and properties.

    This class is a :class:`~typing.Generic` class and accepts one type variable that specifies
    the type of the argument :paramref:`~process_request.rate_limit_args` of
    :meth:`process_request` and the methods of :class:`~telegram.ext.ExtBot`.

    Hint:
        Requests to :meth:`~telegram.Bot.get_updates` are never rate limited.

    .. seealso:: :wiki:`Architecture Overview <Architecture>`,
        :wiki:`Avoiding Flood Limits <Avoiding-flood-limits>`

    .. versionadded:: 20.0
    """

    __slots__ = ()

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize resources used by this class. Must be implemented by a subclass."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Stop & clear resources used by this class. Must be implemented by a subclass."""

    @abstractmethod
    async def process_request(
        self,
        callback: Callable[..., Coroutine[Any, Any, bool | JSONDict | list[JSONDict]]],
        args: Any,
        kwargs: dict[str, Any],
        endpoint: str,
        data: dict[str, Any],
        rate_limit_args: RLARGS | None,
    ) -> bool | JSONDict | list[JSONDict]:
        """
        Process a request. Must be implemented by a subclass.

        This method must call :paramref:`callback` and return the result of the call.
        `When` the callback is called is up to the implementation.

        Important:
            This method must only return once the result of :paramref:`callback` is known!

        If a :exc:`~telegram.error.RetryAfter` error is raised, this method may try to make
        a new request by calling the callback again.

        Warning:
            This method *should not* handle any other exception raised by :paramref:`callback`!

        There are basically two different approaches how a rate limiter can be implemented:

        1. React only if necessary. In this case, the :paramref:`callback` is called without any
           precautions. If a :exc:`~telegram.error.RetryAfter` error is raised, processing requests
           is halted for the :attr:`~telegram.error.RetryAfter.retry_after` and finally the
           :paramref:`callback` is called again. This approach is often amendable for bots that
           don't have a large user base and/or don't send more messages than they get updates.
        2. Throttle all outgoing requests. In this case the implementation makes sure that the
           requests are spread out over a longer time interval in order to stay below the rate
           limits. This approach is often amendable for bots that have a large user base and/or
           send more messages than they get updates.

        An implementation can use the information provided by :paramref:`data`,
        :paramref:`endpoint` and :paramref:`rate_limit_args` to handle each request differently.

        Examples:
            * It is usually desirable to call :meth:`telegram.Bot.answer_inline_query`
              as quickly as possible, while delaying :meth:`telegram.Bot.send_message`
              is acceptable.
            * There are `different <https://core.telegram.org/bots/faq\
              #my-bot-is-hitting-limits-how-do-i-avoid-this>`_ rate limits for group chats and
              private chats.
            * When sending broadcast messages to a large number of users, these requests can
              typically be delayed for a longer time than messages that are direct replies to a
              user input.

        Args:
            callback (Callable[..., :term:`coroutine`]): The coroutine function that must be called
                to make the request.
            args (tuple[:obj:`object`]): The positional arguments for the :paramref:`callback`
                function.
            kwargs (dict[:obj:`str`, :obj:`object`]): The keyword arguments for the
                :paramref:`callback` function.
            endpoint (:obj:`str`): The endpoint that the request is made for, e.g.
                ``"sendMessage"``.
            data (dict[:obj:`str`, :obj:`object`]): The parameters that were passed to the method
                of :class:`~telegram.ext.ExtBot`. Any ``api_kwargs`` are included in this and
                any :paramref:`~telegram.ext.ExtBot.defaults` are already applied.

                Example:

                    When calling::

                        await ext_bot.send_message(
                            chat_id=1,
                            text="Hello world!",
                            api_kwargs={"custom": "arg"}
                        )

                    then :paramref:`data` will be::

                        {"chat_id": 1, "text": "Hello world!", "custom": "arg"}

            rate_limit_args (:obj:`None` | :class:`object`): Custom arguments passed to the methods
                of :class:`~telegram.ext.ExtBot`. Can e.g. be used to specify the priority of
                the request.

        Returns:
            :obj:`bool` | dict[:obj:`str`, :obj:`object`] | :obj:`None`: The result of the
            callback function.
        """
