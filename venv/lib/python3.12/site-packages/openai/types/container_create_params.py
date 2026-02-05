# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

from .._types import SequenceNotStr

__all__ = ["ContainerCreateParams", "ExpiresAfter"]


class ContainerCreateParams(TypedDict, total=False):
    name: Required[str]
    """Name of the container to create."""

    expires_after: ExpiresAfter
    """Container expiration time in seconds relative to the 'anchor' time."""

    file_ids: SequenceNotStr[str]
    """IDs of files to copy to the container."""

    memory_limit: Literal["1g", "4g", "16g", "64g"]
    """Optional memory limit for the container. Defaults to "1g"."""


class ExpiresAfter(TypedDict, total=False):
    """Container expiration time in seconds relative to the 'anchor' time."""

    anchor: Required[Literal["last_active_at"]]
    """Time anchor for the expiration time.

    Currently only 'last_active_at' is supported.
    """

    minutes: Required[int]
