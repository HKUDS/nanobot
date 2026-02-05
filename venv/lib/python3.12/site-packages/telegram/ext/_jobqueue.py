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
"""This module contains the classes JobQueue and Job."""

import asyncio
import datetime as dtm
import re
import weakref
from typing import TYPE_CHECKING, Any, Generic, cast, overload

try:
    from apscheduler.executors.asyncio import AsyncIOExecutor
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    APS_AVAILABLE = True
except ImportError:
    APS_AVAILABLE = False

from telegram._utils.datetime import UTC, localize
from telegram._utils.logging import get_logger
from telegram._utils.repr import build_repr_with_selected_attrs
from telegram._utils.types import JSONDict
from telegram.ext._extbot import ExtBot
from telegram.ext._utils.types import CCT, JobCallback

if TYPE_CHECKING:
    from collections.abc import Iterable

    if APS_AVAILABLE:
        from apscheduler.job import Job as APSJob

    from telegram.ext import Application


_ALL_DAYS = tuple(range(7))
_LOGGER = get_logger(__name__, class_name="JobQueue")


def _get_callback_name(callback: object) -> str:
    """Get the name of a callback function or callable object.

    Args:
        callback: A callable object (function, method, or callable class instance)

    Returns:
        The name of the callback, using __name__ if available, otherwise the class name.
    """
    return getattr(callback, "__name__", None) or callback.__class__.__name__


