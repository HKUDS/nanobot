# coding=utf-8
# Copyright 2022-present, the HuggingFace Inc. team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Handle typing imports based on system compatibility."""

import sys
from typing import Any, Callable, Literal, Optional, Type, TypeVar, Union, get_args, get_origin


UNION_TYPES: list[Any] = [Union]
if sys.version_info >= (3, 10):
    from types import UnionType

    UNION_TYPES += [UnionType]


HTTP_METHOD_T = Literal["GET", "OPTIONS", "HEAD", "POST", "PUT", "PATCH", "DELETE"]

# type hint meaning "function signature not changed by decorator"
CallableT = TypeVar("CallableT", bound=Callable)

_JSON_SERIALIZABLE_TYPES = (int, float, str, bool, type(None))


def is_jsonable(obj: Any, _visited: Optional[set[int]] = None) -> bool:
    """Check if an object is JSON serializable.

    This is a weak check, as it does not check for the actual JSON serialization, but only for the types of the object.
    It works correctly for basic use cases but do not guarantee an exhaustive check.

    Object is considered to be recursively json serializable if:
    - it is an instance of int, float, str, bool, or NoneType
    - it is a list or tuple and all its items are json serializable
    - it is a dict and all its keys are strings and all its values are json serializable

    Uses a visited set to avoid infinite recursion on circular references. If object has already been visited, it is
    considered not json serializable.
    """
    # Initialize visited set to track object ids and detect circular references
    if _visited is None:
        _visited = set()

    # Detect circular reference
    obj_id = id(obj)
    if obj_id in _visited:
        return False

    # Add current object to visited before recursive checks
    _visited.add(obj_id)
    try:
        if isinstance(obj, _JSON_SERIALIZABLE_TYPES):
            return True
        if isinstance(obj, (list, tuple)):
            return all(is_jsonable(item, _visited) for item in obj)
        if isinstance(obj, dict):
            return all(
                isinstance(key, _JSON_SERIALIZABLE_TYPES) and is_jsonable(value, _visited)
                for key, value in obj.items()
            )
        if hasattr(obj, "__json__"):
            return True
        return False
    except RecursionError:
        return False
    finally:
        # Remove the object id from visited to avoid side‑effects for other branches
        _visited.discard(obj_id)


def is_simple_optional_type(type_: Type) -> bool:
    """Check if a type is optional, i.e. Optional[Type] or Union[Type, None] or Type | None, where Type is a non-composite type."""
    if get_origin(type_) in UNION_TYPES:
        union_args = get_args(type_)
        if len(union_args) == 2 and type(None) in union_args:
            return True
    return False


def unwrap_simple_optional_type(optional_type: Type) -> Type:
    """Unwraps a simple optional type, i.e. returns Type from Optional[Type]."""
    for arg in get_args(optional_type):
        if arg is not type(None):
            return arg
    raise ValueError(f"'{optional_type}' is not an optional type")
