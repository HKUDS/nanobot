# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["RealtimeMcpListTools", "Tool"]


class Tool(BaseModel):
    """A tool available on an MCP server."""

    input_schema: object
    """The JSON schema describing the tool's input."""

    name: str
    """The name of the tool."""

    annotations: Optional[object] = None
    """Additional annotations about the tool."""

    description: Optional[str] = None
    """The description of the tool."""


class RealtimeMcpListTools(BaseModel):
    """A Realtime item listing tools available on an MCP server."""

    server_label: str
    """The label of the MCP server."""

    tools: List[Tool]
    """The tools available on the server."""

    type: Literal["mcp_list_tools"]
    """The type of the item. Always `mcp_list_tools`."""

    id: Optional[str] = None
    """The unique ID of the list."""
