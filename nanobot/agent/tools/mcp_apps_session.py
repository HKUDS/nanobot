"""MCP Apps capability declaration for an explicitly enabled browser host."""

from datetime import timedelta
from typing import TypeVar

from mcp import ClientSession, types
from mcp.shared.message import ClientMessageMetadata, ServerMessageMetadata
from mcp.shared.session import ProgressFnT
from pydantic import BaseModel

_ResultT = TypeVar("_ResultT", bound=BaseModel)


class MCPAppsClientSession(ClientSession):
    async def send_request(
        self,
        request: types.ClientRequest,
        result_type: type[_ResultT],
        request_read_timeout_seconds: timedelta | None = None,
        metadata: ClientMessageMetadata | ServerMessageMetadata | None = None,
        progress_callback: ProgressFnT | None = None,
    ) -> _ResultT:
        if isinstance(request.root, types.InitializeRequest):
            initialization = request.root.model_copy(deep=True)
            capabilities = initialization.params.capabilities
            initialization.params.capabilities = types.ClientCapabilities.model_validate({
                **capabilities.model_dump(exclude_none=True),
                "extensions": {
                    "io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]},
                },
            })
            request = types.ClientRequest(initialization)
        return await super().send_request(
            request, result_type, request_read_timeout_seconds, metadata, progress_callback,
        )
