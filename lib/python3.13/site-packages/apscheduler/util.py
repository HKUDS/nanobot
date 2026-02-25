"""This module contains several handy functions primarily meant for internal use."""

__all__ = (
    "asbool",
    "asint",
    "astimezone",
    "check_callable_args",
    "convert_to_datetime",
    "datetime_ceil",
    "datetime_to_utc_timestamp",
    "get_callable_name",
    "localize",
    "maybe_ref",
    "normalize",
    "obj_to_ref",
    "ref_to_obj",
    "undefined",
    "utc_timestamp_to_datetime",
)

import re
import sys
from calendar import timegm
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from functools import partial
from inspect import isbuiltin, isclass, isfunction, ismethod, signature

if sys.version_info < (3, 14):
    from asyncio import iscoroutinefunction
else:
    from inspect import iscoroutinefunction

if sys.version_info < (3, 9):
    from backports.zoneinfo import ZoneInfo
else:
    from zoneinfo import ZoneInfo

UTC = timezone.utc


class _Undefined:
    def __nonzero__(self):
        return False

    def __bool__(self):
        return False

    def __repr__(self):
        return "<undefined>"


undefined = (
    _Undefined()
)  #: a unique object that only signifies that no value is defined


def asint(text):
    """
    Safely converts a string to an integer, returning ``None`` if the string is ``None``.

    :type text: str
    :rtype: int

    """
    if text is not None:
        return int(text)


def asbool(obj):
    """
    Interprets an object as a boolean value.

    :rtype: bool

    """
    if isinstance(obj, str):
        obj = obj.strip().lower()
        if obj in ("true", "yes", "on", "y", "t", "1"):
            return True

        if obj in ("false", "no", "off", "n", "f", "0"):
            return False

        raise ValueError(f'Unable to interpret value "{obj}" as boolean')

    return bool(obj)


def astimezone(obj):
    """
    Interprets an object as a timezone.

    :rtype: tzinfo

    """
    if isinstance(obj, str):
        if obj == "UTC":
            return timezone.utc

        return ZoneInfo(obj)

    if isinstance(obj, tzinfo):
        if obj.tzname(None) == "local":
            raise ValueError(
                "Unable to determine the name of the local timezone -- you must "
                "explicitly specify the name of the local timezone. Please refrain "
                "from using timezones like EST to prevent problems with daylight "
                "saving time. Instead, use a locale based timezone name (such as "
                "Europe/Helsinki)."
            )
        elif isinstance(obj, ZoneInfo):
            return obj
        elif hasattr(obj, "zone"):
            # pytz timezones
            if obj.zone:
                return ZoneInfo(obj.zone)

            return timezone(obj._offset)

        return obj

    if obj is not None:
        raise TypeError(f"Expected tzinfo, got {obj.__class__.__name__} instead")


def asdate(obj):
    if isinstance(obj, str):
        return date.fromisoformat(obj)

    return obj


_DATE_REGEX = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
    r"(?:[ T](?P<hour>\d{1,2}):(?P<minute>\d{1,2}):(?P<second>\d{1,2})"
    r"(?:\.(?P<microsecond>\d{1,6}))?"
    r"(?P<timezone>Z|[+-]\d\d:\d\d)?)?$"
)


def convert_to_datetime(input, tz, arg_name):
    """
    Converts the given object to a timezone aware datetime object.

    If a timezone aware datetime object is passed, it is returned unmodified.
    If a native datetime object is passed, it is given the specified timezone.
    If the input is a string, it is parsed as a datetime with the given timezone.

    Date strings are accepted in three different forms: date only (Y-m-d), date with
    time (Y-m-d H:M:S) or with date+time with microseconds (Y-m-d H:M:S.micro).
    Additionally you can override the time zone by giving a specific offset in the
    format specified by ISO 8601: Z (UTC), +HH:MM or -HH:MM.

    :param str|datetime input: the datetime or string to convert to a timezone aware
        datetime
    :param datetime.tzinfo tz: timezone to interpret ``input`` in
    :param str arg_name: the name of the argument (used in an error message)
    :rtype: datetime

    """
    if input is None:
        return
    elif isinstance(input, datetime):
        datetime_ = input
    elif isinstance(input, date):
        datetime_ = datetime.combine(input, time())
    elif isinstance(input, str):
        m = _DATE_REGEX.match(input)
        if not m:
            raise ValueError("Invalid date string")

        values = m.groupdict()
        tzname = values.pop("timezone")
        if tzname == "Z":
            tz = timezone.utc
        elif tzname:
            hours, minutes = (int(x) for x in tzname[1:].split(":"))
            sign = 1 if tzname[0] == "+" else -1
            tz = timezone(sign * timedelta(hours=hours, minutes=minutes))

        values = {k: int(v or 0) for k, v in values.items()}
        datetime_ = datetime(**values)
    else:
        raise TypeError(f"Unsupported type for {arg_name}: {input.__class__.__name__}")

    if datetime_.tzinfo is not None:
        return datetime_
    if tz is None:
        raise ValueError(
            f'The "tz" argument must be specified if {arg_name} has no timezone information'
        )
    if isinstance(tz, str):
        tz = astimezone(tz)

    return localize(datetime_, tz)


