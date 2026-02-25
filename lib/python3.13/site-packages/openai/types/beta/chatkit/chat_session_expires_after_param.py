# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["ChatSessionExpiresAfterParam"]


class ChatSessionExpiresAfterParam(TypedDict, total=False):
    """Controls when the session expires relative to an anchor timestamp."""

    anchor: Required[Literal["created_at"]]
    """Base timestamp used to calculate expiration. Currently fixed to `created_at`."""

    seconds: Required[int]
    """Number of seconds after the anchor when the session expires."""
