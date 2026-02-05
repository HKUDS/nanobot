# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ComparisonFilter"]


class ComparisonFilter(BaseModel):
    """
    A filter used to compare a specified attribute key to a given value using a defined comparison operation.
    """

    key: str
    """The key to compare against the value."""

    type: Literal["eq", "ne", "gt", "gte", "lt", "lte"]
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

    value: Union[str, float, bool, List[Union[str, float]]]
    """
    The value to compare against the attribute key; supports string, number, or
    boolean types.
    """
