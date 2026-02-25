from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from tzlocal import get_localzone

from apscheduler.triggers.base import BaseTrigger
from apscheduler.util import (
    asdate,
    astimezone,
    timezone_repr,
)


class CalendarIntervalTrigger(BaseTrigger):
    """
    Runs the task on specified calendar-based intervals always at the same exact time of
    day.

    When calculating the next date, the ``years`` and ``months`` parameters are first
    added to the previous date while keeping the day of the month constant. This is
    repeated until the resulting date is valid. After that, the ``weeks`` and ``days``
    parameters are added to that date. Finally, the date is combined with the given time
    (hour, minute, second) to form the final datetime.

    This means that if the ``days`` or ``weeks`` parameters are not used, the task will
    always be executed on the same day of the month at the same wall clock time,
    assuming the date and time are valid.

    If the resulting datetime is invalid due to a daylight saving forward shift, the
    date is discarded and the process moves on to the next date. If instead the datetime
    is ambiguous due to a backward DST shift, the earlier of the two resulting datetimes
    is used.

    If no previous run time is specified when requesting a new run time (like when
    starting for the first time or resuming after being paused), ``start_date`` is used
    as a reference and the next valid datetime equal to or later than the current time
    will be returned. Otherwise, the next valid datetime starting from the previous run
    time is returned, even if it's in the past.

    .. warning:: Be wary of setting a start date near the end of the month (29. – 31.)
        if you have ``months`` specified in your interval, as this will skip the months
        when those days do not exist. Likewise, setting the start date on the leap day
        (February 29th) and having ``years`` defined may cause some years to be skipped.

        Users are also discouraged from  using a time inside the target timezone's DST
        switching period (typically around 2 am) since a date could either be skipped or
        repeated due to the specified wall clock time either occurring twice or not at
        all.

    :param years: number of years to wait
    :param months: number of months to wait
    :param weeks: number of weeks to wait
    :param days: number of days to wait
    :param hour: hour to run the task at
    :param minute: minute to run the task at
    :param second: second to run the task at
    :param start_date: first date to trigger on (defaults to current date if omitted)
    :param end_date: latest possible date to trigger on
    :param timezone: time zone to use for calculating the next fire time (defaults
        to scheduler timezone if created via the scheduler, otherwise the local time
        zone)
    :param jitter: delay the job execution by ``jitter`` seconds at most
    """

    __slots__ = (
        "_time",
        "days",
        "end_date",
        "jitter",
        "months",
        "start_date",
        "timezone",
        "weeks",
        "years",
    )

    def __init__(
        self,
        *,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        days: int = 0,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        timezone: str | tzinfo | None = None,
        jitter: int | None = None,
    ):
        if timezone:
            self.timezone = astimezone(timezone)
        else:
            self.timezone = astimezone(get_localzone())

        self.years = years
        self.months = months
        self.weeks = weeks
        self.days = days
        self.start_date = asdate(start_date) or date.today()
        self.end_date = asdate(end_date)
        self.jitter = jitter
        self._time = time(hour, minute, second, tzinfo=self.timezone)

        if self.years == self.months == self.weeks == self.days == 0:
            raise ValueError("interval must be at least 1 day long")

        if self.end_date and self.start_date > self.end_date:
            raise ValueError("end_date cannot be earlier than start_date")

    def get_next_fire_time(
        self, previous_fire_time: datetime | None, now: datetime
    ) -> datetime | None:
        while True:
            if previous_fire_time:
                year, month = previous_fire_time.year, previous_fire_time.month
                while True:
                    month += self.months
                    year += self.years + (month - 1) // 12
                    month = (month - 1) % 12 + 1
                    try:
                        next_date = date(year, month, previous_fire_time.day)
                    except ValueError:
                        pass  # Nonexistent date
                    else:
                        next_date += timedelta(self.days + self.weeks * 7)
                        break
            else:
                next_date = self.start_date

            # Don't return any date past end_date
            if self.end_date and next_date > self.end_date:
                return None

            # Combine the date with the designated time and normalize the result
            timestamp = datetime.combine(next_date, self._time).timestamp()
            next_time = datetime.fromtimestamp(timestamp, self.timezone)

            # Check if the time is off due to normalization and a forward DST shift
            if next_time.timetz() != self._time:
                previous_fire_time = next_time.date()
            else:
                return self._apply_jitter(next_time, self.jitter, now)

    def __getstate__(self) -> dict[str, Any]:
        return {
            "version": 1,
            "interval": [self.years, self.months, self.weeks, self.days],
            "time": [self._time.hour, self._time.minute, self._time.second],
            "start_date": self.start_date,
            "end_date": self.end_date,
            "timezone": self.timezone,
            "jitter": self.jitter,
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        if state.get("version", 1) > 1:
            raise ValueError(
                f"Got serialized data for version {state['version']} of "
                f"{self.__class__.__name__}, but only versions up to 1 can be handled"
            )

        self.years, self.months, self.weeks, self.days = state["interval"]
        self.start_date = state["start_date"]
        self.end_date = state["end_date"]
        self.timezone = state["timezone"]
        self.jitter = state["jitter"]
        self._time = time(*state["time"], tzinfo=self.timezone)

    def __repr__(self) -> str:
        fields = []
        for field in "years", "months", "weeks", "days":
            value = getattr(self, field)
            if value > 0:
                fields.append(f"{field}={value}")

        fields.append(f"time={self._time.isoformat()!r}")
        fields.append(f"start_date='{self.start_date}'")
        if self.end_date:
            fields.append(f"end_date='{self.end_date}'")

        fields.append(f"timezone={timezone_repr(self.timezone)!r}")
        return f"{self.__class__.__name__}({', '.join(fields)})"
