# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, TypedDict

__all__ = ["SkillListParams"]


class SkillListParams(TypedDict, total=False):
    after: str
    """Identifier for the last item from the previous pagination request"""

    limit: int
    """Number of items to retrieve"""

    order: Literal["asc", "desc"]
    """Sort order of results by timestamp.

    Use `asc` for ascending order or `desc` for descending order.
    """
