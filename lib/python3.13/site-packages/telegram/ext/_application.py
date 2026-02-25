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
"""This module contains the Application class."""

import asyncio
import contextlib
import datetime as dtm
import inspect
import itertools
import platform
import signal
import sys
from collections import defaultdict
from collections.abc import Awaitable, Callable, Coroutine, Generator, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import TYPE_CHECKING, Any, Generic, NoReturn, TypeAlias, TypeVar

from telegram._update import Update
from telegram._utils.defaultvalue import (
    DEFAULT_80,
    DEFAULT_IP,
    DEFAULT_NONE,
    DEFAULT_TRUE,
    DefaultValue,
)
from telegram._utils.logging import get_logger
from telegram._utils.repr import build_repr_with_selected_attrs
from telegram._utils.types import SCT, DVType, ODVInput, TimePeriod
from telegram._utils.warnings import warn
from telegram.error import TelegramError
from telegram.ext._basepersistence import BasePersistence
from telegram.ext._contexttypes import ContextTypes
from telegram.ext._extbot import ExtBot
from telegram.ext._handlers.basehandler import BaseHandler
from telegram.ext._updater import Updater
from telegram.ext._utils.networkloop import network_retry_loop
from telegram.ext._utils.stack import was_called_by
from telegram.ext._utils.trackingdict import TrackingDict
from telegram.ext._utils.types import BD, BT, CCT, CD, JQ, RT, UD, ConversationKey, HandlerCallback
from telegram.warnings import PTBDeprecationWarning

if TYPE_CHECKING:
    from socket import socket

    from telegram import Message
    from telegram.ext import ConversationHandler, JobQueue
    from telegram.ext._applicationbuilder import InitApplicationBuilder
    from telegram.ext._baseupdateprocessor import BaseUpdateProcessor
    from telegram.ext._jobqueue import Job

DEFAULT_GROUP: int = 0

_AppType = TypeVar("_AppType", bound="Application")  # pylint: disable=invalid-name
_STOP_SIGNAL = object()
_DEFAULT_0 = DefaultValue(0)

# Since python 3.12, the coroutine passed to create_task should not be an (async) generator. Remove
# this check when we drop support for python 3.11.
if sys.version_info >= (3, 12):
    _CoroType = Awaitable[RT]
else:
    _CoroType: TypeAlias = Generator["asyncio.Future[object]", None, RT] | Awaitable[RT]

_ErrorCoroType: TypeAlias = _CoroType[RT] | None

_LOGGER = get_logger(__name__)


class ApplicationHandlerStop(Exception):
    """
    Raise this in a handler or an error handler to prevent execution of any other handler (even in
    different groups).

    In order to use this exception in a :class:`telegram.ext.ConversationHandler`, pass the
    optional :paramref:`state` parameter instead of returning the next state:

    .. code-block:: python

        async def conversation_callback(update, context):
            ...
            raise ApplicationHandlerStop(next_state)

    Note:
        Has no effect, if the handler or error handler is run in a non-blocking way.

    Args:
        state (:obj:`object`, optional): The next state of the conversation.

    Attributes:
        state (:obj:`object`): Optional. The next state of the conversation.
    """

    __slots__ = ("state",)

    def __init__(self, state: object | None = None) -> None:
        super().__init__()
        self.state: object | None = state


