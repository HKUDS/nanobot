# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ResponseMcpCallInProgress"]


class ResponseMcpCallInProgress(BaseModel):
    """Returned when an MCP tool call has started and is in progress."""

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the MCP tool call item."""

    output_index: int
    """The index of the output item in the response."""

    type: Literal["response.mcp_call.in_progress"]
    """The event type, must be `response.mcp_call.in_progress`."""
