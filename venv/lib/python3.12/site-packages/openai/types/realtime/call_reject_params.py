# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import TypedDict

__all__ = ["CallRejectParams"]


class CallRejectParams(TypedDict, total=False):
    status_code: int
    """SIP response code to send back to the caller.

    Defaults to `603` (Decline) when omitted.
    """
