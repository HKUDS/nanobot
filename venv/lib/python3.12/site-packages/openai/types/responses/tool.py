# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Dict, List, Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from . import web_search_tool
from ..._utils import PropertyInfo
from ..._models import BaseModel
from .custom_tool import CustomTool
from .computer_tool import ComputerTool
from .function_tool import FunctionTool
from .web_search_tool import WebSearchTool
from .apply_patch_tool import ApplyPatchTool
from .file_search_tool import FileSearchTool
from .function_shell_tool import FunctionShellTool
from .web_search_preview_tool import WebSearchPreviewTool

__all__ = [
    "Tool",
    "WebSearchTool",
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

WebSearchToolFilters = web_search_tool.Filters
WebSearchToolUserLocation = web_search_tool.UserLocation


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


class CodeInterpreterContainerCodeInterpreterToolAuto(BaseModel):
    """Configuration for a code interpreter container.

    Optionally specify the IDs of the files to run the code on.
    """

    type: Literal["auto"]
    """Always `auto`."""

    file_ids: Optional[List[str]] = None
    """An optional list of uploaded files to make available to your code."""

    memory_limit: Optional[Literal["1g", "4g", "16g", "64g"]] = None
    """The memory limit for the code interpreter container."""


CodeInterpreterContainer: TypeAlias = Union[str, CodeInterpreterContainerCodeInterpreterToolAuto]


class CodeInterpreter(BaseModel):
    """A tool that runs Python code to help generate a response to a prompt."""

    container: CodeInterpreterContainer
    """The code interpreter container.

    Can be a container ID or an object that specifies uploaded file IDs to make
    available to your code, along with an optional `memory_limit` setting.
    """

    type: Literal["code_interpreter"]
    """The type of the code interpreter tool. Always `code_interpreter`."""


class ImageGenerationInputImageMask(BaseModel):
    """Optional mask for inpainting.

    Contains `image_url`
    (string, optional) and `file_id` (string, optional).
    """

    file_id: Optional[str] = None
    """File ID for the mask image."""

    image_url: Optional[str] = None
    """Base64-encoded mask image."""


class ImageGeneration(BaseModel):
    """A tool that generates images using the GPT image models."""

    type: Literal["image_generation"]
    """The type of the image generation tool. Always `image_generation`."""

    background: Optional[Literal["transparent", "opaque", "auto"]] = None
    """Background type for the generated image.

    One of `transparent`, `opaque`, or `auto`. Default: `auto`.
    """

    input_fidelity: Optional[Literal["high", "low"]] = None
    """
    Control how much effort the model will exert to match the style and features,
    especially facial features, of input images. This parameter is only supported
    for `gpt-image-1`. Unsupported for `gpt-image-1-mini`. Supports `high` and
    `low`. Defaults to `low`.
    """

    input_image_mask: Optional[ImageGenerationInputImageMask] = None
    """Optional mask for inpainting.

    Contains `image_url` (string, optional) and `file_id` (string, optional).
    """

    model: Union[str, Literal["gpt-image-1", "gpt-image-1-mini"], None] = None
    """The image generation model to use. Default: `gpt-image-1`."""

    moderation: Optional[Literal["auto", "low"]] = None
    """Moderation level for the generated image. Default: `auto`."""

    output_compression: Optional[int] = None
    """Compression level for the output image. Default: 100."""

    output_format: Optional[Literal["png", "webp", "jpeg"]] = None
    """The output format of the generated image.

    One of `png`, `webp`, or `jpeg`. Default: `png`.
    """

    partial_images: Optional[int] = None
    """
    Number of partial images to generate in streaming mode, from 0 (default value)
    to 3.
    """

    quality: Optional[Literal["low", "medium", "high", "auto"]] = None
    """The quality of the generated image.

    One of `low`, `medium`, `high`, or `auto`. Default: `auto`.
    """

    size: Optional[Literal["1024x1024", "1024x1536", "1536x1024", "auto"]] = None
    """The size of the generated image.

    One of `1024x1024`, `1024x1536`, `1536x1024`, or `auto`. Default: `auto`.
    """


class LocalShell(BaseModel):
    """A tool that allows the model to execute shell commands in a local environment."""

    type: Literal["local_shell"]
    """The type of the local shell tool. Always `local_shell`."""


Tool: TypeAlias = Annotated[
    Union[
        FunctionTool,
        FileSearchTool,
        ComputerTool,
        WebSearchTool,
        Mcp,
        CodeInterpreter,
        ImageGeneration,
        LocalShell,
        FunctionShellTool,
        CustomTool,
        WebSearchPreviewTool,
        ApplyPatchTool,
    ],
    PropertyInfo(discriminator="type"),
]
