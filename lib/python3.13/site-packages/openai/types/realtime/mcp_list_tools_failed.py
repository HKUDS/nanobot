# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["McpListToolsFailed"]


class McpListToolsFailed(BaseModel):
    """Returned when listing MCP tools has failed for an item."""

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the MCP list tools item."""

    type: Literal["mcp_list_tools.failed"]
    """The event type, must be `mcp_list_tools.failed`."""
