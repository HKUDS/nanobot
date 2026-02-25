# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union, Optional
from typing_extensions import Literal, Required, TypeAlias, TypedDict

from .realtime_mcphttp_error_param import RealtimeMcphttpErrorParam
from .realtime_mcp_protocol_error_param import RealtimeMcpProtocolErrorParam
from .realtime_mcp_tool_execution_error_param import RealtimeMcpToolExecutionErrorParam

__all__ = ["RealtimeMcpToolCallParam", "Error"]

Error: TypeAlias = Union[RealtimeMcpProtocolErrorParam, RealtimeMcpToolExecutionErrorParam, RealtimeMcphttpErrorParam]


class RealtimeMcpToolCallParam(TypedDict, total=False):
    """A Realtime item representing an invocation of a tool on an MCP server."""

    id: Required[str]
    """The unique ID of the tool call."""

    arguments: Required[str]
    """A JSON string of the arguments passed to the tool."""

    name: Required[str]
    """The name of the tool that was run."""

    server_label: Required[str]
    """The label of the MCP server running the tool."""

    type: Required[Literal["mcp_call"]]
    """The type of the item. Always `mcp_call`."""

    approval_request_id: Optional[str]
    """The ID of an associated approval request, if any."""

    error: Optional[Error]
    """The error from the tool call, if any."""

    output: Optional[str]
    """The output from the tool call."""
