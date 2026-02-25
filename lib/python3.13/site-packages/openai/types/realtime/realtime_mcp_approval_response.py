# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["RealtimeMcpApprovalResponse"]


class RealtimeMcpApprovalResponse(BaseModel):
    """A Realtime item responding to an MCP approval request."""

    id: str
    """The unique ID of the approval response."""

    approval_request_id: str
    """The ID of the approval request being answered."""

    approve: bool
    """Whether the request was approved."""

    type: Literal["mcp_approval_response"]
    """The type of the item. Always `mcp_approval_response`."""

    reason: Optional[str] = None
    """Optional reason for the decision."""
