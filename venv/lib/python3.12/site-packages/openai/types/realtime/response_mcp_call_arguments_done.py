# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ResponseMcpCallArgumentsDone"]


class ResponseMcpCallArgumentsDone(BaseModel):
    """Returned when MCP tool call arguments are finalized during response generation."""

    arguments: str
    """The final JSON-encoded arguments string."""

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the MCP tool call item."""

    output_index: int
    """The index of the output item in the response."""

    response_id: str
    """The ID of the response."""

    type: Literal["response.mcp_call_arguments.done"]
    """The event type, must be `response.mcp_call_arguments.done`."""