class JobQueue(Generic[CCT]):
    """This class allows you to periodically perform tasks with the bot. It is a convenience
    wrapper for the APScheduler library.

    This class is a :class:`~typing.Generic` class and accepts one type variable that specifies
    the type of the argument ``context`` of the job callbacks (:paramref:`~run_once.callback`) of
    :meth:`run_once` and the other scheduling methods.

    Important:
        If you want to use this class, you must install PTB with the optional requirement
        ``job-queue``, i.e.

        .. code-block:: bash

           pip install "python-telegram-bot[job-queue]"

    Examples:
        :any:`Timer Bot <examples.timerbot>`

    .. seealso:: :wiki:`Architecture Overview <Architecture>`,
        :wiki:`Job Queue <Extensions---JobQueue>`

    .. versionchanged:: 20.0
        To use this class, PTB must be installed via
        ``pip install "python-telegram-bot[job-queue]"``.

    Attributes:
        scheduler (:class:`apscheduler.schedulers.asyncio.AsyncIOScheduler`): The scheduler.

            Warning:
                This scheduler is configured by :meth:`set_application`. Additional configuration
                settings can be made by users. However, calling
                :meth:`~apscheduler.schedulers.base.BaseScheduler.configure` will delete any
                previous configuration settings. Therefore, please make sure to pass the values
                returned by :attr:`scheduler_configuration` to the method call in addition to your
                custom values.
                Alternatively, you can also use methods like
                :meth:`~apscheduler.schedulers.base.BaseScheduler.add_jobstore` to avoid using
                :meth:`~apscheduler.schedulers.base.BaseScheduler.configure` altogether.

            .. versionchanged:: 20.0
                Uses :class:`~apscheduler.schedulers.asyncio.AsyncIOScheduler` instead of
                :class:`~apscheduler.schedulers.background.BackgroundScheduler`

    """

    __slots__ = ("_application", "_executor", "scheduler")
    _CRON_MAPPING = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

    def __init__(self) -> None:
        if not APS_AVAILABLE:
            raise RuntimeError(
                "To use `JobQueue`, PTB must be installed via `pip install "
                '"python-telegram-bot[job-queue]"`.'
            )

        self._application: weakref.ReferenceType[Application] | None = None
        self._executor = AsyncIOExecutor()
        self.scheduler: "AsyncIOScheduler" = AsyncIOScheduler(  # noqa: UP037
            **self.scheduler_configuration
        )

    def __repr__(self) -> str:
        """Give a string representation of the JobQueue in the form ``JobQueue[application=...]``.

        As this class doesn't implement :meth:`object.__str__`, the default implementation
        will be used, which is equivalent to :meth:`__repr__`.

        Returns:
            :obj:`str`
        """
        return build_repr_with_selected_attrs(self, application=self.application)

    @property
    def application(self) -> "Application[Any, CCT, Any, Any, Any, JobQueue[CCT]]":
        """The application this JobQueue is associated with."""
        if self._application is None:
            raise RuntimeError("No application was set for this JobQueue.")
        application = self._application()
        if application is not None:
            return application
        raise RuntimeError("The application instance is no longer alive.")

    @property
    def scheduler_configuration(self) -> JSONDict:
        """Provides configuration values that are used by :class:`JobQueue` for :attr:`scheduler`.

        Tip:
            Since calling
            :meth:`scheduler.configure() <apscheduler.schedulers.base.BaseScheduler.configure>`
            deletes any previous setting, please make sure to pass these values to the method call
            in addition to your custom values:

            .. code-block:: python

                scheduler.configure(..., **job_queue.scheduler_configuration)

            Alternatively, you can also use methods like
            :meth:`~apscheduler.schedulers.base.BaseScheduler.add_jobstore` to avoid using
            :meth:`~apscheduler.schedulers.base.BaseScheduler.configure` altogether.

        .. versionadded:: 20.7

        Returns:
            dict[:obj:`str`, :obj:`object`]: The configuration values as dictionary.

        """
        timezone: dtm.tzinfo = UTC
        if (
            self._application
            and isinstance(self.application.bot, ExtBot)
            and self.application.bot.defaults
        ):
            timezone = self.application.bot.defaults.tzinfo or UTC

        return {
            "timezone": timezone,
            "executors": {"default": self._executor},
        }

    def _tz_now(self) -> dtm.datetime:
        return dtm.datetime.now(self.scheduler.timezone)

    @overload
    def _parse_time_input(self, time: None, shift_day: bool = False) -> None: ...

    @overload
    def _parse_time_input(
        self,
        time: float | dtm.timedelta | dtm.datetime | dtm.time,
        shift_day: bool = False,
    ) -> dtm.datetime: ...

    def _parse_time_input(
        self,
        time: float | dtm.timedelta | dtm.datetime | dtm.time | None,
        shift_day: bool = False,
    ) -> dtm.datetime | None:
        if time is None:
            return None
        if isinstance(time, int | float):
            return self._tz_now() + dtm.timedelta(seconds=time)
        if isinstance(time, dtm.timedelta):
            return self._tz_now() + time
        if isinstance(time, dtm.time):
            date_time = dtm.datetime.combine(
                dtm.datetime.now(tz=time.tzinfo or self.scheduler.timezone).date(), time
            )
            if date_time.tzinfo is None:
                # dtm.combine uses the tzinfo of `time`, which might be None, so we still have
                # to localize it
                date_time = localize(date_time, self.scheduler.timezone)
            if shift_day and date_time <= dtm.datetime.now(UTC):
                date_time += dtm.timedelta(days=1)
            return date_time
        return time

    def set_application(
        self, application: "Application[Any, CCT, Any, Any, Any, JobQueue[CCT]]"
    ) -> None:
        """Set the application to be used by this JobQueue.

        Args:
            application (:class:`telegram.ext.Application`): The application.

        """
        self._application = weakref.ref(application)
        self.scheduler.configure(**self.scheduler_configuration)

    @staticmethod
    async def job_callback(job_queue: "JobQueue[CCT]", job: "Job[CCT]") -> None:
        """This method is used as a callback for the APScheduler jobs.

        More precisely, the ``func`` argument of :class:`apscheduler.job.Job` is set to this method
        and the ``arg`` argument (representing positional arguments to ``func``) is set to a tuple
        containing the :class:`JobQueue` itself and the :class:`~telegram.ext.Job` instance.

        Tip:
            This method is a static method rather than a bound method. This makes the arguments
            more transparent and allows for easier handling of PTBs integration of APScheduler
            when utilizing advanced features of APScheduler.

        Hint:
            This method is effectively a wrapper for :meth:`telegram.ext.Job.run`.

        .. versionadded:: 20.4

        Args:
            job_queue (:class:`JobQueue`): The job queue that created the job.
            job (:class:`~telegram.ext.Job`): The job to run.
        """
        await job.run(job_queue.application)

    def run_once(
        self,
        callback: JobCallback[CCT],
        when: float | dtm.timedelta | dtm.datetime | dtm.time,
        data: object | None = None,
        name: str | None = None,
        chat_id: int | None = None,
        user_id: int | None = None,
        job_kwargs: JSONDict | None = None,
    ) -> "Job[CCT]":
        """Creates a new :class:`Job` instance that runs once and adds it to the queue.

        Args:
            callback (:term:`coroutine function`): The callback function that should be executed by
                the new job. Callback signature::

                    async def callback(context: CallbackContext)

            when (:obj:`int` | :obj:`float` | :obj:`datetime.timedelta` |                         \
                  :obj:`datetime.datetime` | :obj:`datetime.time`):
                Time in or at which the job should run. This parameter will be interpreted
                depending on its type.

                * :obj:`int` or :obj:`float` will be interpreted as "seconds from now" in which the
                  job should run.
                * :obj:`datetime.timedelta` will be interpreted as "time from now" in which the
                  job should run.
                * :obj:`datetime.datetime` will be interpreted as a specific date and time at
                  which the job should run. If the timezone (:attr:`datetime.datetime.tzinfo`) is
                  :obj:`None`, the default timezone of the bot will be used, which is UTC unless
                  :attr:`telegram.ext.Defaults.tzinfo` is used.
                * :obj:`datetime.time` will be interpreted as a specific time of day at which the
                  job should run. This could be either today or, if the time has already passed,
                  tomorrow. If the timezone (:attr:`datetime.time.tzinfo`) is :obj:`None`, the
                  default timezone of the bot will be used, which is UTC unless
                  :attr:`telegram.ext.Defaults.tzinfo` is used.

            chat_id (:obj:`int`, optional): Chat id of the chat associated with this job. If
                passed, the corresponding :attr:`~telegram.ext.CallbackContext.chat_data` will
                be available in the callback.

                .. versionadded:: 20.0

            user_id (:obj:`int`, optional): User id of the user associated with this job. If
                passed, the corresponding :attr:`~telegram.ext.CallbackContext.user_data` will
                be available in the callback.

                .. versionadded:: 20.0
            data (:obj:`object`, optional): Additional data needed for the callback function.
                Can be accessed through :attr:`Job.data` in the callback. Defaults to
                :obj:`None`.

                .. versionchanged:: 20.0
                    Renamed the parameter ``context`` to :paramref:`data`.
            name (:obj:`str`, optional): The name of the new job. Defaults to
                :external:attr:`callback.__name__ <definition.__name__>`.
            job_kwargs (:obj:`dict`, optional): Arbitrary keyword arguments to pass to the
                :meth:`apscheduler.schedulers.base.BaseScheduler.add_job()`.

        Returns:
            :class:`telegram.ext.Job`: The new :class:`Job` instance that has been added to the job
            queue.

        """
        if not job_kwargs:
            job_kwargs = {}

        name = name or _get_callback_name(callback)
        job = Job(callback=callback, data=data, name=name, chat_id=chat_id, user_id=user_id)
        date_time = self._parse_time_input(when, shift_day=True)

        j = self.scheduler.add_job(
            self.job_callback,
            name=name,
            trigger="date",
            run_date=date_time,
            args=(self, job),
            timezone=date_time.tzinfo or self.scheduler.timezone,
            **job_kwargs,
        )

        job._job = j  # pylint: disable=protected-access
        return job

    def run_repeating(
        self,
        callback: JobCallback[CCT],
        interval: float | dtm.timedelta,
        first: float | dtm.timedelta | dtm.datetime | dtm.time | None = None,
        last: float | dtm.timedelta | dtm.datetime | dtm.time | None = None,
        data: object | None = None,
        name: str | None = None,
        chat_id: int | None = None,
        user_id: int | None = None,
        job_kwargs: JSONDict | None = None,
    ) -> "Job[CCT]":
        """Creates a new :class:`Job` instance that runs at specified intervals and adds it to the
        queue.

        Note:
            For a note about DST, please see the documentation of `APScheduler`_.

        .. _`APScheduler`: https://apscheduler.readthedocs.io/en/stable/modules/triggers/cron.html
                           #daylight-saving-time-behavior

        Args:
            callback (:term:`coroutine function`): The callback function that should be executed by
                the new job. Callback signature::

                    async def callback(context: CallbackContext)

            interval (:obj:`int` | :obj:`float` | :obj:`datetime.timedelta`): The interval in which
                the job will run. If it is an :obj:`int` or a :obj:`float`, it will be interpreted
                as seconds.
            first (:obj:`int` | :obj:`float` | :obj:`datetime.timedelta` |                        \
                   :obj:`datetime.datetime` | :obj:`datetime.time`, optional):
                Time in or at which the job should run. This parameter will be interpreted
                depending on its type.

                * :obj:`int` or :obj:`float` will be interpreted as "seconds from now" in which the
                  job should run.
                * :obj:`datetime.timedelta` will be interpreted as "time from now" in which the
                  job should run.
                * :obj:`datetime.datetime` will be interpreted as a specific date and time at
                  which the job should run. If the timezone (:attr:`datetime.datetime.tzinfo`) is
                  :obj:`None`, the default timezone of the bot will be used.
                * :obj:`datetime.time` will be interpreted as a specific time of day at which the
                  job should run. This could be either today or, if the time has already passed,
                  tomorrow. If the timezone (:attr:`datetime.time.tzinfo`) is :obj:`None`, the
                  default timezone of the bot will be used, which is UTC unless
                  :attr:`telegram.ext.Defaults.tzinfo` is used.

                Defaults to :paramref:`interval`

                Note:
                    Setting :paramref:`first` to ``0``, ``datetime.datetime.now()`` or another
                    value that indicates that the job should run immediately will not work due
                    to how the APScheduler library works. If you want to run a job immediately,
                    we recommend to use an approach along the lines of::

                        job = context.job_queue.run_repeating(callback, interval=5)
                        await job.run(context.application)

                    .. seealso:: :meth:`telegram.ext.Job.run`

            last (:obj:`int` | :obj:`float` | :obj:`datetime.timedelta` |                        \
                   :obj:`datetime.datetime` | :obj:`datetime.time`, optional):
                Latest possible time for the job to run. This parameter will be interpreted
                depending on its type. See :paramref:`first` for details.

                If :paramref:`last` is :obj:`datetime.datetime` or :obj:`datetime.time` type
                and ``last.tzinfo`` is :obj:`None`, the default timezone of the bot will be
                assumed, which is UTC unless :attr:`telegram.ext.Defaults.tzinfo` is used.

                Defaults to :obj:`None`.
            data (:obj:`object`, optional): Additional data needed for the callback function.
                Can be accessed through :attr:`Job.data` in the callback. Defaults to
                :obj:`None`.

                .. versionchanged:: 20.0
                    Renamed the parameter ``context`` to :paramref:`data`.
            name (:obj:`str`, optional): The name of the new job. Defaults to
                :external:attr:`callback.__name__ <definition.__name__>`.
            chat_id (:obj:`int`, optional): Chat id of the chat associated with this job. If
                passed, the corresponding :attr:`~telegram.ext.CallbackContext.chat_data` will
                be available in the callback.

                .. versionadded:: 20.0

            user_id (:obj:`int`, optional): User id of the user associated with this job. If
                passed, the corresponding :attr:`~telegram.ext.CallbackContext.user_data` will
                be available in the callback.

                .. versionadded:: 20.0
            job_kwargs (:obj:`dict`, optional): Arbitrary keyword arguments to pass to the
                :meth:`apscheduler.schedulers.base.BaseScheduler.add_job()`.

        Returns:
            :class:`telegram.ext.Job`: The new :class:`Job` instance that has been added to the job
            queue.

        """
        if not job_kwargs:
            job_kwargs = {}

        name = name or _get_callback_name(callback)
        job = Job(callback=callback, data=data, name=name, chat_id=chat_id, user_id=user_id)

        dt_first = self._parse_time_input(first)
        dt_last = self._parse_time_input(last)

        if dt_last and dt_first and dt_last < dt_first:
            raise ValueError("'last' must not be before 'first'!")

        if isinstance(interval, dtm.timedelta):
            interval = interval.total_seconds()

        j = self.scheduler.add_job(
            self.job_callback,
            trigger="interval",
            args=(self, job),
            start_date=dt_first,
            end_date=dt_last,
            seconds=interval,
            name=name,
            **job_kwargs,
        )

        job._job = j  # pylint: disable=protected-access
        return job

    def run_monthly(
        self,
        callback: JobCallback[CCT],
        when: dtm.time,
        day: int,
        data: object | None = None,
        name: str | None = None,
        chat_id: int | None = None,
        user_id: int | None = None,
        job_kwargs: JSONDict | None = None,
    ) -> "Job[CCT]":
        """Creates a new :class:`Job` that runs on a monthly basis and adds it to the queue.

        .. versionchanged:: 20.0
            The ``day_is_strict`` argument was removed. Instead one can now pass ``-1`` to the
            :paramref:`day` parameter to have the job run on the last day of the month.

        Args:
            callback (:term:`coroutine function`): The callback function that should be executed by
                the new job. Callback signature::

                    async def callback(context: CallbackContext)

            when (:obj:`datetime.time`): Time of day at which the job should run. If the timezone
                (``when.tzinfo``) is :obj:`None`, the default timezone of the bot will be used,
                which is UTC unless :attr:`telegram.ext.Defaults.tzinfo` is used.
            day (:obj:`int`): Defines the day of the month whereby the job would run. It should
                be within the range of ``1`` and ``31``, inclusive. If a month has fewer days than
                this number, the job will not run in this month. Passing ``-1`` leads to the job
                running on the last day of the month.
            data (:obj:`object`, optional): Additional data needed for the callback function.
                Can be accessed through :attr:`Job.data` in the callback. Defaults to
                :obj:`None`.

                .. versionchanged:: 20.0
                    Renamed the parameter ``context`` to :paramref:`data`.
            name (:obj:`str`, optional): The name of the new job. Defaults to
                :external:attr:`callback.__name__ <definition.__name__>`.
            chat_id (:obj:`int`, optional): Chat id of the chat associated with this job. If
                passed, the corresponding :attr:`~telegram.ext.CallbackContext.chat_data` will
                be available in the callback.

                .. versionadded:: 20.0

            user_id (:obj:`int`, optional): User id of the user associated with this job. If
                passed, the corresponding :attr:`~telegram.ext.CallbackContext.user_data` will
                be available in the callback.

                .. versionadded:: 20.0
            job_kwargs (:obj:`dict`, optional): Arbitrary keyword arguments to pass to the
                :meth:`apscheduler.schedulers.base.BaseScheduler.add_job()`.

        Returns:
            :class:`telegram.ext.Job`: The new :class:`Job` instance that has been added to the job
            queue.

        """
        if not job_kwargs:
            job_kwargs = {}

        name = name or _get_callback_name(callback)
        job = Job(callback=callback, data=data, name=name, chat_id=chat_id, user_id=user_id)

        j = self.scheduler.add_job(
            self.job_callback,
            trigger="cron",
            args=(self, job),
            name=name,
            day="last" if day == -1 else day,
            hour=when.hour,
            minute=when.minute,
            second=when.second,
            timezone=when.tzinfo or self.scheduler.timezone,
            **job_kwargs,
        )
        job._job = j  # pylint: disable=protected-access
        return job

    def run_daily(
        self,
        callback: JobCallback[CCT],
        time: dtm.time,
        days: tuple[int, ...] = _ALL_DAYS,
        data: object | None = None,
        name: str | None = None,
        chat_id: int | None = None,
        user_id: int | None = None,
        job_kwargs: JSONDict | None = None,
    ) -> "Job[CCT]":
        """Creates a new :class:`Job` that runs on a daily basis and adds it to the queue.

        Note:
            For a note about DST, please see the documentation of `APScheduler`_.

        .. _`APScheduler`: https://apscheduler.readthedocs.io/en/stable/modules/triggers/cron.html
                           #daylight-saving-time-behavior

        Args:
            callback (:term:`coroutine function`): The callback function that should be executed by
                the new job. Callback signature::

                    async def callback(context: CallbackContext)

            time (:obj:`datetime.time`): Time of day at which the job should run. If the timezone
                (:obj:`datetime.time.tzinfo`) is :obj:`None`, the default timezone of the bot will
                be used, which is UTC unless :attr:`telegram.ext.Defaults.tzinfo` is used.
            days (tuple[:obj:`int`], optional): Defines on which days of the week the job should
                run (where ``0-6`` correspond to sunday - saturday). By default, the job will run
                every day.

                .. versionchanged:: 20.0
                    Changed day of the week mapping of 0-6 from monday-sunday to sunday-saturday.

            data (:obj:`object`, optional): Additional data needed for the callback function.
                Can be accessed through :attr:`Job.data` in the callback. Defaults to
                :obj:`None`.

                .. versionchanged:: 20.0
                    Renamed the parameter ``context`` to :paramref:`data`.
            name (:obj:`str`, optional): The name of the new job. Defaults to
                :external:attr:`callback.__name__ <definition.__name__>`.
            chat_id (:obj:`int`, optional): Chat id of the chat associated with this job. If
                passed, the corresponding :attr:`~telegram.ext.CallbackContext.chat_data` will
                be available in the callback.

                .. versionadded:: 20.0

            user_id (:obj:`int`, optional): User id of the user associated with this job. If
                passed, the corresponding :attr:`~telegram.ext.CallbackContext.user_data` will
                be available in the callback.

                .. versionadded:: 20.0
            job_kwargs (:obj:`dict`, optional): Arbitrary keyword arguments to pass to the
                :meth:`apscheduler.schedulers.base.BaseScheduler.add_job()`.

        Returns:
            :class:`telegram.ext.Job`: The new :class:`Job` instance that has been added to the job
            queue.

        """
        if not job_kwargs:
            job_kwargs = {}

        name = name or _get_callback_name(callback)
        job = Job(callback=callback, data=data, name=name, chat_id=chat_id, user_id=user_id)

        j = self.scheduler.add_job(
            self.job_callback,
            name=name,
            args=(self, job),
            trigger="cron",
            day_of_week=",".join([self._CRON_MAPPING[d] for d in days]),
            hour=time.hour,
            minute=time.minute,
            second=time.second,
            timezone=time.tzinfo or self.scheduler.timezone,
            **job_kwargs,
        )

        job._job = j  # pylint: disable=protected-access
        return job

    def run_custom(
        self,
        callback: JobCallback[CCT],
        job_kwargs: JSONDict,
        data: object | None = None,
        name: str | None = None,
        chat_id: int | None = None,
        user_id: int | None = None,
    ) -> "Job[CCT]":
        """Creates a new custom defined :class:`Job`.

        Args:
            callback (:term:`coroutine function`): The callback function that should be executed by
                the new job. Callback signature::

                    async def callback(context: CallbackContext)

            job_kwargs (:obj:`dict`): Arbitrary keyword arguments. Used as arguments for
                :meth:`apscheduler.schedulers.base.BaseScheduler.add_job`.
            data (:obj:`object`, optional): Additional data needed for the callback function.
                Can be accessed through :attr:`Job.data` in the callback. Defaults to
                :obj:`None`.

                .. versionchanged:: 20.0
                    Renamed the parameter ``context`` to :paramref:`data`.
            name (:obj:`str`, optional): The name of the new job. Defaults to
                :external:attr:`callback.__name__ <definition.__name__>`.
            chat_id (:obj:`int`, optional): Chat id of the chat associated with this job. If
                passed, the corresponding :attr:`~telegram.ext.CallbackContext.chat_data` will
                be available in the callback.

                .. versionadded:: 20.0

            user_id (:obj:`int`, optional): User id of the user associated with this job. If
                passed, the corresponding :attr:`~telegram.ext.CallbackContext.user_data` will
                be available in the callback.

                .. versionadded:: 20.0

        Returns:
            :class:`telegram.ext.Job`: The new :class:`Job` instance that has been added to the job
            queue.

        """
        name = name or _get_callback_name(callback)
        job = Job(callback=callback, data=data, name=name, chat_id=chat_id, user_id=user_id)

        j = self.scheduler.add_job(self.job_callback, args=(self, job), name=name, **job_kwargs)

        job._job = j  # pylint: disable=protected-access
        return job

    async def start(self) -> None:
        # this method async just in case future versions need that
        """Starts the :class:`~telegram.ext.JobQueue`."""
        if not self.scheduler.running:
            self.scheduler.start()

    async def stop(self, wait: bool = True) -> None:
        """Shuts down the :class:`~telegram.ext.JobQueue`.

        Args:
            wait (:obj:`bool`, optional): Whether to wait until all currently running jobs
                have finished. Defaults to :obj:`True`.

        """
        # the interface methods of AsyncIOExecutor are currently not really asyncio-compatible
        # so we apply some small tweaks here to try and smoothen the integration into PTB
        # TODO: When APS 4.0 hits, we should be able to remove the tweaks
        if wait:
            # Unfortunately AsyncIOExecutor just cancels them all ...
            await asyncio.gather(
                *self._executor._pending_futures,  # pylint: disable=protected-access
                return_exceptions=True,
            )
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            # scheduler.shutdown schedules a task in the event loop but immediately returns
            # so give it a tiny bit of time to actually shut down.
            await asyncio.sleep(0.01)

    def jobs(self, pattern: str | re.Pattern[str] | None = None) -> tuple["Job[CCT]", ...]:
        """Returns a tuple of all *scheduled* jobs that are currently in the :class:`JobQueue`.

        Args:
            pattern (:obj:`str` | :obj:`re.Pattern`, optional): A regular expression pattern. If
                passed, only jobs whose name matches the pattern will be returned.
                Defaults to :obj:`None`.

                Hint:
                    This uses :func:`re.search` and not :func:`re.match`.

                .. versionadded:: 21.10

        Returns:
            tuple[:class:`Job`]: Tuple of all *scheduled* jobs.
        """
        jobs_generator: Iterable[Job] = (
            Job.from_aps_job(job) for job in self.scheduler.get_jobs()
        )
        if pattern is None:
            return tuple(jobs_generator)
        return tuple(
            job for job in jobs_generator if (job.name and re.compile(pattern).search(job.name))
        )

    def get_jobs_by_name(self, name: str) -> tuple["Job[CCT]", ...]:
        """Returns a tuple of all *scheduled* jobs with the given name that are currently
        in the :class:`JobQueue`.

        Hint:
            This method is a convenience wrapper for :meth:`jobs` with a pattern that matches the
            given name.

        Returns:
            tuple[:class:`Job`]: Tuple of all *scheduled* jobs matching the name.
        """
        return self.jobs(f"^{re.escape(name)}$")


