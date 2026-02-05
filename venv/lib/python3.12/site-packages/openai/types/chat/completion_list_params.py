# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Optional
from typing_extensions import Literal, TypedDict

from ..shared_params.metadata import Metadata

__all__ = ["CompletionListParams"]


class CompletionListParams(TypedDict, total=False):
    after: str
    """Identifier for the last chat completion from the previous pagination request."""

    limit: int
    """Number of Chat Completions to retrieve."""

    metadata: Optional[Metadata]
    """Set of 16 key-value pairs that can be attached to an object.

    This can be useful for storing additional information about the object in a
    structured format, and querying for objects via API or the dashboard.

    Keys are strings with a maximum length of 64 characters. Values are strings with
    a maximum length of 512 characters.
    """

    model: str
    """The model used to generate the Chat Completions."""

    order: Literal["asc", "desc"]
    """Sort order for Chat Completions by timestamp.

    Use `asc` for ascending order or `desc` for descending order. Defaults to `asc`.
    """
