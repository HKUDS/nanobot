import random
from datetime import datetime, timedelta
from math import ceil

from tzlocal import get_localzone

from apscheduler.triggers.base import BaseTrigger
from apscheduler.util import (
    astimezone,
    convert_to_datetime,
    datetime_repr,
)


class IntervalTrigger(BaseTrigger):
    """
    Triggers on specified intervals, starting on ``start_date`` if specified, ``datetime.now()`` +
    interval otherwise.

    :param int weeks: number of weeks to wait
    :param int days: number of days to wait
    :param int hours: number of hours to wait
    :param int minutes: number of minutes to wait
    :param int seconds: number of seconds to wait
    :param datetime|str start_date: starting point for the interval calculation
    :param datetime|str end_date: latest possible date/time to trigger on
    :param datetime.tzinfo|str timezone: time zone to use for the date/time calculations
    :param int|None jitter: delay the job execution by ``jitter`` seconds at most
    """

    __slots__ = (
        "end_date",
        "interval",
        "interval_length",
        "jitter",
        "start_date",
        "timezone",
    )

    def __init__(
        self,
        weeks=0,
        days=0,
        hours=0,
        minutes=0,
        seconds=0,
        start_date=None,
        end_date=None,
        timezone=None,
        jitter=None,
    ):
        self.interval = timedelta(
            weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds
        )
        self.interval_length = self.interval.total_seconds()
        if self.interval_length == 0:
            self.interval = timedelta(seconds=1)
            self.interval_length = 1

        if timezone:
            self.timezone = astimezone(timezone)
        elif isinstance(start_date, datetime) and start_date.tzinfo:
            self.timezone = astimezone(start_date.tzinfo)
        elif isinstance(end_date, datetime) and end_date.tzinfo:
            self.timezone = astimezone(end_date.tzinfo)
        else:
            self.timezone = get_localzone()

        start_date = start_date or (datetime.now(self.timezone) + self.interval)
        self.start_date = convert_to_datetime(start_date, self.timezone, "start_date")
        self.end_date = convert_to_datetime(end_date, self.timezone, "end_date")

        self.jitter = jitter

    def get_next_fire_time(self, previous_fire_time, now):
        if previous_fire_time:
            next_fire_time = previous_fire_time.timestamp() + self.interval_length
        elif self.start_date > now:
            next_fire_time = self.start_date.timestamp()
        else:
            timediff = now.timestamp() - self.start_date.timestamp()
            next_interval_num = ceil(timediff / self.interval_length)
            next_fire_time = (
                self.start_date.timestamp() + self.interval_length * next_interval_num
            )

        if self.jitter is not None:
            next_fire_time += random.uniform(0, self.jitter)

        if not self.end_date or next_fire_time <= self.end_date.timestamp():
            return datetime.fromtimestamp(next_fire_time, tz=self.timezone)

    def __getstate__(self):
        return {
            "version": 2,
            "timezone": astimezone(self.timezone),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "interval": self.interval,
            "jitter": self.jitter,
        }

    def __setstate__(self, state):
        # This is for compatibility with APScheduler 3.0.x
        if isinstance(state, tuple):
            state = state[1]

        if state.get("version", 1) > 2:
            raise ValueError(
                f"Got serialized data for version {state['version']} of "
                f"{self.__class__.__name__}, but only versions up to 2 can be handled"
            )

        self.timezone = state["timezone"]
        self.start_date = state["start_date"]
        self.end_date = state["end_date"]
        self.interval = state["interval"]
        self.interval_length = self.interval.total_seconds()
        self.jitter = state.get("jitter")

    def __str__(self):
        return f"interval[{self.interval!s}]"

    def __repr__(self):
        options = [
            f"interval={self.interval!r}",
            f"start_date={datetime_repr(self.start_date)!r}",
        ]
        if self.end_date:
            options.append(f"end_date={datetime_repr(self.end_date)!r}")
        if self.jitter:
            options.append(f"jitter={self.jitter}")

        return "<{} ({}, timezone='{}')>".format(
            self.__class__.__name__,
            ", ".join(options),
            self.timezone,
        )
