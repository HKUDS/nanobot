"""
SessionGroup concurrently manages multiple MCP session connections.

Tools, resources, and prompts are aggregated across servers. Servers may
be connected to or disconnected from at any point after initialization.

This abstractions can handle naming collisions using a custom user-provided
hook.
"""

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from types import TracebackType
from typing import Any, TypeAlias, overload

import anyio
import httpx
from pydantic import BaseModel
from typing_extensions import Self, deprecated

import mcp
from mcp import types
from mcp.client.session import ElicitationFnT, ListRootsFnT, LoggingFnT, MessageHandlerFnT, SamplingFnT
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.exceptions import McpError
from mcp.shared.session import ProgressFnT


class SseServerParameters(BaseModel):
    """Parameters for intializing a sse_client."""

    # The endpoint URL.
    url: str

    # Optional headers to include in requests.
    headers: dict[str, Any] | None = None

    # HTTP timeout for regular operations.
    timeout: float = 5

    # Timeout for SSE read operations.
    sse_read_timeout: float = 60 * 5


class StreamableHttpParameters(BaseModel):
    """Parameters for intializing a streamable_http_client."""

    # The endpoint URL.
    url: str

    # Optional headers to include in requests.
    headers: dict[str, Any] | None = None

    # HTTP timeout for regular operations.
    timeout: timedelta = timedelta(seconds=30)

    # Timeout for SSE read operations.
    sse_read_timeout: timedelta = timedelta(seconds=60 * 5)

    # Close the client session when the transport closes.
    terminate_on_close: bool = True


ServerParameters: TypeAlias = StdioServerParameters | SseServerParameters | StreamableHttpParameters


# Use dataclass instead of pydantic BaseModel
# because pydantic BaseModel cannot handle Protocol fields.
@dataclass
class ClientSessionParameters:
    """Parameters for establishing a client session to an MCP server."""

    read_timeout_seconds: timedelta | None = None
    sampling_callback: SamplingFnT | None = None
    elicitation_callback: ElicitationFnT | None = None
    list_roots_callback: ListRootsFnT | None = None
    logging_callback: LoggingFnT | None = None
    message_handler: MessageHandlerFnT | None = None
    client_info: types.Implementation | None = None


