# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Dict, Union, Optional
from typing_extensions import Literal, Required, TypeAlias, TypedDict

from . import web_search_tool_param
from ..chat import ChatCompletionFunctionToolParam
from ..._types import SequenceNotStr
from .custom_tool_param import CustomToolParam
from .computer_tool_param import ComputerToolParam
from .function_tool_param import FunctionToolParam
from .web_search_tool_param import WebSearchToolParam
from .apply_patch_tool_param import ApplyPatchToolParam
from .file_search_tool_param import FileSearchToolParam
from .function_shell_tool_param import FunctionShellToolParam
from .web_search_preview_tool_param import WebSearchPreviewToolParam

__all__ = [
    "ToolParam",
    "Mcp",
    "McpAllowedTools",
    "McpAllowedToolsMcpToolFilter",
    "McpRequireApproval",
    "McpRequireApprovalMcpToolApprovalFilter",
    "McpRequireApprovalMcpToolApprovalFilterAlways",
    "McpRequireApprovalMcpToolApprovalFilterNever",
    "CodeInterpreter",
    "CodeInterpreterContainer",
    "CodeInterpreterContainerCodeInterpreterToolAuto",
    "ImageGeneration",
    "ImageGenerationInputImageMask",
    "LocalShell",
]

WebSearchTool = web_search_tool_param.WebSearchToolParam
WebSearchToolFilters = web_search_tool_param.Filters
WebSearchToolUserLocation = web_search_tool_param.UserLocation


class McpAllowedToolsMcpToolFilter(TypedDict, total=False):
    """A filter object to specify which tools are allowed."""

    read_only: bool
    """Indicates whether or not a tool modifies data or is read-only.

    If an MCP server is
    [annotated with `readOnlyHint`](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations-readonlyhint),
    it will match this filter.
    """

    tool_names: SequenceNotStr[str]
    """List of allowed tool names."""


McpAllowedTools: TypeAlias = Union[SequenceNotStr[str], McpAllowedToolsMcpToolFilter]


class McpRequireApprovalMcpToolApprovalFilterAlways(TypedDict, total=False):
    """A filter object to specify which tools are allowed."""

    read_only: bool
    """Indicates whether or not a tool modifies data or is read-only.

    If an MCP server is
    [annotated with `readOnlyHint`](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations-readonlyhint),
    it will match this filter.
    """

    tool_names: SequenceNotStr[str]
    """List of allowed tool names."""


class McpRequireApprovalMcpToolApprovalFilterNever(TypedDict, total=False):
    """A filter object to specify which tools are allowed."""

    read_only: bool
    """Indicates whether or not a tool modifies data or is read-only.

    If an MCP server is
    [annotated with `readOnlyHint`](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations-readonlyhint),
    it will match this filter.
    """

    tool_names: SequenceNotStr[str]
    """List of allowed tool names."""


class McpRequireApprovalMcpToolApprovalFilter(TypedDict, total=False):
    """Specify which of the MCP server's tools require approval.

    Can be
    `always`, `never`, or a filter object associated with tools
    that require approval.
    """

    always: McpRequireApprovalMcpToolApprovalFilterAlways
    """A filter object to specify which tools are allowed."""

    never: McpRequireApprovalMcpToolApprovalFilterNever
    """A filter object to specify which tools are allowed."""


McpRequireApproval: TypeAlias = Union[McpRequireApprovalMcpToolApprovalFilter, Literal["always", "never"]]


class Mcp(TypedDict, total=False):
    """
    Give the model access to additional tools via remote Model Context Protocol
    (MCP) servers. [Learn more about MCP](https://platform.openai.com/docs/guides/tools-remote-mcp).
    """

    server_label: Required[str]
    """A label for this MCP server, used to identify it in tool calls."""

    type: Required[Literal["mcp"]]
    """The type of the MCP tool. Always `mcp`."""

    allowed_tools: Optional[McpAllowedTools]
    """List of allowed tool names or a filter object."""

    authorization: str
    """
    An OAuth access token that can be used with a remote MCP server, either with a
    custom MCP server URL or a service connector. Your application must handle the
    OAuth authorization flow and provide the token here.
    """

    connector_id: Literal[
        "connector_dropbox",
        "connector_gmail",
        "connector_googlecalendar",
        "connector_googledrive",
        "connector_microsoftteams",
        "connector_outlookcalendar",
        "connector_outlookemail",
        "connector_sharepoint",
    ]
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

    headers: Optional[Dict[str, str]]
    """Optional HTTP headers to send to the MCP server.

    Use for authentication or other purposes.
    """

    require_approval: Optional[McpRequireApproval]
    """Specify which of the MCP server's tools require approval."""

    server_description: str
    """Optional description of the MCP server, used to provide more context."""

    server_url: str
    """The URL for the MCP server.

    One of `server_url` or `connector_id` must be provided.
    """