class Job(Generic[CCT]):
    """This class is a convenience wrapper for the jobs held in a :class:`telegram.ext.JobQueue`.
    With the current backend APScheduler, :attr:`job` holds a :class:`apscheduler.job.Job`
    instance.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :class:`id <apscheduler.job.Job>` is equal.

    This class is a :class:`~typing.Generic` class and accepts one type variable that specifies
    the type of the argument ``context`` of :paramref:`callback`.

    Important:
        If you want to use this class, you must install PTB with the optional requirement
        ``job-queue``, i.e.

        .. code-block:: bash

           pip install "python-telegram-bot[job-queue]"

    Note:
        All attributes and instance methods of :attr:`job` are also directly available as
        attributes/methods of the corresponding :class:`telegram.ext.Job` object.

    Warning:
        This class should not be instantiated manually.
        Use the methods of :class:`telegram.ext.JobQueue` to schedule jobs.

    .. seealso:: :wiki:`Job Queue <Extensions---JobQueue>`

    .. versionchanged:: 20.0

       * Removed argument and attribute ``job_queue``.
       * Renamed ``Job.context`` to :attr:`Job.data`.
       * Removed argument ``job``
       * To use this class, PTB must be installed via
         ``pip install "python-telegram-bot[job-queue]"``.

    Args:
        callback (:term:`coroutine function`): The callback function that should be executed by the
            new job. Callback signature::

                async def callback(context: CallbackContext)

        data (:obj:`object`, optional): Additional data needed for the :paramref:`callback`
            function. Can be accessed through :attr:`Job.data` in the callback. Defaults to
            :obj:`None`.
        name (:obj:`str`, optional): The name of the new job. Defaults to
            :external:obj:`callback.__name__ <definition.__name__>`.
        chat_id (:obj:`int`, optional): Chat id of the chat that this job is associated with.

            .. versionadded:: 20.0
        user_id (:obj:`int`, optional): User id of the user that this job is associated with.

            .. versionadded:: 20.0
    Attributes:
        callback (:term:`coroutine function`): The callback function that should be executed by the
            new job.
        data (:obj:`object`): Optional. Additional data needed for the :attr:`callback` function.
        name (:obj:`str`): Optional. The name of the new job.
        chat_id (:obj:`int`): Optional. Chat id of the chat that this job is associated with.

            .. versionadded:: 20.0
        user_id (:obj:`int`): Optional. User id of the user that this job is associated with.

            .. versionadded:: 20.0
    """

    __slots__ = (
        "_enabled",
        "_job",
        "_removed",
        "callback",
        "chat_id",
        "data",
        "name",
        "user_id",
    )

    def __init__(
        self,
        callback: JobCallback[CCT],
        data: object | None = None,
        name: str | None = None,
        chat_id: int | None = None,
        user_id: int | None = None,
    ):
        if not APS_AVAILABLE:
            raise RuntimeError(
                "To use `Job`, PTB must be installed via `pip install "
                '"python-telegram-bot[job-queue]"`.'
            )

        self.callback: JobCallback[CCT] = callback
        self.data: object | None = data
        self.name: str | None = name or _get_callback_name(callback)
        self.chat_id: int | None = chat_id
        self.user_id: int | None = user_id

        self._removed = False
        self._enabled = False

        self._job = cast("APSJob", None)

    def __getattr__(self, item: str) -> object:
        """Overrides :py:meth:`object.__getattr__` to get specific attribute of the
        :class:`telegram.ext.Job` object or of its attribute :class:`apscheduler.job.Job`,
        if exists.

        Args:
           item (:obj:`str`): The name of the attribute.

        Returns:
            :object: The value of the attribute.

        Raises:
            :exc:`AttributeError`: If the attribute does not exist in both
                :class:`telegram.ext.Job` and :class:`apscheduler.job.Job` objects.
        """
        try:
            return getattr(self.job, item)
        except AttributeError as exc:
            raise AttributeError(
                f"Neither 'telegram.ext.Job' nor 'apscheduler.job.Job' has attribute '{item}'"
            ) from exc

    def __eq__(self, other: object) -> bool:
        """Defines equality condition for the :class:`telegram.ext.Job` object.
        Two objects of this class are considered to be equal if their
        :class:`id <apscheduler.job.Job>` are equal.

        Returns:
            :obj:`True` if both objects have :paramref:`id` parameters identical.
            :obj:`False` otherwise.
        """
        if isinstance(other, self.__class__):
            return self.id == other.id
        return False

    def __hash__(self) -> int:
        """Builds a hash value for this object such that the hash of two objects is
        equal if and only if the objects are equal in terms of :meth:`__eq__`.

        Returns:
            :obj:`int`: The hash value of the object.
        """
        return hash(self.id)

    def __repr__(self) -> str:
        """Give a string representation of the job in the form
        ``Job[id=..., name=..., callback=..., trigger=...]``.

        As this class doesn't implement :meth:`object.__str__`, the default implementation
        will be used, which is equivalent to :meth:`__repr__`.

        Returns:
            :obj:`str`
        """
        return build_repr_with_selected_attrs(
            self,
            id=self.job.id,
            name=self.name,
            callback=_get_callback_name(self.callback),
            trigger=self.job.trigger,
        )

    @property
    def job(self) -> "APSJob":
        """:class:`apscheduler.job.Job`: The APS Job this job is a wrapper for.

        .. versionchanged:: 20.0
            This property is now read-only.
        """
        return self._job

    @property
    def removed(self) -> bool:
        """:obj:`bool`: Whether this job is due to be removed."""
        return self._removed

    @property
    def enabled(self) -> bool:
        """:obj:`bool`: Whether this job is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, status: bool) -> None:
        if status:
            self.job.resume()
        else:
            self.job.pause()
        self._enabled = status

    @property
    def next_t(self) -> dtm.datetime | None:
        """
        :class:`datetime.datetime`: Datetime for the next job execution.
        Datetime is localized according to :attr:`datetime.datetime.tzinfo`.
        If job is removed or already ran it equals to :obj:`None`.

        Warning:
            This attribute is only available, if the :class:`telegram.ext.JobQueue` this job
            belongs to is already started. Otherwise APScheduler raises an :exc:`AttributeError`.
        """
        return self.job.next_run_time

    @classmethod
    def from_aps_job(cls, aps_job: "APSJob") -> "Job[CCT]":
        """Provides the :class:`telegram.ext.Job` that is associated with the given APScheduler
        job.

        Tip:
            This method can be useful when using advanced APScheduler features along with
            :class:`telegram.ext.JobQueue`.

        .. versionadded:: 20.4

        Args:
            aps_job (:class:`apscheduler.job.Job`): The APScheduler job

        Returns:
            :class:`telegram.ext.Job`
        """
        ext_job = aps_job.args[1]
        ext_job._job = aps_job  # pylint: disable=protected-access
        return ext_job

    async def run(
        self, application: "Application[Any, CCT, Any, Any, Any, JobQueue[CCT]]"
    ) -> None:
        """Executes the callback function independently of the jobs schedule. Also calls
        :meth:`telegram.ext.Application.update_persistence`.

        .. versionchanged:: 20.0
            Calls :meth:`telegram.ext.Application.update_persistence`.

        Args:
            application (:class:`telegram.ext.Application`): The application this job is associated
                with.
        """
        # We shield the task such that the job isn't cancelled mid-run
        await asyncio.shield(self._run(application))

    async def _run(
        self, application: "Application[Any, CCT, Any, Any, Any, JobQueue[CCT]]"
    ) -> None:
        try:
            try:
                context = application.context_types.context.from_job(self, application)
            except Exception as exc:
                _LOGGER.critical(
                    "Error while building CallbackContext for job %s. Job will not be run.",
                    self._job,
                    exc_info=exc,
                )
                return

            await context.refresh_data()
            await self.callback(context)
        except Exception as exc:
            await application.create_task(
                application.process_error(None, exc, job=self),
                name=f"Job:{self.id}:run:process_error",
            )
        finally:
            # This is internal logic of application - let's keep it private for now
            application._mark_for_persistence_update(job=self)  # pylint: disable=protected-access

    def schedule_removal(self) -> None:
        """
        Schedules this job for removal from the :class:`JobQueue`. It will be removed without
        executing its callback function again.
        """
        self.job.remove()
        self._removed = True
