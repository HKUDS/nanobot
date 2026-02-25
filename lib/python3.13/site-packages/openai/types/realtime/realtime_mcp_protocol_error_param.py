# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["RealtimeMcpProtocolErrorParam"]


class RealtimeMcpProtocolErrorParam(TypedDict, total=False):
    code: Required[int]

    message: Required[str]

    type: Required[Literal["protocol_error"]]
