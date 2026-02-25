"""JSON-compatible module with sane defaults."""

from json import *  # noqa: F401, F403
from json import loads as original_loads


def _safe_int(s):
    if len(s) > 100:
        raise ValueError('Integer is too large')
    return int(s)


def loads(*args, **kwargs):
    if 'parse_int' not in kwargs:  # pragma: no cover
        kwargs['parse_int'] = _safe_int
    return original_loads(*args, **kwargs)
