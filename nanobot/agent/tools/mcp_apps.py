"""Explicit backend access to an MCP App on its originating connection."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from email.message import Message
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from pydantic import AnyUrl

from nanobot.agent.tools.mcp_result import snapshot_mcp_json

if TYPE_CHECKING:
    from mcp import ClientSession, types

_APP_MIME_TYPE = "text/html;profile=mcp-app"
_MAX_HTML_BYTES = 1024 * 1024
_MAX_MESSAGE_BYTES = 64 * 1024


@dataclass(frozen=True)
class MCPAppToolCall:
    """Source-bound request presented to a trusted backend approval policy."""

    server_name: str
    tool_name: str
    arguments: dict[str, Any]


MCPAppAuthorization = Callable[[MCPAppToolCall], Awaitable[bool]]


@dataclass(frozen=True)
class MCPAppResource:
    uri: str
    html: str
    meta: dict[str, Any]


def _app_visible(tool: types.Tool) -> bool:
    ui = (tool.meta or {}).get("ui")
    if not isinstance(ui, dict):
        return True
    visibility: object = cast(dict[str, Any], ui).get("visibility")
    return visibility is None or (isinstance(visibility, list) and "app" in visibility)


@dataclass
class _AppConnection:
    session: ClientSession
    server_name: str
    tools: dict[str, types.Tool]
    timeout: float
    closed: bool = False

    def require_open(self) -> None:
        if self.closed:
            raise RuntimeError("The originating MCP connection is closed; reopen the app")


class MCPAppServer:
    """An allowlisted catalog bound to one live MCP connection.

    Constructed by connection discovery, not from app-provided server names.
    Closing a connection revokes all app sessions opened against this catalog.
    """

    def __init__(
        self,
        session: ClientSession,
        server_name: str,
        tools: Mapping[str, types.Tool],
        *,
        timeout: float = 30,
    ) -> None:
        self._connection = _AppConnection(session, server_name, dict(tools), timeout)

    def close(self) -> None:
        self._connection.closed = True

    def open_app(
        self,
        tool_name: str,
        *,
        authorize: MCPAppAuthorization,
    ) -> MCPAppSession:
        """Bind a declared UI resource and a host-owned authorization policy."""
        self._connection.require_open()
        definition = self._connection.tools.get(tool_name)
        if definition is None:
            raise ValueError("The originating tool is unavailable")
        ui = (definition.meta or {}).get("ui")
        uri: object = cast(dict[str, Any], ui).get("resourceUri") if isinstance(ui, dict) else None
        if not isinstance(uri, str) or len(uri) > 4096 or urlsplit(uri).scheme != "ui":
            raise ValueError("The originating tool does not declare a ui:// resource")
        return MCPAppSession(self._connection, AnyUrl(uri), authorize)


class MCPAppSession:
    """Backend bridge with a fixed resource and same-server tool access.

    This object is not a browser wire protocol. The host must bind it to its
    authenticated chat and hold its authorization callback outside app control.
    """

    def __init__(
        self,
        connection: _AppConnection,
        resource_uri: AnyUrl,
        authorize: MCPAppAuthorization,
    ) -> None:
        self._connection = connection
        self._resource_uri = resource_uri
        self._authorize = authorize
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("The MCP app session is closed")
        self._connection.require_open()

    async def read_resource(self) -> MCPAppResource:
        """Read only the UI declared by the originating tool, with bounded HTML."""
        from mcp import types

        self._require_open()
        result = await asyncio.wait_for(
            self._connection.session.read_resource(self._resource_uri),
            timeout=self._connection.timeout,
        )
        self._require_open()
        if len(result.contents) != 1:
            raise ValueError("An MCP App resource must contain exactly one HTML document")
        resource = result.contents[0]
        if str(resource.uri) != str(self._resource_uri):
            raise ValueError("The MCP App response URI does not match the declared resource")
        mime = Message()
        mime["content-type"] = resource.mimeType or ""
        if mime.get_content_type() != "text/html" or mime.get_param("profile") != "mcp-app":
            raise ValueError(f"The MCP App resource must use {_APP_MIME_TYPE}")
        if isinstance(resource, types.TextResourceContents):
            if len(resource.text) > _MAX_HTML_BYTES:
                raise ValueError("The MCP App HTML exceeds the 1 MiB limit")
            html_bytes = resource.text.encode("utf-8")
        else:
            if len(resource.blob) > 4 * ((_MAX_HTML_BYTES + 2) // 3):
                raise ValueError("The MCP App HTML exceeds the 1 MiB limit")
            html_bytes = base64.b64decode(resource.blob, validate=True)
        if len(html_bytes) > _MAX_HTML_BYTES:
            raise ValueError("The MCP App HTML exceeds the 1 MiB limit")
        meta = resource.meta or {}
        return MCPAppResource(
            uri=str(resource.uri),
            html=html_bytes.decode("utf-8"),
            meta=snapshot_mcp_json(meta, _MAX_MESSAGE_BYTES),
        )

    def prepare_tool_call(self, name: str, arguments: object) -> MCPAppToolCall:
        """Validate a source-bound call without dispatching it or granting approval."""
        self._require_open()
        definition = self._connection.tools.get(name)
        if definition is None or not _app_visible(definition):
            raise PermissionError("The tool is not available to this MCP app")
        if not isinstance(arguments, dict):
            raise ValueError("MCP App tool arguments must be a JSON object")
        params: dict[str, Any] = snapshot_mcp_json(arguments, _MAX_MESSAGE_BYTES)
        return MCPAppToolCall(
            server_name=self._connection.server_name,
            tool_name=name,
            arguments=snapshot_mcp_json(params, _MAX_MESSAGE_BYTES),
        )

    async def call_tool(self, name: str, arguments: object) -> types.CallToolResult:
        """Authorize one app-visible tool; never retry a possibly committed call."""
        request = self.prepare_tool_call(name, arguments)
        params = snapshot_mcp_json(request.arguments, _MAX_MESSAGE_BYTES)
        if await self._authorize(request) is not True:
            raise PermissionError("MCP App tool execution was not approved")
        self._require_open()
        result = await asyncio.wait_for(
            self._connection.session.call_tool(name, arguments=params),
            timeout=self._connection.timeout,
        )
        self._require_open()
        try:
            snapshot_mcp_json(result.model_dump(by_alias=True), _MAX_MESSAGE_BYTES)
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise ValueError(
                "The tool finished, but its result cannot be rendered within the JSON limits; "
                "do not retry the action"
            ) from exc
        return result