class Application(
    contextlib.AbstractAsyncContextManager["Application"],
    Generic[BT, CCT, UD, CD, BD, JQ],
):
    """This class dispatches all kinds of updates to its registered handlers, and is the entry
    point to a PTB application.

    Tip:
         This class may not be initialized directly. Use :class:`telegram.ext.ApplicationBuilder`
         or :meth:`builder` (for convenience).

    Instances of this class can be used as asyncio context managers, where

    .. code:: python

        async with application:
            # code

    is roughly equivalent to

    .. code:: python

        try:
            await application.initialize()
            # code
        finally:
            await application.shutdown()

    .. seealso:: :meth:`__aenter__` and :meth:`__aexit__`.

    This class is a :class:`~typing.Generic` class and accepts six type variables:

    1. The type of :attr:`bot`. Must be :class:`telegram.Bot` or a subclass of that class.
    2. The type of the argument ``context`` of callback functions for (error) handlers and jobs.
       Must be :class:`telegram.ext.CallbackContext` or a subclass of that class. This must be
       consistent with the following types.
    3. The type of the values of :attr:`user_data`.
    4. The type of the values of :attr:`chat_data`.
    5. The type of :attr:`bot_data`.
    6. The type of :attr:`job_queue`. Must either be :class:`telegram.ext.JobQueue` or a subclass
       of that or :obj:`None`.

    Examples:
        :any:`Echo Bot <examples.echobot>`

    .. seealso:: :wiki:`Your First Bot <Extensions---Your-first-Bot>`,
        :wiki:`Architecture Overview <Architecture>`

    .. versionchanged:: 20.0

        * Initialization is now done through the :class:`telegram.ext.ApplicationBuilder`.
        * Removed the attribute ``groups``.

    Attributes:
        bot (:class:`telegram.Bot`): The bot object that should be passed to the handlers.
        update_queue (:class:`asyncio.Queue`): The synchronized queue that will contain the
            updates.
        updater (:class:`telegram.ext.Updater`): Optional. The updater used by this application.
        chat_data (:obj:`types.MappingProxyType`): A dictionary handlers can use to store data for
            the chat. For each integer chat id, the corresponding value of this mapping is
            available as :attr:`telegram.ext.CallbackContext.chat_data` in handler callbacks for
            updates from that chat.

            .. versionchanged:: 20.0
                :attr:`chat_data` is now read-only. Note that the values of the mapping are still
                mutable, i.e. editing ``context.chat_data`` within a handler callback is possible
                (and encouraged), but editing the mapping ``application.chat_data`` itself is not.

            .. tip::

                * Manually modifying :attr:`chat_data` is almost never needed and unadvisable.
                * Entries are never deleted automatically from this mapping. If you want to delete
                  the data associated with a specific chat, e.g. if the bot got removed from that
                  chat, please use :meth:`drop_chat_data`.

        user_data (:obj:`types.MappingProxyType`): A dictionary handlers can use to store data for
            the user. For each integer user id, the corresponding value of this mapping is
            available as :attr:`telegram.ext.CallbackContext.user_data` in handler callbacks for
            updates from that user.

            .. versionchanged:: 20.0
                :attr:`user_data` is now read-only. Note that the values of the mapping are still
                mutable, i.e. editing ``context.user_data`` within a handler callback is possible
                (and encouraged), but editing the mapping ``application.user_data`` itself is not.

            .. tip::

               * Manually modifying :attr:`user_data` is almost never needed and unadvisable.
               * Entries are never deleted automatically from this mapping. If you want to delete
                 the data associated with a specific user, e.g. if that user blocked the bot,
                 please use :meth:`drop_user_data`.

        bot_data (:obj:`dict`): A dictionary handlers can use to store data for the bot.
        persistence (:class:`telegram.ext.BasePersistence`): The persistence class to
            store data that should be persistent over restarts.
        handlers (dict[:obj:`int`, list[:class:`telegram.ext.BaseHandler`]]): A dictionary mapping
            each handler group to the list of handlers registered to that group.

            .. seealso::
                :meth:`add_handler`, :meth:`add_handlers`.
        error_handlers (dict[:term:`coroutine function`, :obj:`bool`]): A dictionary where the keys
            are error handlers and the values indicate whether they are to be run blocking.

            .. seealso::
                :meth:`add_error_handler`
        context_types (:class:`telegram.ext.ContextTypes`): Specifies the types used by this
            dispatcher for the ``context`` argument of handler and job callbacks.
        post_init (:term:`coroutine function`): Optional. A callback that will be executed by
            :meth:`Application.run_polling` and :meth:`Application.run_webhook` after initializing
            the application via :meth:`initialize`.
        post_shutdown (:term:`coroutine function`): Optional. A callback that will be executed by
            :meth:`Application.run_polling` and :meth:`Application.run_webhook` after shutting down
            the application via :meth:`shutdown`.
        post_stop (:term:`coroutine function`): Optional. A callback that will be executed by
            :meth:`Application.run_polling` and :meth:`Application.run_webhook` after stopping
            the application via :meth:`stop`.

            .. versionadded:: 20.1

    """

    __slots__ = (
        (
            "__create_task_tasks",
            "__update_fetcher_task",
            "__update_persistence_event",
            "__update_persistence_lock",
            "__update_persistence_task",
            "__stop_running_marker",
            "_chat_data",
            "_chat_ids_to_be_deleted_in_persistence",
            "_chat_ids_to_be_updated_in_persistence",
            "_conversation_handler_conversations",
            "_initialized",
            "_job_queue",
            "_running",
            "_update_processor",
            "_user_data",
            "_user_ids_to_be_deleted_in_persistence",
            "_user_ids_to_be_updated_in_persistence",
            "bot",
            "bot_data",
            "chat_data",
            "context_types",
            "error_handlers",
            "handlers",
            "persistence",
            "post_init",
            "post_shutdown",
            "post_stop",
            "update_queue",
            "updater",
            "user_data",
        )
        # Allowing '__weakref__' creation here since we need it for the JobQueue
        # Currently the __weakref__ slot is already created
        # in the AsyncContextManager base class for pythons < 3.13
        + (("__weakref__",) if sys.version_info >= (3, 13) else ())
    )

    def __init__(
        self: "Application[BT, CCT, UD, CD, BD, JQ]",
        *,
        bot: BT,
        update_queue: "asyncio.Queue[object]",
        updater: Updater | None,
        job_queue: JQ,
        update_processor: "BaseUpdateProcessor",
        persistence: BasePersistence[UD, CD, BD] | None,
        context_types: ContextTypes[CCT, UD, CD, BD],
        post_init: (
            Callable[["Application[BT, CCT, UD, CD, BD, JQ]"], Coroutine[Any, Any, None]] | None
        ),
        post_shutdown: (
            Callable[["Application[BT, CCT, UD, CD, BD, JQ]"], Coroutine[Any, Any, None]] | None
        ),
        post_stop: (
            Callable[["Application[BT, CCT, UD, CD, BD, JQ]"], Coroutine[Any, Any, None]] | None
        ),
    ):
        if not was_called_by(
            inspect.currentframe(), Path(__file__).parent.resolve() / "_applicationbuilder.py"
        ):
            warn(
                "`Application` instances should be built via the `ApplicationBuilder`.",
                stacklevel=2,
            )

        self.bot: BT = bot
        self.update_queue: asyncio.Queue[object] = update_queue
        self.context_types: ContextTypes[CCT, UD, CD, BD] = context_types
        self.updater: Updater | None = updater
        self.handlers: dict[int, list[BaseHandler[Any, CCT, Any]]] = {}
        self.error_handlers: dict[
            HandlerCallback[object, CCT, None], bool | DefaultValue[bool]
        ] = {}
        self.post_init: (
            Callable[[Application[BT, CCT, UD, CD, BD, JQ]], Coroutine[Any, Any, None]] | None
        ) = post_init
        self.post_shutdown: (
            Callable[[Application[BT, CCT, UD, CD, BD, JQ]], Coroutine[Any, Any, None]] | None
        ) = post_shutdown
        self.post_stop: (
            Callable[[Application[BT, CCT, UD, CD, BD, JQ]], Coroutine[Any, Any, None]] | None
        ) = post_stop
        self._update_processor = update_processor
        self.bot_data: BD = self.context_types.bot_data()
        self._user_data: defaultdict[int, UD] = defaultdict(self.context_types.user_data)
        self._chat_data: defaultdict[int, CD] = defaultdict(self.context_types.chat_data)
        # Read only mapping
        self.user_data: Mapping[int, UD] = MappingProxyType(self._user_data)
        self.chat_data: Mapping[int, CD] = MappingProxyType(self._chat_data)

        self.persistence: BasePersistence[UD, CD, BD] | None = None
        if persistence and not isinstance(persistence, BasePersistence):
            raise TypeError("persistence must be based on telegram.ext.BasePersistence")
        self.persistence = persistence

        # Some bookkeeping for persistence logic
        self._chat_ids_to_be_updated_in_persistence: set[int] = set()
        self._user_ids_to_be_updated_in_persistence: set[int] = set()
        self._chat_ids_to_be_deleted_in_persistence: set[int] = set()
        self._user_ids_to_be_deleted_in_persistence: set[int] = set()

        # This attribute will hold references to the conversation dicts of all conversation
        # handlers so that we can extract the changed states during `update_persistence`
        self._conversation_handler_conversations: dict[
            str, TrackingDict[ConversationKey, object]
        ] = {}

        # A number of low-level helpers for the internal logic
        self._initialized = False
        self._running = False
        self._job_queue: JQ = job_queue
        self.__update_fetcher_task: asyncio.Task | None = None
        self.__update_persistence_task: asyncio.Task | None = None
        self.__update_persistence_event = asyncio.Event()
        self.__update_persistence_lock = asyncio.Lock()
        self.__create_task_tasks: set[asyncio.Task] = set()  # Used for awaiting tasks upon exit
        self.__stop_running_marker = asyncio.Event()

    async def __aenter__(self: _AppType) -> _AppType:
        """|async_context_manager| :meth:`initializes <initialize>` the App.

        Returns:
            The initialized App instance.

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
        """|async_context_manager| :meth:`shuts down <shutdown>` the App."""
        # Make sure not to return `True` so that exceptions are not suppressed
        # https://docs.python.org/3/reference/datamodel.html?#object.__aexit__
        await self.shutdown()

    def __repr__(self) -> str:
        """Give a string representation of the application in the form ``Application[bot=...]``.

        As this class doesn't implement :meth:`object.__str__`, the default implementation
        will be used, which is equivalent to :meth:`__repr__`.

        Returns:
            :obj:`str`
        """
        return build_repr_with_selected_attrs(self, bot=self.bot)

    @property
    def running(self) -> bool:
        """:obj:`bool`: Indicates if this application is running.

        .. seealso::
            :meth:`start`, :meth:`stop`
        """
        return self._running

    @property
    def concurrent_updates(self) -> int:
        """:obj:`int`: The number of concurrent updates that will be processed in parallel. A
        value of ``0`` indicates updates are *not* being processed concurrently.

        .. versionchanged:: 20.4
            This is now just a shortcut to :attr:`update_processor.max_concurrent_updates
            <telegram.ext.BaseUpdateProcessor.max_concurrent_updates>`.

        .. seealso:: :wiki:`Concurrency`
        """
        return self._update_processor.max_concurrent_updates

    @property
    def job_queue(self) -> "JobQueue[CCT] | None":
        """
        :class:`telegram.ext.JobQueue`: The :class:`JobQueue` used by the
            :class:`telegram.ext.Application`.

        .. seealso:: :wiki:`Job Queue <Extensions---JobQueue>`
        """
        if self._job_queue is None:
            warn(
                "No `JobQueue` set up. To use `JobQueue`, you must install PTB via "
                '`pip install "python-telegram-bot[job-queue]"`.',
                stacklevel=2,
            )
        return self._job_queue

    @property
    def update_processor(self) -> "BaseUpdateProcessor":
        """:class:`telegram.ext.BaseUpdateProcessor`: The update processor used by this
        application.

        .. seealso:: :wiki:`Concurrency`

        .. versionadded:: 20.4
        """
        return self._update_processor

    @staticmethod
    def _raise_system_exit() -> NoReturn:
        raise SystemExit

    @staticmethod
    def builder() -> "InitApplicationBuilder":
        """Convenience method. Returns a new :class:`telegram.ext.ApplicationBuilder`.

        .. versionadded:: 20.0
        """
        # Unfortunately this needs to be here due to cyclical imports
        from telegram.ext import (  # pylint: disable=import-outside-toplevel  # noqa: PLC0415
            ApplicationBuilder,
        )

        return ApplicationBuilder()

    def _check_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError(
                "This Application was not initialized via `Application.initialize`!"
            )

    async def initialize(self) -> None:
        """Initializes the Application by initializing:

        * The :attr:`bot`, by calling :meth:`telegram.Bot.initialize`.
        * The :attr:`updater`, by calling :meth:`telegram.ext.Updater.initialize`.
        * The :attr:`persistence`, by loading persistent conversations and data.
        * The :attr:`update_processor` by calling
          :meth:`telegram.ext.BaseUpdateProcessor.initialize`.

        Does *not* call :attr:`post_init` - that is only done by :meth:`run_polling` and
        :meth:`run_webhook`.

        .. seealso::
            :meth:`shutdown`
        """
        if self._initialized:
            _LOGGER.debug("This Application is already initialized.")
            return

        await self.bot.initialize()
        await self._update_processor.initialize()

        if self.updater:
            await self.updater.initialize()

        if not self.persistence:
            self._initialized = True
            return

        await self._initialize_persistence()

        # Unfortunately due to circular imports this has to be here
        # pylint: disable=import-outside-toplevel
        from telegram.ext._handlers.conversationhandler import ConversationHandler  # noqa: PLC0415

        # Initialize the persistent conversation handlers with the stored states
        for handler in itertools.chain.from_iterable(self.handlers.values()):
            if isinstance(handler, ConversationHandler) and handler.persistent and handler.name:
                await self._add_ch_to_persistence(handler)

        self._initialized = True
        self.__stop_running_marker.clear()

    async def _add_ch_to_persistence(self, handler: "ConversationHandler") -> None:
        self._conversation_handler_conversations.update(
            await handler._initialize_persistence(self)  # pylint: disable=protected-access
        )

    async def shutdown(self) -> None:
        """Shuts down the Application by shutting down:

        * :attr:`bot` by calling :meth:`telegram.Bot.shutdown`
        * :attr:`updater` by calling :meth:`telegram.ext.Updater.shutdown`
        * :attr:`persistence` by calling :meth:`update_persistence` and
          :meth:`BasePersistence.flush`
        * :attr:`update_processor` by calling :meth:`telegram.ext.BaseUpdateProcessor.shutdown`

        Does *not* call :attr:`post_shutdown` - that is only done by :meth:`run_polling` and
        :meth:`run_webhook`.

        .. seealso::
            :meth:`initialize`

        Raises:
            :exc:`RuntimeError`: If the application is still :attr:`running`.
        """
        if self.running:
            raise RuntimeError("This Application is still running!")

        if not self._initialized:
            _LOGGER.debug("This Application is already shut down. Returning.")
            return

        await self.bot.shutdown()
        await self._update_processor.shutdown()

        if self.updater:
            await self.updater.shutdown()

        if self.persistence:
            _LOGGER.debug("Updating & flushing persistence before shutdown")
            await self.update_persistence()
            await self.persistence.flush()
            _LOGGER.debug("Updated and flushed persistence")

        self._initialized = False

    async def _initialize_persistence(self) -> None:
        """This method basically just loads all the data by awaiting the BP methods"""
        if not self.persistence:
            return

        if self.persistence.store_data.user_data:
            self._user_data.update(await self.persistence.get_user_data())
        if self.persistence.store_data.chat_data:
            self._chat_data.update(await self.persistence.get_chat_data())
        if self.persistence.store_data.bot_data:
            self.bot_data = await self.persistence.get_bot_data()
            if not isinstance(self.bot_data, self.context_types.bot_data):
                raise ValueError(
                    f"bot_data must be of type {self.context_types.bot_data.__name__}"
                )

        # Mypy doesn't know that persistence.set_bot (see above) already checks that
        # self.bot is an instance of ExtBot if callback_data should be stored ...
        if self.persistence.store_data.callback_data and (
            self.bot.callback_data_cache is not None  # type: ignore[attr-defined]
        ):
            persistent_data = await self.persistence.get_callback_data()
            if persistent_data is not None:
                if not isinstance(persistent_data, tuple) or len(persistent_data) != 2:
                    raise ValueError("callback_data must be a tuple of length 2")
                self.bot.callback_data_cache.load_persistence_data(  # type: ignore[attr-defined]
                    persistent_data
                )

    async def start(self) -> None:
        """Starts

        * a background task that fetches updates from :attr:`update_queue` and processes them via
          :meth:`process_update`.
        * :attr:`job_queue`, if set.
        * a background task that calls :meth:`update_persistence` in regular intervals, if
          :attr:`persistence` is set.

        Note:
            This does *not* start fetching updates from Telegram. To fetch updates, you need to
            either start :attr:`updater` manually or use one of :meth:`run_polling` or
            :meth:`run_webhook`.

        Tip:
            When using a custom logic for startup and shutdown of the application, eventual
            cancellation of pending tasks should happen only `after` :meth:`stop` has been called
            in order to ensure that the tasks mentioned above are not cancelled prematurely.

        .. seealso::
            :meth:`stop`

        Raises:
            :exc:`RuntimeError`: If the application is already running or was not initialized.
        """
        if self.running:
            raise RuntimeError("This Application is already running!")
        self._check_initialized()

        self._running = True
        self.__update_persistence_event.clear()

        try:
            if self.persistence:
                self.__update_persistence_task = asyncio.create_task(
                    self._persistence_updater(),
                    name=f"Application:{self.bot.id}:persistence_updater",
                )
                _LOGGER.debug("Loop for updating persistence started")

            if self._job_queue:
                await self._job_queue.start()  # type: ignore[union-attr]
                _LOGGER.debug("JobQueue started")

            self.__update_fetcher_task = asyncio.create_task(
                self._update_fetcher(), name=f"Application:{self.bot.id}:update_fetcher"
            )
            _LOGGER.info("Application started")

        except Exception:
            self._running = False
            raise

    async def stop(self) -> None:
        """Stops the process after processing any pending updates or tasks created by
        :meth:`create_task`. Also stops :attr:`job_queue`, if set.
        Finally, calls :meth:`update_persistence` and :meth:`BasePersistence.flush` on
        :attr:`persistence`, if set.

        Warning:
            Once this method is called, no more updates will be fetched from :attr:`update_queue`,
            even if it's not empty.

        .. seealso::
            :meth:`start`

        Note:
            * This does *not* stop :attr:`updater`. You need to either manually call
              :meth:`telegram.ext.Updater.stop` or use one of :meth:`run_polling` or
              :meth:`run_webhook`.
            * Does *not* call :attr:`post_stop` - that is only done by
              :meth:`run_polling` and :meth:`run_webhook`.

        Raises:
            :exc:`RuntimeError`: If the application is not running.
        """
        if not self.running:
            raise RuntimeError("This Application is not running!")

        self._running = False
        self.__stop_running_marker.clear()
        _LOGGER.info("Application is stopping. This might take a moment.")

        # Stop listening for new updates and handle all pending ones
        if self.__update_fetcher_task:
            if self.__update_fetcher_task.done():
                try:
                    self.__update_fetcher_task.result()
                except BaseException as exc:
                    _LOGGER.critical(
                        "Fetching updates was aborted due to %r. Suppressing "
                        "exception to ensure graceful shutdown.",
                        exc,
                        exc_info=True,
                    )
            else:
                await self.update_queue.put(_STOP_SIGNAL)
                _LOGGER.debug("Waiting for update_queue to join")
                await self.update_queue.join()
                await self.__update_fetcher_task
        _LOGGER.debug("Application stopped fetching of updates.")

        if self._job_queue:
            _LOGGER.debug("Waiting for running jobs to finish")
            await self._job_queue.stop(wait=True)  # type: ignore[union-attr]
            _LOGGER.debug("JobQueue stopped")

        _LOGGER.debug("Waiting for `create_task` calls to be processed")
        await asyncio.gather(*self.__create_task_tasks, return_exceptions=True)

        # Make sure that this is the *last* step of stopping the application!
        if self.persistence and self.__update_persistence_task:
            _LOGGER.debug("Waiting for persistence loop to finish")
            self.__update_persistence_event.set()
            await self.__update_persistence_task
            self.__update_persistence_event.clear()

        _LOGGER.info("Application.stop() complete")

    def stop_running(self) -> None:
        """This method can be used to stop the execution of :meth:`run_polling` or
        :meth:`run_webhook` from within a handler, job or error callback. This allows a graceful
        shutdown of the application, i.e. the methods listed in :attr:`run_polling` and
        :attr:`run_webhook` will still be executed.

        This method can also be called within :meth:`post_init`. This allows for a graceful,
        early shutdown of the application if some condition is met (e.g., a database connection
        could not be established).

        Note:
            If the application is not running and this method is not called within
            :meth:`post_init`, this method does nothing.

        Warning:
            This method is designed to for use in combination with :meth:`run_polling` or
            :meth:`run_webhook`. Using this method in combination with a custom logic for starting
            and stopping the application is not guaranteed to work as expected. Use at your own
            risk.

        .. versionadded:: 20.5

        .. versionchanged:: 21.2
            Added support for calling within :meth:`post_init`.
        """
        if self.running:
            # This works because `__run` is using `loop.run_forever()`. If that changes, this
            # method needs to be adapted.
            asyncio.get_running_loop().stop()
        else:
            self.__stop_running_marker.set()
            if not self._initialized:
                _LOGGER.debug(
                    "Application is not running and not initialized. `stop_running()` likely has "
                    "no effect."
                )

    def run_polling(
        self,
        poll_interval: float = 0.0,
        timeout: TimePeriod = dtm.timedelta(seconds=10),
        bootstrap_retries: int = 0,
        allowed_updates: Sequence[str] | None = None,
        drop_pending_updates: bool | None = None,
        close_loop: bool = True,
        stop_signals: ODVInput[Sequence[int]] = DEFAULT_NONE,
    ) -> None:
        """Convenience method that takes care of initializing and starting the app,
        polling updates from Telegram using :meth:`telegram.ext.Updater.start_polling` and
        a graceful shutdown of the app on exit.

        |app_run_shutdown| :paramref:`stop_signals`.

        The order of execution by :meth:`run_polling` is roughly as follows:

        - :meth:`initialize`
        - :meth:`post_init`
        - :meth:`telegram.ext.Updater.start_polling`
        - :meth:`start`
        - Run the application until the users stops it
        - :meth:`telegram.ext.Updater.stop`
        - :meth:`stop`
        - :meth:`post_stop`
        - :meth:`shutdown`
        - :meth:`post_shutdown`

        A small wrapper is passed to :paramref:`telegram.ext.Updater.start_polling.error_callback`
        which forwards errors occurring during polling to
        :meth:`registered error handlers <add_error_handler>`. The update parameter of the callback
        will be set to :obj:`None`.

        .. include:: inclusions/application_run_tip.rst

        .. versionchanged::
            Removed the deprecated parameters ``read_timeout``, ``write_timeout``,
            ``connect_timeout``, and ``pool_timeout``. Use the corresponding methods in
            :class:`telegram.ext.ApplicationBuilder` instead.

        Args:
            poll_interval (:obj:`float`, optional): Time to wait between polling updates from
                Telegram in seconds. Default is ``0.0``.
            timeout (:obj:`int` | :class:`datetime.timedelta`, optional): Passed to
                :paramref:`telegram.Bot.get_updates.timeout`.
                Default is :obj:`timedelta(seconds=10)<datetime.timedelta>`.

                .. versionchanged:: v22.2
                    |time-period-input|
            bootstrap_retries (:obj:`int`, optional): Whether the bootstrapping phase
                (calling :meth:`initialize` and the boostrapping of
                :meth:`telegram.ext.Updater.start_polling`)
                will retry on failures on the Telegram server.

                * < 0 - retry indefinitely
                *   0 - no retries (default)
                * > 0 - retry up to X times

                .. versionchanged:: 21.11
                    The default value will be changed to from ``-1`` to ``0``. Indefinite retries
                    during bootstrapping are not recommended.

            drop_pending_updates (:obj:`bool`, optional): Whether to clean any pending updates on
                Telegram servers before actually starting to poll. Default is :obj:`False`.
            allowed_updates (Sequence[:obj:`str`], optional): Passed to
                :meth:`telegram.Bot.get_updates`.

                .. versionchanged:: 21.9
                    Accepts any :class:`collections.abc.Sequence` as input instead of just a list
            close_loop (:obj:`bool`, optional): If :obj:`True`, the current event loop will be
                closed upon shutdown. Defaults to :obj:`True`.

                .. seealso::
                    :meth:`asyncio.loop.close`
            stop_signals (Sequence[:obj:`int`] | :obj:`None`, optional): Signals that will shut
                down the app. Pass :obj:`None` to not use stop signals.
                Defaults to :data:`signal.SIGINT`, :data:`signal.SIGTERM` and
                :data:`signal.SIGABRT` on non Windows platforms.

                Caution:
                    Not every :class:`asyncio.AbstractEventLoop` implements
                    :meth:`asyncio.loop.add_signal_handler`. Most notably, the standard event loop
                    on Windows, :class:`asyncio.ProactorEventLoop`, does not implement this method.
                    If this method is not available, stop signals can not be set.

        Raises:
            :exc:`RuntimeError`: If the Application does not have an :class:`telegram.ext.Updater`.
        """
        if not self.updater:
            raise RuntimeError(
                "Application.run_polling is only available if the application has an Updater."
            )

        def error_callback(exc: TelegramError) -> None:
            self.create_task(self.process_error(error=exc, update=None))

        return self.__run(
            updater_coroutine=self.updater.start_polling(
                poll_interval=poll_interval,
                timeout=timeout,
                bootstrap_retries=bootstrap_retries,
                allowed_updates=allowed_updates,
                drop_pending_updates=drop_pending_updates,
                error_callback=error_callback,  # if there is an error in fetching updates
            ),
            stop_signals=stop_signals,
            bootstrap_retries=bootstrap_retries,
            close_loop=close_loop,
        )

    def run_webhook(
        self,
        listen: DVType[str] = DEFAULT_IP,
        port: DVType[int] = DEFAULT_80,
        url_path: str = "",
        cert: str | Path | None = None,
        key: str | Path | None = None,
        bootstrap_retries: int = 0,
        webhook_url: str | None = None,
        allowed_updates: Sequence[str] | None = None,
        drop_pending_updates: bool | None = None,
        ip_address: str | None = None,
        max_connections: int = 40,
        close_loop: bool = True,
        stop_signals: ODVInput[Sequence[int]] = DEFAULT_NONE,
        secret_token: str | None = None,
        unix: "str | Path | socket | None" = None,
    ) -> None:
        """Convenience method that takes care of initializing and starting the app,
        listening for updates from Telegram using :meth:`telegram.ext.Updater.start_webhook` and
        a graceful shutdown of the app on exit.

        |app_run_shutdown| :paramref:`stop_signals`.

        If :paramref:`cert`
        and :paramref:`key` are not provided, the webhook will be started directly on
        ``http://listen:port/url_path``, so SSL can be handled by another
        application. Else, the webhook will be started on
        ``https://listen:port/url_path``. Also calls :meth:`telegram.Bot.set_webhook` as
        required.

        The order of execution by :meth:`run_webhook` is roughly as follows:

        - :meth:`initialize`
        - :meth:`post_init`
        - :meth:`telegram.ext.Updater.start_webhook`
        - :meth:`start`
        - Run the application until the users stops it
        - :meth:`telegram.ext.Updater.stop`
        - :meth:`stop`
        - :meth:`post_stop`
        - :meth:`shutdown`
        - :meth:`post_shutdown`

        Important:
            If you want to use this method, you must install PTB with the optional requirement
            ``webhooks``, i.e.

            .. code-block:: bash

               pip install "python-telegram-bot[webhooks]"

        .. include:: inclusions/application_run_tip.rst

        .. seealso::
            :wiki:`Webhooks`

        Args:
            listen (:obj:`str`, optional): IP-Address to listen on. Defaults to
                `127.0.0.1 <https://en.wikipedia.org/wiki/Localhost>`_.
            port (:obj:`int`, optional): Port the bot should be listening on. Must be one of
                :attr:`telegram.constants.SUPPORTED_WEBHOOK_PORTS` unless the bot is running
                behind a proxy. Defaults to ``80``.
            url_path (:obj:`str`, optional): Path inside url. Defaults to `` '' ``
            cert (:class:`pathlib.Path` | :obj:`str`, optional): Path to the SSL certificate file.
            key (:class:`pathlib.Path` | :obj:`str`, optional): Path to the SSL key file.
            bootstrap_retries (:obj:`int`, optional): Whether the bootstrapping phase
                (calling :meth:`initialize` and the boostrapping of
                :meth:`telegram.ext.Updater.start_polling`)
                will retry on failures on the Telegram server.

                * < 0 - retry indefinitely
                *   0 - no retries (default)
                * > 0 - retry up to X times
            webhook_url (:obj:`str`, optional): Explicitly specify the webhook url. Useful behind
                NAT, reverse proxy, etc. Default is derived from :paramref:`listen`,
                :paramref:`port`, :paramref:`url_path`, :paramref:`cert`, and :paramref:`key`.
            allowed_updates (Sequence[:obj:`str`], optional): Passed to
                :meth:`telegram.Bot.set_webhook`.

                .. versionchanged:: 21.9
                    Accepts any :class:`collections.abc.Sequence` as input instead of just a list
            drop_pending_updates (:obj:`bool`, optional): Whether to clean any pending updates on
                Telegram servers before actually starting to poll. Default is :obj:`False`.
            ip_address (:obj:`str`, optional): Passed to :meth:`telegram.Bot.set_webhook`.
            max_connections (:obj:`int`, optional): Passed to
                :meth:`telegram.Bot.set_webhook`. Defaults to ``40``.
            close_loop (:obj:`bool`, optional): If :obj:`True`, the current event loop will be
                closed upon shutdown. Defaults to :obj:`True`.

                .. seealso::
                    :meth:`asyncio.loop.close`
            stop_signals (Sequence[:obj:`int`] | :obj:`None`, optional): Signals that will shut
                down the app. Pass :obj:`None` to not use stop signals.
                Defaults to :data:`signal.SIGINT`, :data:`signal.SIGTERM` and
                :data:`signal.SIGABRT`.

                Caution:
                    Not every :class:`asyncio.AbstractEventLoop` implements
                    :meth:`asyncio.loop.add_signal_handler`. Most notably, the standard event loop
                    on Windows, :class:`asyncio.ProactorEventLoop`, does not implement this method.
                    If this method is not available, stop signals can not be set.
            secret_token (:obj:`str`, optional): Secret token to ensure webhook requests originate
                from Telegram. See :paramref:`telegram.Bot.set_webhook.secret_token` for more
                details.

                When added, the web server started by this call will expect the token to be set in
                the ``X-Telegram-Bot-Api-Secret-Token`` header of an incoming request and will
                raise a :class:`http.HTTPStatus.FORBIDDEN <http.HTTPStatus>` error if either the
                header isn't set or it is set to a wrong token.

                .. versionadded:: 20.0
            unix (:class:`pathlib.Path` | :obj:`str` | :class:`socket.socket`, optional): Can be
                either:

                * the path to the unix socket file as :class:`pathlib.Path` or :obj:`str`. This
                  will be passed to `tornado.netutil.bind_unix_socket <https://www.tornadoweb.org/
                  en/stable/netutil.html#tornado.netutil.bind_unix_socket>`_ to create the socket.
                  If the Path does not exist, the file will be created.

                * or the socket itself. This option allows you to e.g. restrict the permissions of
                  the socket for improved security. Note that you need to pass the correct family,
                  type and socket options yourself.

                Caution:
                    This parameter is a replacement for the default TCP bind. Therefore, it is
                    mutually exclusive with :paramref:`listen` and :paramref:`port`. When using
                    this param, you must also run a reverse proxy to the unix socket and set the
                    appropriate :paramref:`webhook_url`.

                .. versionadded:: 20.8
                .. versionchanged:: 21.1
                    Added support to pass a socket instance itself.
        """
        if not self.updater:
            raise RuntimeError(
                "Application.run_webhook is only available if the application has an Updater."
            )

        return self.__run(
            updater_coroutine=self.updater.start_webhook(
                listen=listen,
                port=port,
                url_path=url_path,
                cert=cert,
                key=key,
                bootstrap_retries=bootstrap_retries,
                drop_pending_updates=drop_pending_updates,
                webhook_url=webhook_url,
                allowed_updates=allowed_updates,
                ip_address=ip_address,
                max_connections=max_connections,
                secret_token=secret_token,
                unix=unix,
            ),
            stop_signals=stop_signals,
            bootstrap_retries=bootstrap_retries,
            close_loop=close_loop,
        )

    async def _bootstrap_initialize(self, max_retries: int) -> None:
        await network_retry_loop(
            action_cb=self.initialize,
            description="Bootstrap Initialize Application",
            max_retries=max_retries,
            interval=1,
        )

    def __run(
        self,
        updater_coroutine: Coroutine,
        stop_signals: ODVInput[Sequence[int]],
        bootstrap_retries: int,
        close_loop: bool = True,
    ) -> None:
        # Try to get the running event loop first, and if there isn't one, create a new one.
        # This handles the Python 3.14+ behavior where get_event_loop() raises RuntimeError
        # when there's no current event loop in the main thread.
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No running event loop, create and set a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if stop_signals is DEFAULT_NONE and platform.system() != "Windows":
            stop_signals = (signal.SIGINT, signal.SIGTERM, signal.SIGABRT)

        try:
            if not isinstance(stop_signals, DefaultValue):
                for sig in stop_signals or []:
                    loop.add_signal_handler(sig, self._raise_system_exit)
        except NotImplementedError as exc:
            warn(
                f"Could not add signal handlers for the stop signals {stop_signals} due to "
                f"exception `{exc!r}`. If your event loop does not implement `add_signal_handler`,"
                " please pass `stop_signals=None`.",
                stacklevel=3,
            )

        try:
            loop.run_until_complete(self._bootstrap_initialize(max_retries=bootstrap_retries))
            if self.post_init:
                loop.run_until_complete(self.post_init(self))
            if self.__stop_running_marker.is_set():
                _LOGGER.info("Application received stop signal via `stop_running`. Shutting down.")
                return
            loop.run_until_complete(updater_coroutine)  # one of updater.start_webhook/polling
            loop.run_until_complete(self.start())
            loop.run_forever()
        except (KeyboardInterrupt, SystemExit):
            _LOGGER.debug("Application received stop signal. Shutting down.")
        finally:
            # We arrive here either by catching the exceptions above or if the loop gets stopped
            # In case the coroutine wasn't awaited, we don't need to bother the user with a warning
            updater_coroutine.close()

            try:
                # Mypy doesn't know that we already check if updater is None
                if self.updater.running:  # type: ignore[union-attr]
                    loop.run_until_complete(self.updater.stop())  # type: ignore[union-attr]
                if self.running:
                    loop.run_until_complete(self.stop())
                    # post_stop should be called only if stop was called!
                    if self.post_stop:
                        loop.run_until_complete(self.post_stop(self))
                loop.run_until_complete(self.shutdown())
                if self.post_shutdown:
                    loop.run_until_complete(self.post_shutdown(self))
            finally:
                if close_loop:
                    loop.close()

    def create_task(
        self,
        coroutine: _CoroType[RT],
        update: object | None = None,
        *,
        name: str | None = None,
    ) -> "asyncio.Task[RT]":
        """Thin wrapper around :func:`asyncio.create_task` that handles exceptions raised by
        the :paramref:`coroutine` with :meth:`process_error`.

        Note:
            * If :paramref:`coroutine` raises an exception, it will be set on the task created by
              this method even though it's handled by :meth:`process_error`.
            * If the application is currently running, tasks created by this method will be
              awaited with :meth:`stop`.

        .. seealso:: :wiki:`Concurrency`

        Args:
            coroutine (:term:`awaitable`): The awaitable to run as task.

                .. versionchanged:: 20.2
                    Accepts :class:`asyncio.Future` and generator-based coroutine functions.
                .. deprecated:: 20.4
                    Since Python 3.12, generator-based coroutine functions are no longer accepted.
            update (:obj:`object`, optional): If set, will be passed to :meth:`process_error`
                as additional information for the error handlers. Moreover, the corresponding
                :attr:`chat_data` and :attr:`user_data` entries will be updated in the next run of
                :meth:`update_persistence` after the :paramref:`coroutine` is finished.

        Keyword Args:
            name (:obj:`str`, optional): The name of the task.

                .. versionadded:: 20.4

        Returns:
            :class:`asyncio.Task`: The created task.
        """
        return self.__create_task(coroutine=coroutine, update=update, name=name)

    def __create_task(
        self,
        coroutine: _CoroType[RT],
        update: object | None = None,
        is_error_handler: bool = False,
        name: str | None = None,
    ) -> "asyncio.Task[RT]":
        # Unfortunately, we can't know if `coroutine` runs one of the error handler functions
        # but by passing `is_error_handler=True` from `process_error`, we can make sure that we
        # get at most one recursion of the user calls `create_task` manually with an error handler
        # function
        task: asyncio.Task[RT] = asyncio.create_task(
            self.__create_task_callback(
                coroutine=coroutine, update=update, is_error_handler=is_error_handler
            ),
            name=name,
        )

        if self.running:
            self.__create_task_tasks.add(task)
            task.add_done_callback(self.__create_task_done_callback)
        else:
            warn(
                "Tasks created via `Application.create_task` while the application is not "
                "running won't be automatically awaited!",
                stacklevel=3,
            )

        return task

    def __create_task_done_callback(self, task: asyncio.Task) -> None:
        self.__create_task_tasks.discard(task)  # Discard from our set since we are done with it
        # We just retrieve the eventual exception so that asyncio doesn't complain in case
        # it's not retrieved somewhere else
        with contextlib.suppress(asyncio.CancelledError, asyncio.InvalidStateError):
            task.exception()

    async def __create_task_callback(
        self,
        coroutine: _CoroType[RT],
        update: object | None = None,
        is_error_handler: bool = False,
    ) -> RT:
        try:
            # Generator-based coroutines are not supported in Python 3.12+
            if sys.version_info < (3, 12) and isinstance(coroutine, Generator):
                warn(
                    PTBDeprecationWarning(
                        "20.4",
                        "Generator-based coroutines are deprecated in create_task and will not"
                        " work in Python 3.12+",
                    ),
                )
                return await asyncio.create_task(coroutine)
            # If user uses generator in python 3.12+, Exception will happen and we cannot do
            # anything about it. (hence the type ignore if mypy is run on python 3.12-)
            return await coroutine  # type: ignore[misc]
        except Exception as exception:
            if isinstance(exception, ApplicationHandlerStop):
                warn(
                    "ApplicationHandlerStop is not supported with handlers running non-blocking.",
                    stacklevel=1,
                )

            # Avoid infinite recursion of error handlers.
            elif is_error_handler:
                _LOGGER.exception(
                    "An error was raised and an uncaught error was raised while "
                    "handling the error with an error_handler.",
                    exc_info=exception,
                )

            else:
                # If we arrive here, an exception happened in the task and was neither
                # ApplicationHandlerStop nor raised by an error handler.
                # So we can and must handle it
                await self.process_error(update=update, error=exception, coroutine=coroutine)

            # Raise exception so that it can be set on the task and retrieved by task.exception()
            raise
        finally:
            self._mark_for_persistence_update(update=update)

    async def __update_fetcher(self) -> None:
        # Continuously fetch updates from the queue. Exit only once the signal object is found.
        while True:
            update = await self.update_queue.get()

            if update is _STOP_SIGNAL:
                # For the _STOP_SIGNAL
                self.update_queue.task_done()
                return

            _LOGGER.debug("Processing update %s", update)

            if self._update_processor.max_concurrent_updates > 1:
                # We don't await the below because it has to be run concurrently
                self.create_task(
                    self.__process_update_wrapper(update),
                    update=update,
                    name=f"Application:{self.bot.id}:process_concurrent_update",
                )
            else:
                await self.__process_update_wrapper(update)

    async def _update_fetcher(self) -> None:
        try:
            await self.__update_fetcher()
        finally:
            while not self.update_queue.empty():
                _LOGGER.debug("Dropping pending update: %s", self.update_queue.get_nowait())
                with contextlib.suppress(ValueError):
                    # Since we're shutting down here, it's not too bad if we call task_done
                    # on an empty queue
                    self.update_queue.task_done()

    async def __process_update_wrapper(self, update: object) -> None:
        try:
            await self._update_processor.process_update(update, self.process_update(update))
        finally:
            self.update_queue.task_done()

    async def process_update(self, update: object) -> None:
        """Processes a single update and marks the update to be updated by the persistence later.
        Exceptions raised by handler callbacks will be processed by :meth:`process_error`.

        .. seealso:: :wiki:`Concurrency`

        .. versionchanged:: 20.0
            Persistence is now updated in an interval set by
            :attr:`telegram.ext.BasePersistence.update_interval`.

        Args:
            update (:class:`telegram.Update` | :obj:`object` | \
                :class:`telegram.error.TelegramError`): The update to process.

        Raises:
            :exc:`RuntimeError`: If the application was not initialized.
        """
        # Processing updates before initialize() is a problem e.g. if persistence is used
        self._check_initialized()

        context = None
        any_blocking = False  # Flag which is set to True if any handler specifies block=True

        # We copy the lists to avoid issues with concurrent modification of the
        # handlers (groups or handlers in groups) while iterating over it via add/remove_handler.
        # Currently considered implementation detail as described in docstrings of
        # add/remove_handler
        # do *not* use `copy.deepcopy` here, as we don't want to deepcopy the handlers themselves
        for handlers in [v.copy() for v in self.handlers.values()]:
            try:
                # no copy needed b/c we copy above
                for handler in handlers:
                    check = handler.check_update(update)  # Should the handler handle this update?
                    if check is None or check is False:
                        continue

                    if not context:  # build a context if not already built
                        try:
                            context = self.context_types.context.from_update(update, self)
                        except Exception as exc:
                            _LOGGER.critical(
                                (
                                    "Error while building CallbackContext for update %s. "
                                    "Update will not be processed."
                                ),
                                update,
                                exc_info=exc,
                            )
                            return
                        await context.refresh_data()
                    coroutine: Coroutine = handler.handle_update(update, self, check, context)

                    if not handler.block or (  # if handler is running with block=False,
                        handler.block is DEFAULT_TRUE
                        and isinstance(self.bot, ExtBot)
                        and self.bot.defaults
                        and not self.bot.defaults.block
                    ):
                        self.create_task(
                            coroutine,
                            update=update,
                            name=(
                                f"Application:{self.bot.id}:process_update_non_blocking:{handler}"
                            ),
                        )
                    else:
                        any_blocking = True
                        await coroutine
                    break  # Only a max of 1 handler per group is handled

            # Stop processing with any other handler.
            except ApplicationHandlerStop:
                _LOGGER.debug("Stopping further handlers due to ApplicationHandlerStop")
                break

            # Dispatch any error.
            except Exception as exc:
                if await self.process_error(update=update, error=exc):
                    _LOGGER.debug("Error handler stopped further handlers.")
                    break

        if any_blocking:
            # Only need to mark the update for persistence if there was at least one
            # blocking handler - the non-blocking handlers mark the update again when finished
            # (in __create_task_callback)
            self._mark_for_persistence_update(update=update)

    def add_handler(self, handler: BaseHandler[Any, CCT, Any], group: int = DEFAULT_GROUP) -> None:
        """Register a handler.

        TL;DR: Order and priority counts. 0 or 1 handlers per group will be used. End handling of
        update with :class:`telegram.ext.ApplicationHandlerStop`.

        A handler must be an instance of a subclass of :class:`telegram.ext.BaseHandler`. All
        handlers
        are organized in groups with a numeric value. The default group is 0. All groups will be
        evaluated for handling an update, but only 0 or 1 handler per group will be used. If
        :class:`telegram.ext.ApplicationHandlerStop` is raised from one of the handlers, no further
        handlers (regardless of the group) will be called.

        The priority/order of handlers is determined as follows:

        * Priority of the group (lower group number == higher priority)
        * The first handler in a group which can handle an update (see
          :attr:`telegram.ext.BaseHandler.check_update`) will be used. Other handlers from the
          group will not be used. The order in which handlers were added to the group defines the
          priority.

        Warning:
            Adding persistent :class:`telegram.ext.ConversationHandler` after the application has
            been initialized is discouraged. This is because the persisted conversation states need
            to be loaded into memory while the application is already processing updates, which
            might lead to race conditions and undesired behavior. In particular, current
            conversation states may be overridden by the loaded data.

        Hint:
            This method currently has no influence on calls to :meth:`process_update` that are
            already in progress.

            .. warning::
                This behavior should currently be considered an implementation detail and not as
                guaranteed behavior.

        Args:
            handler (:class:`telegram.ext.BaseHandler`): A BaseHandler instance.
            group (:obj:`int`, optional): The group identifier. Default is ``0``.

        """
        # Unfortunately due to circular imports this has to be here
        # pylint: disable=import-outside-toplevel
        from telegram.ext._handlers.conversationhandler import ConversationHandler  # noqa: PLC0415

        if not isinstance(handler, BaseHandler):
            raise TypeError(f"handler is not an instance of {BaseHandler.__name__}")
        if not isinstance(group, int):
            raise TypeError("group is not int")
        if isinstance(handler, ConversationHandler) and handler.persistent and handler.name:
            if not self.persistence:
                raise ValueError(
                    f"ConversationHandler {handler.name} "
                    "can not be persistent if application has no persistence"
                )
            if self._initialized:
                self.create_task(
                    self._add_ch_to_persistence(handler),
                    name=f"Application:{self.bot.id}:add_handler:conversation_handler_after_init",
                )
                warn(
                    "A persistent `ConversationHandler` was passed to `add_handler`, "
                    "after `Application.initialize` was called. This is discouraged."
                    "See the docs of `Application.add_handler` for details.",
                    stacklevel=2,
                )

        if group not in self.handlers:
            self.handlers[group] = []
            self.handlers = dict(sorted(self.handlers.items()))  # lower -> higher groups

        self.handlers[group].append(handler)

    def add_handlers(
        self,
        handlers: (
            Sequence[BaseHandler[Any, CCT, Any]] | dict[int, Sequence[BaseHandler[Any, CCT, Any]]]
        ),
        group: int | DefaultValue[int] = _DEFAULT_0,
    ) -> None:
        """Registers multiple handlers at once. The order of the handlers in the passed
        sequence(s) matters. See :meth:`add_handler` for details.

        .. versionadded:: 20.0

        Args:
            handlers (Sequence[:class:`telegram.ext.BaseHandler`] | \
                dict[int, Sequence[:class:`telegram.ext.BaseHandler`]]):
                Specify a sequence of handlers *or* a dictionary where the keys are groups and
                values are handlers.

                .. versionchanged:: 21.7
                    Accepts any :class:`collections.abc.Sequence` as input instead of just a list
                    or tuple.

            group (:obj:`int`, optional): Specify which group the sequence of :paramref:`handlers`
                should be added to. Defaults to ``0``.

        Example::

            app.add_handlers(handlers={
                -1: [MessageHandler(...)],
                1: [CallbackQueryHandler(...), CommandHandler(...)]
            }

        Raises:
            :exc:`TypeError`: If the combination of arguments is invalid.
        """
        if isinstance(handlers, dict) and not isinstance(group, DefaultValue):
            raise TypeError("The `group` argument can only be used with a sequence of handlers.")

        if isinstance(handlers, dict):
            for handler_group, grp_handlers in handlers.items():
                if not isinstance(grp_handlers, Sequence):
                    raise TypeError(
                        f"Handlers for group {handler_group} must be a sequence of handlers."
                    )

                for handler in grp_handlers:
                    self.add_handler(handler, handler_group)

        elif isinstance(handlers, Sequence):
            for handler in handlers:
                self.add_handler(handler, DefaultValue.get_value(group))

        else:
            raise TypeError(
                "The `handlers` argument must be a sequence of handlers or a "
                "dictionary where the keys are groups and values are sequences of handlers."
            )

    def remove_handler(
        self, handler: BaseHandler[Any, CCT, Any], group: int = DEFAULT_GROUP
    ) -> None:
        """Remove a handler from the specified group.

        Hint:
            This method currently has no influence on calls to :meth:`process_update` that are
            already in progress.

            .. warning::
                This behavior should currently be considered an implementation detail and not as
                guaranteed behavior.

        Args:
            handler (:class:`telegram.ext.BaseHandler`): A :class:`telegram.ext.BaseHandler`
                instance.
            group (:obj:`object`, optional): The group identifier. Default is ``0``.

        """
        if handler in self.handlers[group]:
            self.handlers[group].remove(handler)
            if not self.handlers[group]:
                del self.handlers[group]

    def drop_chat_data(self, chat_id: int) -> None:
        """Drops the corresponding entry from the :attr:`chat_data`. Will also be deleted from
        the persistence on the next run of :meth:`update_persistence`, if applicable.

        Warning:
            When using :attr:`concurrent_updates` or the :attr:`job_queue`,
            :meth:`process_update` or :meth:`telegram.ext.Job.run` may re-create this entry due to
            the asynchronous nature of these features. Please make sure that your program can
            avoid or handle such situations.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int`): The chat id to delete. The entry will be deleted even if it is
                not empty.
        """
        self._chat_data.pop(chat_id, None)
        self._chat_ids_to_be_deleted_in_persistence.add(chat_id)

    def drop_user_data(self, user_id: int) -> None:
        """Drops the corresponding entry from the :attr:`user_data`. Will also be deleted from
        the persistence on the next run of :meth:`update_persistence`, if applicable.

        Warning:
            When using :attr:`concurrent_updates` or the :attr:`job_queue`,
            :meth:`process_update` or :meth:`telegram.ext.Job.run` may re-create this entry due to
            the asynchronous nature of these features. Please make sure that your program can
            avoid or handle such situations.

        .. versionadded:: 20.0

        Args:
            user_id (:obj:`int`): The user id to delete. The entry will be deleted even if it is
                not empty.
        """
        self._user_data.pop(user_id, None)
        self._user_ids_to_be_deleted_in_persistence.add(user_id)

    def migrate_chat_data(
        self,
        message: "Message | None" = None,
        old_chat_id: int | None = None,
        new_chat_id: int | None = None,
    ) -> None:
        """Moves the contents of :attr:`chat_data` at key :paramref:`old_chat_id` to the key
        :paramref:`new_chat_id`. Also marks the entries to be updated accordingly in the next run
        of :meth:`update_persistence`.

        Warning:
            * Any data stored in :attr:`chat_data` at key :paramref:`new_chat_id` will be
              overridden
            * The key :paramref:`old_chat_id` of :attr:`chat_data` will be deleted
            * This does not update the :attr:`~telegram.ext.Job.chat_id` attribute of any scheduled
              :class:`telegram.ext.Job`.

            When using :attr:`concurrent_updates` or the :attr:`job_queue`,
            :meth:`process_update` or :meth:`telegram.ext.Job.run` may re-create the old entry due
            to the asynchronous nature of these features. Please make sure that your program can
            avoid or handle such situations.

        .. seealso:: :wiki:`Storing Bot, User and Chat Related Data\
            <Storing-bot%2C-user-and-chat-related-data>`

        Args:
            message (:class:`telegram.Message`, optional): A message with either
                :attr:`~telegram.Message.migrate_from_chat_id` or
                :attr:`~telegram.Message.migrate_to_chat_id`.
                Mutually exclusive with passing :paramref:`old_chat_id` and
                :paramref:`new_chat_id`.

                .. seealso::
                    :attr:`telegram.ext.filters.StatusUpdate.MIGRATE`

            old_chat_id (:obj:`int`, optional): The old chat ID.
                Mutually exclusive with passing :paramref:`message`
            new_chat_id (:obj:`int`, optional): The new chat ID.
                Mutually exclusive with passing :paramref:`message`

        Raises:
            ValueError: Raised if the input is invalid.
        """
        if message and (old_chat_id or new_chat_id):
            raise ValueError("Message and chat_id pair are mutually exclusive")
        if not any((message, old_chat_id, new_chat_id)):
            raise ValueError("chat_id pair or message must be passed")

        if message:
            if message.migrate_from_chat_id is None and message.migrate_to_chat_id is None:
                raise ValueError(
                    "Invalid message instance. The message must have either "
                    "`Message.migrate_from_chat_id` or `Message.migrate_to_chat_id`."
                )

            old_chat_id = message.migrate_from_chat_id or message.chat.id
            new_chat_id = message.migrate_to_chat_id or message.chat.id

        elif not (isinstance(old_chat_id, int) and isinstance(new_chat_id, int)):
            raise ValueError("old_chat_id and new_chat_id must be integers")

        self._chat_data[new_chat_id] = self._chat_data[old_chat_id]
        self.drop_chat_data(old_chat_id)

        self._chat_ids_to_be_updated_in_persistence.add(new_chat_id)
        # old_chat_id is marked for deletion by drop_chat_data above

    def _mark_for_persistence_update(
        self, *, update: object | None = None, job: "Job | None" = None
    ) -> None:
        if isinstance(update, Update):
            if update.effective_chat:
                self._chat_ids_to_be_updated_in_persistence.add(update.effective_chat.id)
            if update.effective_user:
                self._user_ids_to_be_updated_in_persistence.add(update.effective_user.id)

        if job:
            if job.chat_id:
                self._chat_ids_to_be_updated_in_persistence.add(job.chat_id)
            if job.user_id:
                self._user_ids_to_be_updated_in_persistence.add(job.user_id)

    def mark_data_for_update_persistence(
        self, chat_ids: SCT[int] | None = None, user_ids: SCT[int] | None = None
    ) -> None:
        """Mark entries of :attr:`chat_data` and :attr:`user_data` to be updated on the next
        run of :meth:`update_persistence`.

        Tip:
            Use this method sparingly. If you have to use this method, it likely means that you
            access and modify ``context.application.chat/user_data[some_id]`` within a callback.
            Note that for data which should be available globally in all handler callbacks
            independent of the chat/user, it is recommended to use :attr:`bot_data` instead.

        .. versionadded:: 20.3

        Args:
            chat_ids (:obj:`int` | Collection[:obj:`int`], optional): Chat IDs to mark.
            user_ids (:obj:`int` | Collection[:obj:`int`], optional): User IDs to mark.

        """
        if chat_ids:
            if isinstance(chat_ids, int):
                self._chat_ids_to_be_updated_in_persistence.add(chat_ids)
            else:
                self._chat_ids_to_be_updated_in_persistence.update(chat_ids)
        if user_ids:
            if isinstance(user_ids, int):
                self._user_ids_to_be_updated_in_persistence.add(user_ids)
            else:
                self._user_ids_to_be_updated_in_persistence.update(user_ids)

    async def _persistence_updater(self) -> None:
        # Update the persistence in regular intervals. Exit only when the stop event has been set
        while not self.__update_persistence_event.is_set():
            if not self.persistence:
                return

            # asyncio synchronization primitives don't accept a timeout argument, it is recommended
            # to use wait_for instead
            try:
                await asyncio.wait_for(
                    self.__update_persistence_event.wait(),
                    timeout=self.persistence.update_interval,
                )
            except asyncio.TimeoutError:
                pass
            else:
                return

            # putting this *after* the wait_for so we don't immediately update on startup as
            # that would make little sense
            await self.update_persistence()

    async def update_persistence(self) -> None:
        """Updates :attr:`user_data`, :attr:`chat_data`, :attr:`bot_data` in :attr:`persistence`
        along with :attr:`~telegram.ext.ExtBot.callback_data_cache` and the conversation states of
        any persistent :class:`~telegram.ext.ConversationHandler` registered for this application.

        For :attr:`user_data` and :attr:`chat_data`, only those entries are updated which either
        were used or have been manually marked via :meth:`mark_data_for_update_persistence` since
        the last run of this method.

        Tip:
            This method will be called in regular intervals by the application. There is usually
            no need to call it manually.

        Note:
            Any data is deep copied with :func:`copy.deepcopy` before handing it over to the
            persistence in order to avoid race conditions, so all persisted data must be copyable.

        .. seealso:: :attr:`telegram.ext.BasePersistence.update_interval`,
            :meth:`mark_data_for_update_persistence`
        """
        async with self.__update_persistence_lock:
            await self.__update_persistence()

    async def __update_persistence(self) -> None:
        if not self.persistence:
            return

        _LOGGER.debug("Starting next run of updating the persistence.")

        coroutines: set[Coroutine] = set()

        # Mypy doesn't know that persistence.set_bot (see above) already checks that
        # self.bot is an instance of ExtBot if callback_data should be stored ...
        if self.persistence.store_data.callback_data and (
            self.bot.callback_data_cache is not None  # type: ignore[attr-defined]
        ):
            coroutines.add(
                self.persistence.update_callback_data(
                    deepcopy(
                        self.bot.callback_data_cache.persistence_data  # type: ignore[attr-defined]
                    )
                )
            )

        if self.persistence.store_data.bot_data:
            coroutines.add(self.persistence.update_bot_data(deepcopy(self.bot_data)))

        if self.persistence.store_data.chat_data:
            update_ids = self._chat_ids_to_be_updated_in_persistence
            self._chat_ids_to_be_updated_in_persistence = set()
            delete_ids = self._chat_ids_to_be_deleted_in_persistence
            self._chat_ids_to_be_deleted_in_persistence = set()

            # We don't want to update any data that has been deleted!
            update_ids -= delete_ids

            for chat_id in update_ids:
                coroutines.add(
                    self.persistence.update_chat_data(chat_id, deepcopy(self.chat_data[chat_id]))
                )
            for chat_id in delete_ids:
                coroutines.add(self.persistence.drop_chat_data(chat_id))

        if self.persistence.store_data.user_data:
            update_ids = self._user_ids_to_be_updated_in_persistence
            self._user_ids_to_be_updated_in_persistence = set()
            delete_ids = self._user_ids_to_be_deleted_in_persistence
            self._user_ids_to_be_deleted_in_persistence = set()

            # We don't want to update any data that has been deleted!
            update_ids -= delete_ids

            for user_id in update_ids:
                coroutines.add(
                    self.persistence.update_user_data(user_id, deepcopy(self.user_data[user_id]))
                )
            for user_id in delete_ids:
                coroutines.add(self.persistence.drop_user_data(user_id))

        # Unfortunately due to circular imports this has to be here
        # pylint: disable=import-outside-toplevel
        from telegram.ext._handlers.conversationhandler import PendingState  # noqa: PLC0415

        for name, (key, new_state) in itertools.chain.from_iterable(
            zip(itertools.repeat(name), states_dict.pop_accessed_write_items())
            for name, states_dict in self._conversation_handler_conversations.items()
        ):
            if isinstance(new_state, PendingState):
                # If the handler was running non-blocking, we check if the new state is already
                # available. Otherwise, we update with the old state, which is the next best
                # guess.
                # Note that when updating the persistence one last time during self.stop(),
                # *all* tasks will be done.
                if not new_state.done():
                    if self.running:
                        _LOGGER.debug(
                            "A ConversationHandlers state was not yet resolved. Updating the "
                            "persistence with the current state. Will check again on next run of "
                            "Application.update_persistence."
                        )
                    else:
                        _LOGGER.warning(
                            "A ConversationHandlers state was not yet resolved. Updating the "
                            "persistence with the current state."
                        )
                    result = new_state.old_state
                    # We need to check again on the next run if the state is done
                    self._conversation_handler_conversations[name].mark_as_accessed(key)
                else:
                    result = new_state.resolve()
            else:
                result = new_state

            effective_new_state = None if result is TrackingDict.DELETED else result
            coroutines.add(
                self.persistence.update_conversation(
                    name=name, key=key, new_state=effective_new_state
                )
            )

        results = await asyncio.gather(*coroutines, return_exceptions=True)
        _LOGGER.debug("Finished updating persistence.")

        # dispatch any errors
        await asyncio.gather(
            *(
                self.process_error(error=result, update=None)
                for result in results
                if isinstance(result, Exception)
            )
        )

    def add_error_handler(
        self,
        callback: HandlerCallback[object, CCT, None],
        block: DVType[bool] = DEFAULT_TRUE,
    ) -> None:
        """Registers an error handler in the Application. This handler will receive every error
        which happens in your bot. See the docs of :meth:`process_error` for more details on how
        errors are handled.

        Note:
            Attempts to add the same callback multiple times will be ignored.

        Examples:
            :any:`Errorhandler Bot <examples.errorhandlerbot>`

        Hint:
            This method currently has no influence on calls to :meth:`process_error` that are
            already in progress.

            .. warning::
                This behavior should currently be considered an implementation detail and not as
                guaranteed behavior.

        .. seealso:: :wiki:`Exceptions, Warnings and Logging <Exceptions%2C-Warnings-and-Logging>`

        Args:
            callback (:term:`coroutine function`): The callback function for this error handler.
                Will be called when an error is raised. Callback signature::

                    async def callback(update: object | None, context: CallbackContext)

                The error that happened will be present in
                :attr:`telegram.ext.CallbackContext.error`.
            block (:obj:`bool`, optional): Determines whether the return value of the callback
                should be awaited before processing the next error handler in
                :meth:`process_error`. Defaults to :obj:`True`.
        """
        if callback in self.error_handlers:
            _LOGGER.warning("The callback is already registered as an error handler. Ignoring.")
            return

        self.error_handlers[callback] = block

    def remove_error_handler(self, callback: HandlerCallback[object, CCT, None]) -> None:
        """Removes an error handler.

        Hint:
            This method currently has no influence on calls to :meth:`process_error` that are
            already in progress.

            .. warning::
                This behavior should currently be considered an implementation detail and not as
                guaranteed behavior.

        Args:
            callback (:term:`coroutine function`): The error handler to remove.

        """
        self.error_handlers.pop(callback, None)

    async def process_error(
        self,
        update: object | None,
        error: Exception,
        job: "Job[CCT] | None" = None,
        coroutine: _ErrorCoroType[RT] | None = None,
    ) -> bool:
        """Processes an error by passing it to all error handlers registered with
        :meth:`add_error_handler`. If one of the error handlers raises
        :class:`telegram.ext.ApplicationHandlerStop`, the error will not be handled by other error
        handlers. Raising :class:`telegram.ext.ApplicationHandlerStop` also stops processing of
        the update when this method is called by :meth:`process_update`, i.e. no further handlers
        (even in other groups) will handle the update. All other exceptions raised by an error
        handler will just be logged.

        .. versionchanged:: 20.0

            * ``dispatch_error`` was renamed to :meth:`process_error`.
            * Exceptions raised by error handlers are now properly logged.
            * :class:`telegram.ext.ApplicationHandlerStop` is no longer reraised but converted into
              the return value.

        Args:
            update (:obj:`object` | :class:`telegram.Update`): The update that caused the error.
            error (:obj:`Exception`): The error that was raised.
            job (:class:`telegram.ext.Job`, optional): The job that caused the error.

                .. versionadded:: 20.0
            coroutine (:term:`coroutine function`, optional): The coroutine that caused the error.

        Returns:
            :obj:`bool`: :obj:`True`, if one of the error handlers raised
            :class:`telegram.ext.ApplicationHandlerStop`. :obj:`False`, otherwise.
        """
        if self.error_handlers:
            # We copy the list to avoid issues with concurrent modification of the
            # error handlers while iterating over it via add/remove_error_handler.
            # Currently considered implementation detail as described in docstrings of
            # add/remove_error_handler
            error_handler_items = list(self.error_handlers.items())
            for callback, block in error_handler_items:
                try:
                    context = self.context_types.context.from_error(
                        update=update,
                        error=error,
                        application=self,
                        job=job,
                        coroutine=coroutine,
                    )
                except Exception as exc:
                    _LOGGER.critical(
                        (
                            "Error while building CallbackContext for exception %s. "
                            "Exception will not be processed by error handlers."
                        ),
                        error,
                        exc_info=exc,
                    )
                    return False

                if not block or (  # If error handler has `block=False`, create a Task to run cb
                    block is DEFAULT_TRUE
                    and isinstance(self.bot, ExtBot)
                    and self.bot.defaults
                    and not self.bot.defaults.block
                ):
                    self.__create_task(
                        callback(update, context),
                        update=update,
                        is_error_handler=True,
                        name=f"Application:{self.bot.id}:process_error:non_blocking",
                    )
                else:
                    try:
                        await callback(update, context)
                    except ApplicationHandlerStop:
                        return True
                    except Exception as exc:
                        _LOGGER.exception(
                            "An error was raised and an uncaught error was raised while "
                            "handling the error with an error_handler.",
                            exc_info=exc,
                        )
            return False

        _LOGGER.exception("No error handlers are registered, logging exception.", exc_info=error)
        return False