class ClientSessionGroup:
    """Client for managing connections to multiple MCP servers.

    This class is responsible for encapsulating management of server connections.
    It aggregates tools, resources, and prompts from all connected servers.

    For auxiliary handlers, such as resource subscription, this is delegated to
    the client and can be accessed via the session.

    Example Usage:
        name_fn = lambda name, server_info: f"{(server_info.name)}_{name}"
        async with ClientSessionGroup(component_name_hook=name_fn) as group:
            for server_param in server_params:
                await group.connect_to_server(server_param)
            ...

    """

    class _ComponentNames(BaseModel):
        """Used for reverse index to find components."""

        prompts: set[str] = set()
        resources: set[str] = set()
        tools: set[str] = set()

    # Standard MCP components.
    _prompts: dict[str, types.Prompt]
    _resources: dict[str, types.Resource]
    _tools: dict[str, types.Tool]

    # Client-server connection management.
    _sessions: dict[mcp.ClientSession, _ComponentNames]
    _tool_to_session: dict[str, mcp.ClientSession]
    _exit_stack: contextlib.AsyncExitStack
    _session_exit_stacks: dict[mcp.ClientSession, contextlib.AsyncExitStack]

    # Optional fn consuming (component_name, serverInfo) for custom names.
    # This is provide a means to mitigate naming conflicts across servers.
    # Example: (tool_name, serverInfo) => "{result.serverInfo.name}.{tool_name}"
    _ComponentNameHook: TypeAlias = Callable[[str, types.Implementation], str]
    _component_name_hook: _ComponentNameHook | None

    def __init__(
        self,
        exit_stack: contextlib.AsyncExitStack | None = None,
        component_name_hook: _ComponentNameHook | None = None,
    ) -> None:
        """Initializes the MCP client."""

        self._tools = {}
        self._resources = {}
        self._prompts = {}

        self._sessions = {}
        self._tool_to_session = {}
        if exit_stack is None:
            self._exit_stack = contextlib.AsyncExitStack()
            self._owns_exit_stack = True
        else:
            self._exit_stack = exit_stack
            self._owns_exit_stack = False
        self._session_exit_stacks = {}
        self._component_name_hook = component_name_hook

    async def __aenter__(self) -> Self:  # pragma: no cover
        # Enter the exit stack only if we created it ourselves
        if self._owns_exit_stack:
            await self._exit_stack.__aenter__()
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> bool | None:  # pragma: no cover
        """Closes session exit stacks and main exit stack upon completion."""

        # Only close the main exit stack if we created it
        if self._owns_exit_stack:
            await self._exit_stack.aclose()

        # Concurrently close session stacks.
        async with anyio.create_task_group() as tg:
            for exit_stack in self._session_exit_stacks.values():
                tg.start_soon(exit_stack.aclose)

    @property
    def sessions(self) -> list[mcp.ClientSession]:
        """Returns the list of sessions being managed."""
        return list(self._sessions.keys())  # pragma: no cover

    @property
    def prompts(self) -> dict[str, types.Prompt]:
        """Returns the prompts as a dictionary of names to prompts."""
        return self._prompts

    @property
    def resources(self) -> dict[str, types.Resource]:
        """Returns the resources as a dictionary of names to resources."""
        return self._resources

    @property
    def tools(self) -> dict[str, types.Tool]:
        """Returns the tools as a dictionary of names to tools."""
        return self._tools

    @overload
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        read_timeout_seconds: timedelta | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        meta: dict[str, Any] | None = None,
    ) -> types.CallToolResult: ...

    @overload
    @deprecated("The 'args' parameter is deprecated. Use 'arguments' instead.")
    async def call_tool(
        self,
        name: str,
        *,
        args: dict[str, Any],
        read_timeout_seconds: timedelta | None = None,
        progress_callback: ProgressFnT | None = None,
        meta: dict[str, Any] | None = None,
    ) -> types.CallToolResult: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        meta: dict[str, Any] | None = None,
        args: dict[str, Any] | None = None,
    ) -> types.CallToolResult:
        """Executes a tool given its name and arguments."""
        session = self._tool_to_session[name]
        session_tool_name = self.tools[name].name
        return await session.call_tool(
            session_tool_name,
            arguments if args is None else args,
            read_timeout_seconds=read_timeout_seconds,
            progress_callback=progress_callback,
            meta=meta,
        )

    async def disconnect_from_server(self, session: mcp.ClientSession) -> None:
        """Disconnects from a single MCP server."""

        session_known_for_components = session in self._sessions
        session_known_for_stack = session in self._session_exit_stacks

        if not session_known_for_components and not session_known_for_stack:
            raise McpError(
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message="Provided session is not managed or already disconnected.",
                )
            )

        if session_known_for_components:  # pragma: no cover
            component_names = self._sessions.pop(session)  # Pop from _sessions tracking

            # Remove prompts associated with the session.
            for name in component_names.prompts:
                if name in self._prompts:
                    del self._prompts[name]
            # Remove resources associated with the session.
            for name in component_names.resources:
                if name in self._resources:
                    del self._resources[name]
            # Remove tools associated with the session.
            for name in component_names.tools:
                if name in self._tools:
                    del self._tools[name]
                if name in self._tool_to_session:
                    del self._tool_to_session[name]

        # Clean up the session's resources via its dedicated exit stack
        if session_known_for_stack:
            session_stack_to_close = self._session_exit_stacks.pop(session)  # pragma: no cover
            await session_stack_to_close.aclose()  # pragma: no cover

    async def connect_with_session(
        self, server_info: types.Implementation, session: mcp.ClientSession
    ) -> mcp.ClientSession:
        """Connects to a single MCP server."""
        await self._aggregate_components(server_info, session)
        return session

    async def connect_to_server(
        self,
        server_params: ServerParameters,
        session_params: ClientSessionParameters | None = None,
    ) -> mcp.ClientSession:
        """Connects to a single MCP server."""
        server_info, session = await self._establish_session(server_params, session_params or ClientSessionParameters())
        return await self.connect_with_session(server_info, session)

    async def _establish_session(
        self,
        server_params: ServerParameters,
        session_params: ClientSessionParameters,
    ) -> tuple[types.Implementation, mcp.ClientSession]:
        """Establish a client session to an MCP server."""

        session_stack = contextlib.AsyncExitStack()
        try:
            # Create read and write streams that facilitate io with the server.
            if isinstance(server_params, StdioServerParameters):
                client = mcp.stdio_client(server_params)
                read, write = await session_stack.enter_async_context(client)
            elif isinstance(server_params, SseServerParameters):
                client = sse_client(
                    url=server_params.url,
                    headers=server_params.headers,
                    timeout=server_params.timeout,
                    sse_read_timeout=server_params.sse_read_timeout,
                )
                read, write = await session_stack.enter_async_context(client)
            else:
                httpx_client = create_mcp_http_client(
                    headers=server_params.headers,
                    timeout=httpx.Timeout(
                        server_params.timeout.total_seconds(),
                        read=server_params.sse_read_timeout.total_seconds(),
                    ),
                )
                await session_stack.enter_async_context(httpx_client)

                client = streamable_http_client(
                    url=server_params.url,
                    http_client=httpx_client,
                    terminate_on_close=server_params.terminate_on_close,
                )
                read, write, _ = await session_stack.enter_async_context(client)

            session = await session_stack.enter_async_context(
                mcp.ClientSession(
                    read,
                    write,
                    read_timeout_seconds=session_params.read_timeout_seconds,
                    sampling_callback=session_params.sampling_callback,
                    elicitation_callback=session_params.elicitation_callback,
                    list_roots_callback=session_params.list_roots_callback,
                    logging_callback=session_params.logging_callback,
                    message_handler=session_params.message_handler,
                    client_info=session_params.client_info,
                )
            )

            result = await session.initialize()

            # Session successfully initialized.
            # Store its stack and register the stack with the main group stack.
            self._session_exit_stacks[session] = session_stack
            # session_stack itself becomes a resource managed by the
            # main _exit_stack.
            await self._exit_stack.enter_async_context(session_stack)

            return result.serverInfo, session
        except Exception:  # pragma: no cover
            # If anything during this setup fails, ensure the session-specific
            # stack is closed.
            await session_stack.aclose()
            raise

    async def _aggregate_components(self, server_info: types.Implementation, session: mcp.ClientSession) -> None:
        """Aggregates prompts, resources, and tools from a given session."""

        # Create a reverse index so we can find all prompts, resources, and
        # tools belonging to this session. Used for removing components from
        # the session group via self.disconnect_from_server.
        component_names = self._ComponentNames()

        # Temporary components dicts. We do not want to modify the aggregate
        # lists in case of an intermediate failure.
        prompts_temp: dict[str, types.Prompt] = {}
        resources_temp: dict[str, types.Resource] = {}
        tools_temp: dict[str, types.Tool] = {}
        tool_to_session_temp: dict[str, mcp.ClientSession] = {}

        # Query the server for its prompts and aggregate to list.
        try:
            prompts = (await session.list_prompts()).prompts
            for prompt in prompts:
                name = self._component_name(prompt.name, server_info)
                prompts_temp[name] = prompt
                component_names.prompts.add(name)
        except McpError as err:  # pragma: no cover
            logging.warning(f"Could not fetch prompts: {err}")

        # Query the server for its resources and aggregate to list.
        try:
            resources = (await session.list_resources()).resources
            for resource in resources:
                name = self._component_name(resource.name, server_info)
                resources_temp[name] = resource
                component_names.resources.add(name)
        except McpError as err:  # pragma: no cover
            logging.warning(f"Could not fetch resources: {err}")

        # Query the server for its tools and aggregate to list.
        try:
            tools = (await session.list_tools()).tools
            for tool in tools:
                name = self._component_name(tool.name, server_info)
                tools_temp[name] = tool
                tool_to_session_temp[name] = session
                component_names.tools.add(name)
        except McpError as err:  # pragma: no cover
            logging.warning(f"Could not fetch tools: {err}")

        # Clean up exit stack for session if we couldn't retrieve anything
        # from the server.
        if not any((prompts_temp, resources_temp, tools_temp)):
            del self._session_exit_stacks[session]  # pragma: no cover

        # Check for duplicates.
        matching_prompts = prompts_temp.keys() & self._prompts.keys()
        if matching_prompts:
            raise McpError(  # pragma: no cover
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message=f"{matching_prompts} already exist in group prompts.",
                )
            )
        matching_resources = resources_temp.keys() & self._resources.keys()
        if matching_resources:
            raise McpError(  # pragma: no cover
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message=f"{matching_resources} already exist in group resources.",
                )
            )
        matching_tools = tools_temp.keys() & self._tools.keys()
        if matching_tools:
            raise McpError(
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message=f"{matching_tools} already exist in group tools.",
                )
            )

        # Aggregate components.
        self._sessions[session] = component_names
        self._prompts.update(prompts_temp)
        self._resources.update(resources_temp)
        self._tools.update(tools_temp)
        self._tool_to_session.update(tool_to_session_temp)

    def _component_name(self, name: str, server_info: types.Implementation) -> str:
        if self._component_name_hook:
            return self._component_name_hook(name, server_info)
        return name
