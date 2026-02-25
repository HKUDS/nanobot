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
"""This module contains the BaseProcessor class."""

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeVar, final

from telegram.ext._utils.asyncio import TrackedBoundedSemaphore

if TYPE_CHECKING:
    from collections.abc import Awaitable

_BUPT = TypeVar("_BUPT", bound="BaseUpdateProcessor")


class BaseUpdateProcessor(AbstractAsyncContextManager["BaseUpdateProcessor"], ABC):
    """An abstract base class for update processors. You can use this class to implement
    your own update processor.

    Instances of this class can be used as asyncio context managers, where

    .. code:: python

        async with processor:
            # code

    is roughly equivalent to

    .. code:: python

        try:
            await processor.initialize()
            # code
        finally:
            await processor.shutdown()

    .. seealso:: :meth:`__aenter__` and :meth:`__aexit__`.

    .. seealso:: :wiki:`Concurrency`

    .. versionadded:: 20.4

    Args:
        max_concurrent_updates (:obj:`int`): The maximum number of updates to be processed
            concurrently. If this number is exceeded, new updates will be queued until the number
            of currently processed updates decreases.

    Raises:
        :exc:`ValueError`: If :paramref:`max_concurrent_updates` is a non-positive integer.
    """

    __slots__ = ("_max_concurrent_updates", "_semaphore")

    def __init__(self, max_concurrent_updates: int):
        self._max_concurrent_updates = max_concurrent_updates
        if self.max_concurrent_updates < 1:
            raise ValueError("`max_concurrent_updates` must be a positive integer!")
        self._semaphore = TrackedBoundedSemaphore(self.max_concurrent_updates)

    async def __aenter__(self: _BUPT) -> _BUPT:
        """|async_context_manager| :meth:`initializes <initialize>` the Processor.

        Returns:
            The initialized Processor instance.

        Raises:
            :exc:`Exception`: If an exception is raised during initialization, :meth:`shutdown`
                is called in this case.
        """
        try:
            await self.initialize()
        except Exception:
            await self.shutdown()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """|async_context_manager| :meth:`shuts down <shutdown>` the Processor."""
        await self.shutdown()

    @property
    def max_concurrent_updates(self) -> int:
        """:obj:`int`: The maximum number of updates that can be processed concurrently."""
        return self._max_concurrent_updates

    @property
    def current_concurrent_updates(self) -> int:
        """:obj:`int`: The number of updates currently being processed.

        Caution:
            This value is a snapshot of the current number of updates being processed. It may
            change immediately after being read.

        .. versionadded:: 21.11
        """
        return self.max_concurrent_updates - self._semaphore.current_value

    @abstractmethod
    async def do_process_update(
        self,
        update: object,
        coroutine: "Awaitable[Any]",
    ) -> None:
        """Custom implementation of how to process an update. Must be implemented by a subclass.

        Warning:
            This method will be called by :meth:`process_update`. It should *not* be called
            manually.

        Args:
            update (:obj:`object`): The update to be processed.
            coroutine (:term:`Awaitable`): The coroutine that will be awaited to process the
                update.
        """

    @abstractmethod
    async def initialize(self) -> None:
        """Initializes the processor so resources can be allocated. Must be implemented by a
        subclass.

        .. seealso::
            :meth:`shutdown`
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the processor so resources can be freed. Must be implemented by a subclass.

        .. seealso::
            :meth:`initialize`
        """

    @final
    async def process_update(
        self,
        update: object,
        coroutine: "Awaitable[Any]",
    ) -> None:
        """Calls :meth:`do_process_update` with a semaphore to limit the number of concurrent
        updates.

        Args:
            update (:obj:`object`): The update to be processed.
            coroutine (:term:`Awaitable`): The coroutine that will be awaited to process the
                update.
        """
        async with self._semaphore:
            await self.do_process_update(update, coroutine)


class SimpleUpdateProcessor(BaseUpdateProcessor):
    """Instance of :class:`telegram.ext.BaseUpdateProcessor` that immediately awaits the
    coroutine, i.e. does not apply any additional processing. This is used by default when
    :attr:`telegram.ext.ApplicationBuilder.concurrent_updates` is :obj:`int`.

    .. versionadded:: 20.4
    """

    __slots__ = ()

    async def do_process_update(
        self,
        update: object,  # noqa: ARG002
        coroutine: "Awaitable[Any]",
    ) -> None:
        """Immediately awaits the coroutine, i.e. does not apply any additional processing.

        Args:
            update (:obj:`object`): The update to be processed.
            coroutine (:term:`Awaitable`): The coroutine that will be awaited to process the
                update.
        """
        await coroutine

    async def initialize(self) -> None:
        """Does nothing."""

    async def shutdown(self) -> None:
        """Does nothing."""
