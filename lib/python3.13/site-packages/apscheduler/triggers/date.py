from datetime import datetime

from tzlocal import get_localzone

from apscheduler.triggers.base import BaseTrigger
from apscheduler.util import astimezone, convert_to_datetime, datetime_repr


class DateTrigger(BaseTrigger):
    """
    Triggers once on the given datetime. If ``run_date`` is left empty, current time is used.

    :param datetime|str run_date: the date/time to run the job at
    :param datetime.tzinfo|str timezone: time zone for ``run_date`` if it doesn't have one already
    """

    __slots__ = "run_date"

    def __init__(self, run_date=None, timezone=None):
        timezone = astimezone(timezone) or get_localzone()
        if run_date is not None:
            self.run_date = convert_to_datetime(run_date, timezone, "run_date")
        else:
            self.run_date = datetime.now(timezone)

    def get_next_fire_time(self, previous_fire_time, now):
        return self.run_date if previous_fire_time is None else None

    def __getstate__(self):
        return {"version": 1, "run_date": self.run_date}

    def __setstate__(self, state):
        # This is for compatibility with APScheduler 3.0.x
        if isinstance(state, tuple):
            state = state[1]

        if state.get("version", 1) > 1:
            raise ValueError(
                f"Got serialized data for version {state['version']} of "
                f"{self.__class__.__name__}, but only version 1 can be handled"
            )

        self.run_date = state["run_date"]

    def __str__(self):
        return f"date[{datetime_repr(self.run_date)}]"

    def __repr__(self):
        return (
            f"<{self.__class__.__name__} (run_date='{datetime_repr(self.run_date)}')>"
        )
