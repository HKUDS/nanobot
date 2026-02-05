# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Iterable, Optional
from typing_extensions import Literal, Required, TypedDict

__all__ = ["RealtimeMcpListToolsParam", "Tool"]


class Tool(TypedDict, total=False):
    """A tool available on an MCP server."""

    input_schema: Required[object]
    """The JSON schema describing the tool's input."""

    name: Required[str]
    """The name of the tool."""

    annotations: Optional[object]
    """Additional annotations about the tool."""

    description: Optional[str]
    """The description of the tool."""


class RealtimeMcpListToolsParam(TypedDict, total=False):
    """A Realtime item listing tools available on an MCP server."""

    server_label: Required[str]
    """The label of the MCP server."""

    tools: Required[Iterable[Tool]]
    """The tools available on the server."""

    type: Required[Literal["mcp_list_tools"]]
    """The type of the item. Always `mcp_list_tools`."""

    id: str
    """The unique ID of the list."""
