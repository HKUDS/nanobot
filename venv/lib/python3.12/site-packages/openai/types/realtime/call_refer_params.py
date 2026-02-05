# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Required, TypedDict

__all__ = ["CallReferParams"]


class CallReferParams(TypedDict, total=False):
    target_uri: Required[str]
    """URI that should appear in the SIP Refer-To header.

    Supports values like `tel:+14155550123` or `sip:agent@example.com`.
    """