class CodeInterpreterContainerCodeInterpreterToolAuto(TypedDict, total=False):
    """Configuration for a code interpreter container.

    Optionally specify the IDs of the files to run the code on.
    """

    type: Required[Literal["auto"]]
    """Always `auto`."""

    file_ids: SequenceNotStr[str]
    """An optional list of uploaded files to make available to your code."""

    memory_limit: Optional[Literal["1g", "4g", "16g", "64g"]]
    """The memory limit for the code interpreter container."""


CodeInterpreterContainer: TypeAlias = Union[str, CodeInterpreterContainerCodeInterpreterToolAuto]


class CodeInterpreter(TypedDict, total=False):
    """A tool that runs Python code to help generate a response to a prompt."""

    container: Required[CodeInterpreterContainer]
    """The code interpreter container.

    Can be a container ID or an object that specifies uploaded file IDs to make
    available to your code, along with an optional `memory_limit` setting.
    """

    type: Required[Literal["code_interpreter"]]
    """The type of the code interpreter tool. Always `code_interpreter`."""


class ImageGenerationInputImageMask(TypedDict, total=False):
    """Optional mask for inpainting.

    Contains `image_url`
    (string, optional) and `file_id` (string, optional).
    """

    file_id: str
    """File ID for the mask image."""

    image_url: str
    """Base64-encoded mask image."""


class ImageGeneration(TypedDict, total=False):
    """A tool that generates images using the GPT image models."""

    type: Required[Literal["image_generation"]]
    """The type of the image generation tool. Always `image_generation`."""

    background: Literal["transparent", "opaque", "auto"]
    """Background type for the generated image.

    One of `transparent`, `opaque`, or `auto`. Default: `auto`.
    """

    input_fidelity: Optional[Literal["high", "low"]]
    """
    Control how much effort the model will exert to match the style and features,
    especially facial features, of input images. This parameter is only supported
    for `gpt-image-1`. Unsupported for `gpt-image-1-mini`. Supports `high` and
    `low`. Defaults to `low`.
    """

    input_image_mask: ImageGenerationInputImageMask
    """Optional mask for inpainting.

    Contains `image_url` (string, optional) and `file_id` (string, optional).
    """

    model: Union[str, Literal["gpt-image-1", "gpt-image-1-mini"]]
    """The image generation model to use. Default: `gpt-image-1`."""

    moderation: Literal["auto", "low"]
    """Moderation level for the generated image. Default: `auto`."""

    output_compression: int
    """Compression level for the output image. Default: 100."""

    output_format: Literal["png", "webp", "jpeg"]
    """The output format of the generated image.

    One of `png`, `webp`, or `jpeg`. Default: `png`.
    """

    partial_images: int
    """
    Number of partial images to generate in streaming mode, from 0 (default value)
    to 3.
    """

    quality: Literal["low", "medium", "high", "auto"]
    """The quality of the generated image.

    One of `low`, `medium`, `high`, or `auto`. Default: `auto`.
    """

    size: Literal["1024x1024", "1024x1536", "1536x1024", "auto"]
    """The size of the generated image.

    One of `1024x1024`, `1024x1536`, `1536x1024`, or `auto`. Default: `auto`.
    """


class LocalShell(TypedDict, total=False):
    """A tool that allows the model to execute shell commands in a local environment."""

    type: Required[Literal["local_shell"]]
    """The type of the local shell tool. Always `local_shell`."""


ToolParam: TypeAlias = Union[
    FunctionToolParam,
    FileSearchToolParam,
    ComputerToolParam,
    WebSearchToolParam,
    Mcp,
    CodeInterpreter,
    ImageGeneration,
    LocalShell,
    FunctionShellToolParam,
    CustomToolParam,
    WebSearchPreviewToolParam,
    ApplyPatchToolParam,
]


ParseableToolParam: TypeAlias = Union[ToolParam, ChatCompletionFunctionToolParam]
