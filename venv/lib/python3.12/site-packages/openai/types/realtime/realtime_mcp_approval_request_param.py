# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["RealtimeMcpApprovalRequestParam"]


class RealtimeMcpApprovalRequestParam(TypedDict, total=False):
    """A Realtime item requesting human approval of a tool invocation."""

    id: Required[str]
    """The unique ID of the approval request."""

    arguments: Required[str]
    """A JSON string of arguments for the tool."""

    name: Required[str]
    """The name of the tool to run."""

    server_label: Required[str]
    """The label of the MCP server making the request."""

    type: Required[Literal["mcp_approval_request"]]
    """The type of the item. Always `mcp_approval_request`."""
