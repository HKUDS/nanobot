# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel
from .realtime_mcphttp_error import RealtimeMcphttpError
from .realtime_mcp_protocol_error import RealtimeMcpProtocolError
from .realtime_mcp_tool_execution_error import RealtimeMcpToolExecutionError

__all__ = ["RealtimeMcpToolCall", "Error"]

Error: TypeAlias = Annotated[
    Union[RealtimeMcpProtocolError, RealtimeMcpToolExecutionError, RealtimeMcphttpError, None],
    PropertyInfo(discriminator="type"),
]


class RealtimeMcpToolCall(BaseModel):
    """A Realtime item representing an invocation of a tool on an MCP server."""

    id: str
    """The unique ID of the tool call."""

    arguments: str
    """A JSON string of the arguments passed to the tool."""

    name: str
    """The name of the tool that was run."""

    server_label: str
    """The label of the MCP server running the tool."""

    type: Literal["mcp_call"]
    """The type of the item. Always `mcp_call`."""

    approval_request_id: Optional[str] = None
    """The ID of an associated approval request, if any."""

    error: Optional[Error] = None
    """The error from the tool call, if any."""

    output: Optional[str] = None
    """The output from the tool call."""
