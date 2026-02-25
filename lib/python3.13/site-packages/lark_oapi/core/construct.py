from typing import *

from .exception import UnmarshalException


def init(obj: Any, d: Dict, types: Dict) -> None:
    if d is None:
        return
    for k, v in d.items():
        if not hasattr(obj, k):
            continue
        t: Type = types.get(k)
        setattr(obj, k, parse(t, v, k))


def parse(t: Type, v: Any, field: Any) -> Any:
    if t is None or v is None:
        return v

    type_ = type_of(t)
    if type_ is list or type_ is tuple or type_ is List:
        if not isinstance(v, (list, tuple)):
            raise UnmarshalException(t, type(v), field)
        if hasattr(t, "__args__"):
            sub_t = t.__args__[0]
            return [parse(sub_t, i, field) for i in v]
        return v

    if type_ is dict or type_ is Dict:
        if not isinstance(v, dict):
            raise UnmarshalException(t, type(v), field)
        if hasattr(t, "__args__"):
            val_t = t.__args__[1]
            return {k: parse(val_t, v[k], k) for k in v}
        return v

    if type_ is set or type_ is Set:
        if not isinstance(v, set):
            raise UnmarshalException(t, type(v), field)
        if hasattr(t, "__args__"):
            sub_t = t.__args__[0]
            return {parse(sub_t, i, field) for i in v}
        return v

    if type_ is object:
        if not isinstance(v, dict):
            raise UnmarshalException(t, type(v), field)
        return t(v)

    return v


def type_of(t: Type) -> Type:
    if t is int or \
            t is float or \
            t is complex or \
            t is str or \
            t is bool or \
            t is list or \
            t is tuple or \
            t is dict or \
            t is set or \
            t is Any:
        return t

    if hasattr(t, "_name"):
        name = getattr(t, "_name")
        if name == "Dict":
            return Dict
        if name == "List":
            return List
        if name == "Set":
            return Set
        return Any

    return object
