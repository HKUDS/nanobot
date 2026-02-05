# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["McpListToolsCompleted"]


class McpListToolsCompleted(BaseModel):
    """Returned when listing MCP tools has completed for an item."""

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the MCP list tools item."""

    type: Literal["mcp_list_tools.completed"]
    """The event type, must be `mcp_list_tools.completed`."""
