# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import TypedDict

__all__ = ["ChatSessionRateLimitsParam"]


class ChatSessionRateLimitsParam(TypedDict, total=False):
    """Controls request rate limits for the session."""

    max_requests_per_1_minute: int
    """Maximum number of requests allowed per minute for the session. Defaults to 10."""