def datetime_to_utc_timestamp(timeval):
    """
    Converts a datetime instance to a timestamp.

    :type timeval: datetime
    :rtype: float

    """
    if timeval is not None:
        return timegm(timeval.utctimetuple()) + timeval.microsecond / 1000000


def utc_timestamp_to_datetime(timestamp):
    """
    Converts the given timestamp to a datetime instance.

    :type timestamp: float
    :rtype: datetime

    """
    if timestamp is not None:
        return datetime.fromtimestamp(timestamp, timezone.utc)


def timedelta_seconds(delta):
    """
    Converts the given timedelta to seconds.

    :type delta: timedelta
    :rtype: float

    """
    return delta.days * 24 * 60 * 60 + delta.seconds + delta.microseconds / 1000000.0


def datetime_ceil(dateval):
    """
    Rounds the given datetime object upwards.

    :type dateval: datetime

    """
    if dateval.microsecond > 0:
        return datetime_utc_add(
            dateval, timedelta(seconds=1, microseconds=-dateval.microsecond)
        )

    return dateval


def datetime_utc_add(dateval: datetime, tdelta: timedelta) -> datetime:
    """
    Adds an timedelta to a datetime in UTC for correct datetime arithmetic across
    Daylight Saving Time changes

    :param dateval: The date to add to
    :type dateval: datetime
    :param operand: The timedelta to add to the datetime
    :type operand: timedelta
    :return: The sum of the datetime and the timedelta
    :rtype: datetime
    """
    original_tz = dateval.tzinfo
    if original_tz is None:
        return dateval + tdelta

    return (dateval.astimezone(UTC) + tdelta).astimezone(original_tz)


def datetime_repr(dateval):
    return dateval.strftime("%Y-%m-%d %H:%M:%S %Z") if dateval else "None"


def timezone_repr(timezone: tzinfo) -> str:
    if isinstance(timezone, ZoneInfo):
        return timezone.key

    return repr(timezone)


def get_callable_name(func):
    """
    Returns the best available display name for the given function/callable.

    :rtype: str

    """
    if ismethod(func):
        self = func.__self__
        cls = self if isclass(self) else type(self)
        return f"{cls.__qualname__}.{func.__name__}"
    elif isclass(func) or isfunction(func) or isbuiltin(func):
        return func.__qualname__
    elif hasattr(func, "__call__") and callable(func.__call__):
        # instance of a class with a __call__ method
        return type(func).__qualname__

    raise TypeError(
        f"Unable to determine a name for {func!r} -- maybe it is not a callable?"
    )


def obj_to_ref(obj):
    """
    Returns the path to the given callable.

    :rtype: str
    :raises TypeError: if the given object is not callable
    :raises ValueError: if the given object is a :class:`~functools.partial`, lambda or a nested
        function

    """
    if isinstance(obj, partial):
        raise ValueError("Cannot create a reference to a partial()")

    name = get_callable_name(obj)
    if "<lambda>" in name:
        raise ValueError("Cannot create a reference to a lambda")
    if "<locals>" in name:
        raise ValueError("Cannot create a reference to a nested function")

    if ismethod(obj):
        module = obj.__self__.__module__
    else:
        module = obj.__module__

    return f"{module}:{name}"


def ref_to_obj(ref):
    """
    Returns the object pointed to by ``ref``.

    :type ref: str

    """
    if not isinstance(ref, str):
        raise TypeError("References must be strings")
    if ":" not in ref:
        raise ValueError("Invalid reference")

    modulename, rest = ref.split(":", 1)
    try:
        obj = __import__(modulename, fromlist=[rest])
    except ImportError as exc:
        raise LookupError(
            f"Error resolving reference {ref}: could not import module"
        ) from exc

    try:
        for name in rest.split("."):
            obj = getattr(obj, name)
        return obj
    except Exception:
        raise LookupError(f"Error resolving reference {ref}: error looking up object")


