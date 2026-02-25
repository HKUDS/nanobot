# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import Literal, Required, TypedDict

from ..._types import SequenceNotStr

__all__ = ["ComparisonFilter"]


class ComparisonFilter(TypedDict, total=False):
    """
    A filter used to compare a specified attribute key to a given value using a defined comparison operation.
    """

    key: Required[str]
    """The key to compare against the value."""

    type: Required[Literal["eq", "ne", "gt", "gte", "lt", "lte"]]
    """
    Specifies the comparison operator: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`,
    `nin`.

    - `eq`: equals
    - `ne`: not equal
    - `gt`: greater than
    - `gte`: greater than or equal
    - `lt`: less than
    - `lte`: less than or equal
    - `in`: in
    - `nin`: not in
    """

    value: Required[Union[str, float, bool, SequenceNotStr[Union[str, float]]]]
    """
    The value to compare against the attribute key; supports string, number, or
    boolean types.
    """
