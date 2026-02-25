# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, TypedDict

__all__ = ["ThreadListItemsParams"]


class ThreadListItemsParams(TypedDict, total=False):
    after: str
    """List items created after this thread item ID.

    Defaults to null for the first page.
    """

    before: str
    """List items created before this thread item ID.

    Defaults to null for the newest results.
    """

    limit: int
    """Maximum number of thread items to return. Defaults to 20."""

    order: Literal["asc", "desc"]
    """Sort order for results by creation time. Defaults to `desc`."""
