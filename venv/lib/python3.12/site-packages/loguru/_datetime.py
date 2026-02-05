import re
from calendar import day_abbr, day_name, month_abbr, month_name
from datetime import datetime as datetime_
from datetime import timedelta, timezone
from functools import lru_cache, partial
from time import localtime, strftime

tokens = r"H{1,2}|h{1,2}|m{1,2}|s{1,2}|S+|YYYY|YY|M{1,4}|D{1,4}|Z{1,2}|zz|A|X|x|E|Q|dddd|ddd|d"

pattern = re.compile(r"(?:{0})|\[(?:{0}|!UTC|)\]".format(tokens))


def _builtin_datetime_formatter(is_utc, format_string, dt):
    if is_utc:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(format_string)


def _loguru_datetime_formatter(is_utc, format_string, formatters, dt):
    if is_utc:
        dt = dt.astimezone(timezone.utc)
    t = dt.timetuple()
    args = tuple(f(t, dt) for f in formatters)
    return format_string % args


def _default_datetime_formatter(dt):
    return "%04d-%02d-%02d %02d:%02d:%02d.%03d" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def _format_timezone(tzinfo, *, sep):
    offset = tzinfo.utcoffset(None).total_seconds()
    sign = "+" if offset >= 0 else "-"
    (h, m), s = divmod(abs(offset // 60), 60), abs(offset) % 60
    z = "%s%02d%s%02d" % (sign, h, sep, m)
    if s > 0:
        if s.is_integer():
            z += "%s%02d" % (sep, s)
        else:
            z += "%s%09.06f" % (sep, s)
    return z


@lru_cache(maxsize=32)
def _compile_format(spec):
    if spec == "YYYY-MM-DD HH:mm:ss.SSS":
        return _default_datetime_formatter

    is_utc = spec.endswith("!UTC")

    if is_utc:
        spec = spec[:-4]

    if not spec:
        spec = "%Y-%m-%dT%H:%M:%S.%f%z"

    if "%" in spec:
        return partial(_builtin_datetime_formatter, is_utc, spec)

    if "SSSSSSS" in spec:
        raise ValueError(
            "Invalid time format: the provided format string contains more than six successive "
            "'S' characters. This may be due to an attempt to use nanosecond precision, which "
            "is not supported."
        )

    rep = {
        "YYYY": ("%04d", lambda t, dt: t.tm_year),
        "YY": ("%02d", lambda t, dt: t.tm_year % 100),
        "Q": ("%d", lambda t, dt: (t.tm_mon - 1) // 3 + 1),
        "MMMM": ("%s", lambda t, dt: month_name[t.tm_mon]),
        "MMM": ("%s", lambda t, dt: month_abbr[t.tm_mon]),
        "MM": ("%02d", lambda t, dt: t.tm_mon),
        "M": ("%d", lambda t, dt: t.tm_mon),
        "DDDD": ("%03d", lambda t, dt: t.tm_yday),
        "DDD": ("%d", lambda t, dt: t.tm_yday),
        "DD": ("%02d", lambda t, dt: t.tm_mday),
        "D": ("%d", lambda t, dt: t.tm_mday),
        "dddd": ("%s", lambda t, dt: day_name[t.tm_wday]),
        "ddd": ("%s", lambda t, dt: day_abbr[t.tm_wday]),
        "d": ("%d", lambda t, dt: t.tm_wday),
        "E": ("%d", lambda t, dt: t.tm_wday + 1),
        "HH": ("%02d", lambda t, dt: t.tm_hour),
        "H": ("%d", lambda t, dt: t.tm_hour),
        "hh": ("%02d", lambda t, dt: (t.tm_hour - 1) % 12 + 1),
        "h": ("%d", lambda t, dt: (t.tm_hour - 1) % 12 + 1),
        "mm": ("%02d", lambda t, dt: t.tm_min),
        "m": ("%d", lambda t, dt: t.tm_min),
        "ss": ("%02d", lambda t, dt: t.tm_sec),
        "s": ("%d", lambda t, dt: t.tm_sec),
        "S": ("%d", lambda t, dt: dt.microsecond // 100000),
        "SS": ("%02d", lambda t, dt: dt.microsecond // 10000),
        "SSS": ("%03d", lambda t, dt: dt.microsecond // 1000),
        "SSSS": ("%04d", lambda t, dt: dt.microsecond // 100),
        "SSSSS": ("%05d", lambda t, dt: dt.microsecond // 10),
        "SSSSSS": ("%06d", lambda t, dt: dt.microsecond),
        "A": ("%s", lambda t, dt: "AM" if t.tm_hour < 12 else "PM"),
        "Z": ("%s", lambda t, dt: _format_timezone(dt.tzinfo or timezone.utc, sep=":")),
        "ZZ": ("%s", lambda t, dt: _format_timezone(dt.tzinfo or timezone.utc, sep="")),
        "zz": ("%s", lambda t, dt: (dt.tzinfo or timezone.utc).tzname(dt) or ""),
        "X": ("%d", lambda t, dt: dt.timestamp()),
        "x": ("%d", lambda t, dt: int(dt.timestamp() * 1000000 + dt.microsecond)),
    }

    format_string = ""
    formatters = []
    pos = 0

    for match in pattern.finditer(spec):
        start, end = match.span()
        format_string += spec[pos:start]
        pos = end

        token = match.group(0)

        try:
            specifier, formatter = rep[token]
        except KeyError:
            format_string += token[1:-1]
        else:
            format_string += specifier
            formatters.append(formatter)

    format_string += spec[pos:]

    return partial(_loguru_datetime_formatter, is_utc, format_string, formatters)


class datetime(datetime_):  # noqa: N801

    def __format__(self, fmt):
        return _compile_format(fmt)(self)


def aware_now():
    now = datetime_.now()
    timestamp = now.timestamp()
    local = localtime(timestamp)

    try:
        seconds = local.tm_gmtoff
        zone = local.tm_zone
    except AttributeError:
        # Workaround for Python 3.5.
        utc_naive = datetime_.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
        offset = datetime_.fromtimestamp(timestamp) - utc_naive
        seconds = offset.total_seconds()
        zone = strftime("%Z")

    tzinfo = timezone(timedelta(seconds=seconds), zone)

    return datetime.combine(now.date(), now.time().replace(tzinfo=tzinfo))
