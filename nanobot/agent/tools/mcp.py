"""MCP client: connects to MCP servers and wraps their tools as native nanobot tools."""

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


def _extract_nullable_branch(options: Any) -> tuple[dict[str, Any], bool] | None:
    """Return the single non-null branch for nullable unions."""
    if not isinstance(options, list):
        return None

    non_null: list[dict[str, Any]] = []
    saw_null = False
    for option in options:
        if not isinstance(option, dict):
            return None
        if option.get("type") == "null":
            saw_null = True
            continue
        non_null.append(option)

    if saw_null and len(non_null) == 1:
        return non_null[0], True
    return None


def _normalize_schema_for_openai(schema: Any) -> dict[str, Any]:
    """Normalize only nullable JSON Schema patterns for tool definitions."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    normalized = dict(schema)

    raw_type = normalized.get("type")
    if isinstance(raw_type, list):
        non_null = [item for item in raw_type if item != "null"]
        if "null" in raw_type and len(non_null) == 1:
            normalized["type"] = non_null[0]
            normalized["nullable"] = True

    for key in ("oneOf", "anyOf"):
        nullable_branch = _extract_nullable_branch(normalized.get(key))
        if nullable_branch is not None:
            branch, _ = nullable_branch
            merged = {k: v for k, v in normalized.items() if k != key}
            merged.update(branch)
            normalized = merged
            normalized["nullable"] = True
            break

    if "properties" in normalized and isinstance(normalized["properties"], dict):
        normalized["properties"] = {
            name: _normalize_schema_for_openai(prop)
            if isinstance(prop, dict)
            else prop
            for name, prop in normalized["properties"].items()
        }

    if "items" in normalized and isinstance(normalized["items"], dict):
        normalized["items"] = _normalize_schema_for_openai(normalized["items"])

    if normalized.get("type") != "object":
        return normalized

    normalized.setdefault("properties", {})
    normalized.setdefault("required", [])
    return normalized


class MCPToolWrapper(Tool):
    """Wraps a single MCP server tool as a nanobot Tool."""

    def __init__(self, session, server_name: str, tool_def, tool_timeout: int = 30):
        self._session = session
        self._original_name = tool_def.name
        self._name = f"mcp_{server_name}_{tool_def.name}"
        self._description = tool_def.description or tool_def.name
        raw_schema = tool_def.inputSchema or {"type": "object", "properties": {}}
        self._parameters = _normalize_schema_for_openai(raw_schema)
        self._tool_timeout = tool_timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        from mcp import types

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(self._original_name, arguments=kwargs),
                timeout=self._tool_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("MCP tool '{}' timed out after {}s", self._name, self._tool_timeout)
            return f"(MCP tool call timed out after {self._tool_timeout}s)"
        except asyncio.CancelledError:
            # MCP SDK's anyio cancel scopes can leak CancelledError on timeout/failure.
            # Re-raise only if our task was externally cancelled (e.g. /stop).
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            logger.warning("MCP tool '{}' was cancelled by server/SDK", self._name)
            return "(MCP tool call was cancelled)"
        except Exception as exc:
            logger.exception(
                "MCP tool '{}' failed: {}: {}",
                self._name,
                type(exc).__name__,
                exc,
            )
            return f"(MCP tool call failed: {type(exc).__name__})"

        parts = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"


_MCP_TOOL_PREFIX = "mcp_"


async def _register_server_tools(
    session: object, name: str, cfg: object, registry: ToolRegistry
) -> int:
    """List tools from one MCP server session and register them.

    Returns the number of tools registered.
    """
    tools = await session.list_tools()
    enabled_tools = set(cfg.enabled_tools)
    allow_all_tools = "*" in enabled_tools
    registered_count = 0
    matched_enabled_tools: set[str] = set()
    available_raw_names = [td.name for td in tools.tools]
    available_wrapped_names = [
        f"mcp_{name}_{td.name}" for td in tools.tools
    ]
    for tool_def in tools.tools:
        wrapped_name = f"mcp_{name}_{tool_def.name}"
        if (
            not allow_all_tools
            and tool_def.name not in enabled_tools
            and wrapped_name not in enabled_tools
        ):
            logger.debug(
                "MCP: skipping tool '{}' from server '{}' (not in enabledTools)",
                wrapped_name,
                name,
            )
            continue
        wrapper = MCPToolWrapper(
            session, name, tool_def, tool_timeout=cfg.tool_timeout
        )
        registry.register(wrapper)
        logger.debug(
            "MCP: registered tool '{}' from server '{}'",
            wrapper.name,
            name,
        )
        registered_count += 1
        if enabled_tools:
            if tool_def.name in enabled_tools:
                matched_enabled_tools.add(tool_def.name)
            if wrapped_name in enabled_tools:
                matched_enabled_tools.add(wrapped_name)

    if enabled_tools and not allow_all_tools:
        unmatched = sorted(enabled_tools - matched_enabled_tools)
        if unmatched:
            logger.warning(
                "MCP server '{}': enabledTools entries not found: {}. "
                "Available raw names: {}. "
                "Available wrapped names: {}",
                name,
                ", ".join(unmatched),
                ", ".join(available_raw_names) or "(none)",
                ", ".join(available_wrapped_names) or "(none)",
            )
    return registered_count


async def refresh_mcp_tools(
    servers: dict[str, tuple[object, object]],
    registry: ToolRegistry,
) -> None:
    """Re-enumerate tools from all connected MCP servers and rebuild the registry."""
    registry.unregister_by_prefix(_MCP_TOOL_PREFIX)
    for name, (session, cfg) in servers.items():
        try:
            count = await _register_server_tools(session, name, cfg, registry)
            logger.info(
                "MCP server '{}': refreshed, {} tools registered", name, count
            )
        except Exception as e:
            logger.error(
                "MCP server '{}': failed to refresh tools: {}", name, e
            )
    logger.info("MCP tools refreshed across {} server(s)", len(servers))


def setup_tools_list_changed_handler(
    servers: dict[str, tuple[object, object]],
    registry: ToolRegistry,
    lock: asyncio.Lock,
) -> None:
    """Register ``notifications/tools/list_changed`` handlers on every session.

    When any server fires the notification the *lock* is acquired and
    :func:`refresh_mcp_tools` is called for **all** servers so the registry
    stays consistent.
    """

    async def _on_tools_list_changed(*_args: object, **_kwargs: object) -> None:
        async with lock:
            await refresh_mcp_tools(servers, registry)

    for _name, (session, _cfg) in servers.items():
        # Store the callback so callers (and tests) can trigger it.
        session._on_tools_list_changed = _on_tools_list_changed  # type: ignore[attr-defined]

        # If the MCP SDK session exposes ``on_notification``, wire it up.
        if callable(getattr(session, "on_notification", None)):
            session.on_notification(
                "notifications/tools/list_changed",
                _on_tools_list_changed,
            )


async def connect_mcp_servers(
    mcp_servers: dict,
    registry: ToolRegistry,
    stack: AsyncExitStack,
) -> dict[str, tuple[object, object]]:
    """Connect to configured MCP servers and register their tools.

    Returns a mapping of ``{server_name: (session, config)}`` for every
    server that connected successfully.  This dict is also used by
    :func:`setup_tools_list_changed_handler` and :func:`refresh_mcp_tools`.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    connected: dict[str, tuple[object, object]] = {}

    for name, cfg in mcp_servers.items():
        try:
            transport_type = cfg.type
            if not transport_type:
                if cfg.command:
                    transport_type = "stdio"
                elif cfg.url:
                    transport_type = (
                        "sse"
                        if cfg.url.rstrip("/").endswith("/sse")
                        else "streamableHttp"
                    )
                else:
                    logger.warning(
                        "MCP server '{}': no command or url configured, "
                        "skipping",
                        name,
                    )
                    continue

            if transport_type == "stdio":
                params = StdioServerParameters(
                    command=cfg.command, args=cfg.args, env=cfg.env or None
                )
                read, write = await stack.enter_async_context(
                    stdio_client(params)
                )
            elif transport_type == "sse":
                def httpx_client_factory(
                    headers: dict[str, str] | None = None,
                    timeout: httpx.Timeout | None = None,
                    auth: httpx.Auth | None = None,
                ) -> httpx.AsyncClient:
                    merged_headers = {
                        "Accept": "application/json, text/event-stream",
                        **(cfg.headers or {}),
                        **(headers or {}),
                    }
                    return httpx.AsyncClient(
                        headers=merged_headers or None,
                        follow_redirects=True,
                        timeout=timeout,
                        auth=auth,
                    )

                read, write = await stack.enter_async_context(
                    sse_client(
                        cfg.url,
                        httpx_client_factory=httpx_client_factory,
                    )
                )
            elif transport_type == "streamableHttp":
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=cfg.headers or None,
                        follow_redirects=True,
                        timeout=None,
                    )
                )
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(cfg.url, http_client=http_client)
                )
            else:
                logger.warning(
                    "MCP server '{}': unknown transport type '{}'",
                    name,
                    transport_type,
                )
                continue

            session = await stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()

            count = await _register_server_tools(
                session, name, cfg, registry
            )
            connected[name] = (session, cfg)

            logger.info(
                "MCP server '{}': connected, {} tools registered",
                name,
                count,
            )
        except Exception as e:
            logger.error("MCP server '{}': failed to connect: {}", name, e)

    # Set up live-refresh notification handlers for all connected servers.
    if connected:
        lock = asyncio.Lock()
        setup_tools_list_changed_handler(connected, registry, lock)

    return connected
