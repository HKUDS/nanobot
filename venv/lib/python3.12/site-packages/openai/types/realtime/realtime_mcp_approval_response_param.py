# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Optional
from typing_extensions import Literal, Required, TypedDict

__all__ = ["RealtimeMcpApprovalResponseParam"]


class RealtimeMcpApprovalResponseParam(TypedDict, total=False):
    """A Realtime item responding to an MCP approval request."""

    id: Required[str]
    """The unique ID of the approval response."""

    approval_request_id: Required[str]
    """The ID of the approval request being answered."""

    approve: Required[bool]
    """Whether the request was approved."""

    type: Required[Literal["mcp_approval_response"]]
    """The type of the item. Always `mcp_approval_response`."""

    reason: Optional[str]
    """Optional reason for the decision."""