def maybe_ref(ref):
    """
    Returns the object that the given reference points to, if it is indeed a reference.
    If it is not a reference, the object is returned as-is.

    """
    if not isinstance(ref, str):
        return ref
    return ref_to_obj(ref)


def check_callable_args(func, args, kwargs):
    """
    Ensures that the given callable can be called with the given arguments.

    :type args: tuple
    :type kwargs: dict

    """
    pos_kwargs_conflicts = []  # parameters that have a match in both args and kwargs
    positional_only_kwargs = []  # positional-only parameters that have a match in kwargs
    unsatisfied_args = []  # parameters in signature that don't have a match in args or kwargs
    unsatisfied_kwargs = []  # keyword-only arguments that don't have a match in kwargs
    unmatched_args = list(
        args
    )  # args that didn't match any of the parameters in the signature
    # kwargs that didn't match any of the parameters in the signature
    unmatched_kwargs = list(kwargs)
    # indicates if the signature defines *args and **kwargs respectively
    has_varargs = has_var_kwargs = False

    try:
        sig = signature(func, follow_wrapped=False)
    except ValueError:
        # signature() doesn't work against every kind of callable
        return

    for param in sig.parameters.values():
        if param.kind == param.POSITIONAL_OR_KEYWORD:
            if param.name in unmatched_kwargs and unmatched_args:
                pos_kwargs_conflicts.append(param.name)
            elif unmatched_args:
                del unmatched_args[0]
            elif param.name in unmatched_kwargs:
                unmatched_kwargs.remove(param.name)
            elif param.default is param.empty:
                unsatisfied_args.append(param.name)
        elif param.kind == param.POSITIONAL_ONLY:
            if unmatched_args:
                del unmatched_args[0]
            elif param.name in unmatched_kwargs:
                unmatched_kwargs.remove(param.name)
                positional_only_kwargs.append(param.name)
            elif param.default is param.empty:
                unsatisfied_args.append(param.name)
        elif param.kind == param.KEYWORD_ONLY:
            if param.name in unmatched_kwargs:
                unmatched_kwargs.remove(param.name)
            elif param.default is param.empty:
                unsatisfied_kwargs.append(param.name)
        elif param.kind == param.VAR_POSITIONAL:
            has_varargs = True
        elif param.kind == param.VAR_KEYWORD:
            has_var_kwargs = True

    # Make sure there are no conflicts between args and kwargs
    if pos_kwargs_conflicts:
        raise ValueError(
            "The following arguments are supplied in both args and kwargs: {}".format(
                ", ".join(pos_kwargs_conflicts)
            )
        )

    # Check if keyword arguments are being fed to positional-only parameters
    if positional_only_kwargs:
        raise ValueError(
            "The following arguments cannot be given as keyword arguments: {}".format(
                ", ".join(positional_only_kwargs)
            )
        )

    # Check that the number of positional arguments minus the number of matched kwargs
    # matches the argspec
    if unsatisfied_args:
        raise ValueError(
            "The following arguments have not been supplied: {}".format(
                ", ".join(unsatisfied_args)
            )
        )

    # Check that all keyword-only arguments have been supplied
    if unsatisfied_kwargs:
        raise ValueError(
            "The following keyword-only arguments have not been supplied in kwargs: "
            "{}".format(", ".join(unsatisfied_kwargs))
        )

    # Check that the callable can accept the given number of positional arguments
    if not has_varargs and unmatched_args:
        raise ValueError(
            f"The list of positional arguments is longer than the target callable can "
            f"handle (allowed: {len(args) - len(unmatched_args)}, given in args: "
            f"{len(args)})"
        )

    # Check that the callable can accept the given keyword arguments
    if not has_var_kwargs and unmatched_kwargs:
        raise ValueError(
            "The target callable does not accept the following keyword arguments: "
            "{}".format(", ".join(unmatched_kwargs))
        )


def iscoroutinefunction_partial(f):
    while isinstance(f, partial):
        f = f.func

    # The asyncio version of iscoroutinefunction includes testing for @coroutine
    # decorations vs. the inspect version which does not.
    return iscoroutinefunction(f)


def normalize(dt):
    return datetime.fromtimestamp(dt.timestamp(), dt.tzinfo)


def localize(dt, tzinfo):
    if hasattr(tzinfo, "localize"):
        return tzinfo.localize(dt)

    return normalize(dt.replace(tzinfo=tzinfo))
