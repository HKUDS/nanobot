# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Dict, List, Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel
from .realtime_function_tool import RealtimeFunctionTool

__all__ = [
    "RealtimeToolsConfigUnion",
    "Mcp",
    "McpAllowedTools",
    "McpAllowedToolsMcpToolFilter",
    "McpRequireApproval",
    "McpRequireApprovalMcpToolApprovalFilter",
    "McpRequireApprovalMcpToolApprovalFilterAlways",
    "McpRequireApprovalMcpToolApprovalFilterNever",
]


class McpAllowedToolsMcpToolFilter(BaseModel):
    """A filter object to specify which tools are allowed."""

    read_only: Optional[bool] = None
    """Indicates whether or not a tool modifies data or is read-only.

    If an MCP server is
    [annotated with `readOnlyHint`](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations-readonlyhint),
    it will match this filter.
    """

    tool_names: Optional[List[str]] = None
    """List of allowed tool names."""


McpAllowedTools: TypeAlias = Union[List[str], McpAllowedToolsMcpToolFilter, None]


class McpRequireApprovalMcpToolApprovalFilterAlways(BaseModel):
    """A filter object to specify which tools are allowed."""

    read_only: Optional[bool] = None
    """Indicates whether or not a tool modifies data or is read-only.

    If an MCP server is
    [annotated with `readOnlyHint`](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations-readonlyhint),
    it will match this filter.
    """

    tool_names: Optional[List[str]] = None
    """List of allowed tool names."""


class McpRequireApprovalMcpToolApprovalFilterNever(BaseModel):
    """A filter object to specify which tools are allowed."""

    read_only: Optional[bool] = None
    """Indicates whether or not a tool modifies data or is read-only.

    If an MCP server is
    [annotated with `readOnlyHint`](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations-readonlyhint),
    it will match this filter.
    """

    tool_names: Optional[List[str]] = None
    """List of allowed tool names."""


class McpRequireApprovalMcpToolApprovalFilter(BaseModel):
    """Specify which of the MCP server's tools require approval.

    Can be
    `always`, `never`, or a filter object associated with tools
    that require approval.
    """

    always: Optional[McpRequireApprovalMcpToolApprovalFilterAlways] = None
    """A filter object to specify which tools are allowed."""

    never: Optional[McpRequireApprovalMcpToolApprovalFilterNever] = None
    """A filter object to specify which tools are allowed."""


McpRequireApproval: TypeAlias = Union[McpRequireApprovalMcpToolApprovalFilter, Literal["always", "never"], None]


class Mcp(BaseModel):
    """
    Give the model access to additional tools via remote Model Context Protocol
    (MCP) servers. [Learn more about MCP](https://platform.openai.com/docs/guides/tools-remote-mcp).
    """

    server_label: str
    """A label for this MCP server, used to identify it in tool calls."""

    type: Literal["mcp"]
    """The type of the MCP tool. Always `mcp`."""

    allowed_tools: Optional[McpAllowedTools] = None
    """List of allowed tool names or a filter object."""

    authorization: Optional[str] = None
    """
    An OAuth access token that can be used with a remote MCP server, either with a
    custom MCP server URL or a service connector. Your application must handle the
    OAuth authorization flow and provide the token here.
    """

    connector_id: Optional[
        Literal[
            "connector_dropbox",
            "connector_gmail",
            "connector_googlecalendar",
            "connector_googledrive",
            "connector_microsoftteams",
            "connector_outlookcalendar",
            "connector_outlookemail",
            "connector_sharepoint",
        ]
    ] = None
    """Identifier for service connectors, like those available in ChatGPT.

    One of `server_url` or `connector_id` must be provided. Learn more about service
    connectors
    [here](https://platform.openai.com/docs/guides/tools-remote-mcp#connectors).

    Currently supported `connector_id` values are:

    - Dropbox: `connector_dropbox`
    - Gmail: `connector_gmail`
    - Google Calendar: `connector_googlecalendar`
    - Google Drive: `connector_googledrive`
    - Microsoft Teams: `connector_microsoftteams`
    - Outlook Calendar: `connector_outlookcalendar`
    - Outlook Email: `connector_outlookemail`
    - SharePoint: `connector_sharepoint`
    """

    headers: Optional[Dict[str, str]] = None
    """Optional HTTP headers to send to the MCP server.

    Use for authentication or other purposes.
    """

    require_approval: Optional[McpRequireApproval] = None
    """Specify which of the MCP server's tools require approval."""

    server_description: Optional[str] = None
    """Optional description of the MCP server, used to provide more context."""

    server_url: Optional[str] = None
    """The URL for the MCP server.

    One of `server_url` or `connector_id` must be provided.
    """


RealtimeToolsConfigUnion: TypeAlias = Annotated[Union[RealtimeFunctionTool, Mcp], PropertyInfo(discriminator="type")]
