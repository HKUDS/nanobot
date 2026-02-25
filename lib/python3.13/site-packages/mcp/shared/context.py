"""
Request context for MCP handlers.
"""

from dataclasses import dataclass, field
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.shared.message import CloseSSEStreamCallback
from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParams

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])
LifespanContextT = TypeVar("LifespanContextT")
RequestT = TypeVar("RequestT", default=Any)


@dataclass
class RequestContext(Generic[SessionT, LifespanContextT, RequestT]):
    request_id: RequestId
    meta: RequestParams.Meta | None
    session: SessionT
    lifespan_context: LifespanContextT
    # NOTE: This is typed as Any to avoid circular imports. The actual type is
    # mcp.server.experimental.request_context.Experimental, but importing it here
    # triggers mcp.server.__init__ -> fastmcp -> tools -> back to this module.
    # The Server sets this to an Experimental instance at runtime.
    experimental: Any = field(default=None)
    request: RequestT | None = None
    close_sse_stream: CloseSSEStreamCallback | None = None
    close_standalone_sse_stream: CloseSSEStreamCallback | None = None
