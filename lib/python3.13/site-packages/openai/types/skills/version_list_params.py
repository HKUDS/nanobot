# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, TypedDict

__all__ = ["VersionListParams"]


class VersionListParams(TypedDict, total=False):
    after: str
    """The skill version ID to start after."""

    limit: int
    """Number of versions to retrieve."""

    order: Literal["asc", "desc"]
    """Sort order of results by version number."""
