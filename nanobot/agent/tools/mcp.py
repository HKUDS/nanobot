"""MCP client: connects to MCP servers and wraps their tools as native nanobot tools."""

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


def _normalize_schema_for_openai(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize JSON Schema for OpenAI-compatible providers.
    
    OpenAI's API (and many compatible providers) only supports a subset of JSON Schema:
    - Top-level type must be 'object'
    - No oneOf/anyOf/allOf/enum/not at the top level
    - Properties should have simple types
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    
    # If schema has oneOf/anyOf/allOf at top level, try to extract the first option
    for key in ["oneOf", "anyOf", "allOf"]:
        if key in schema:
            options = schema[key]
            if isinstance(options, list) and len(options) > 0:
                # Use the first option as the base schema
                first_option = options[0]
                if isinstance(first_option, dict):
                    # Merge with other schema properties, preferring the first option
                    normalized = dict(schema)
                    del normalized[key]
                    normalized.update(first_option)
                    return _normalize_schema_for_openai(normalized)
    
    # Ensure top-level type is object
    if schema.get("type") != "object":
        # If no type specified or different type, default to object
        schema = {"type": "object", **{k: v for k, v in schema.items() if k != "type"}}
    
    # Clean up unsupported properties at top level
    unsupported = ["enum", "not", "const"]
    for key in unsupported:
        schema.pop(key, None)
    
    # Ensure properties and required exist
    if "properties" not in schema:
        schema["properties"] = {}
    if "required" not in schema:
        schema["required"] = []
    
    # Recursively normalize nested property schemas
    if "properties" in schema and isinstance(schema["properties"], dict):
        for prop_name, prop_schema in schema["properties"].items():
            if isinstance(prop_schema, dict):
                schema["properties"][prop_name] = _normalize_property_schema(prop_schema)
    
    return schema


def _normalize_property_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize a property schema for OpenAI compatibility."""
    if not isinstance(schema, dict):
        return {"type": "string"}
    
    # Handle oneOf/anyOf in properties
    for key in ["oneOf", "anyOf"]:
        if key in schema:
            options = schema[key]
            if isinstance(options, list) and len(options) > 0:
                first_option = options[0]
                if isinstance(first_option, dict):
                    # Replace the complex schema with the first option
                    result = {k: v for k, v in schema.items() if k not in [key, "allOf", "not"]}
                    result.update(first_option)
                    return _normalize_property_schema(result)
    
    # Handle allOf by merging all subschemas
    if "allOf" in schema:
        subschemas = schema["allOf"]
        if isinstance(subschemas, list):
            merged = {}
            for sub in subschemas:
                if isinstance(sub, dict):
                    merged.update(sub)
            # Remove allOf and merge with other properties
            result = {k: v for k, v in schema.items() if k != "allOf"}
            result.update(merged)
            return _normalize_property_schema(result)
    
    # Ensure type is simple
    if "type" not in schema:
        # Try to infer type from other properties
        if "enum" in schema:
            schema["type"] = "string"
        elif "properties" in schema:
            schema["type"] = "object"
        elif "items" in schema:
            schema["type"] = "array"
        else:
            schema["type"] = "string"
    
    # Clean up not/const
    schema.pop("not", None)
    schema.pop("const", None)
    
    return schema


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


async def connect_mcp_servers(
    mcp_servers: dict, registry: ToolRegistry, stack: AsyncExitStack
) -> None:
    """Connect to configured MCP servers and register their tools."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    for name, cfg in mcp_servers.items():
        try:
            transport_type = cfg.type
            if not transport_type:
                if cfg.command:
                    transport_type = "stdio"
                elif cfg.url:
                    # Convention: URLs ending with /sse use SSE transport; others use streamableHttp
                    transport_type = (
                        "sse" if cfg.url.rstrip("/").endswith("/sse") else "streamableHttp"
                    )
                else:
                    logger.warning("MCP server '{}': no command or url configured, skipping", name)
                    continue

            if transport_type == "stdio":
                params = StdioServerParameters(
                    command=cfg.command, args=cfg.args, env=cfg.env or None
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif transport_type == "sse":
                def httpx_client_factory(
                    headers: dict[str, str] | None = None,
                    timeout: httpx.Timeout | None = None,
                    auth: httpx.Auth | None = None,
                ) -> httpx.AsyncClient:
                    merged_headers = {**(cfg.headers or {}), **(headers or {})}
                    return httpx.AsyncClient(
                        headers=merged_headers or None,
                        follow_redirects=True,
                        timeout=timeout,
                        auth=auth,
                    )

                read, write = await stack.enter_async_context(
                    sse_client(cfg.url, httpx_client_factory=httpx_client_factory)
                )
            elif transport_type == "streamableHttp":
                # Always provide an explicit httpx client so MCP HTTP transport does not
                # inherit httpx's default 5s timeout and preempt the higher-level tool timeout.
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
                logger.warning("MCP server '{}': unknown transport type '{}'", name, transport_type)
                continue

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            tools = await session.list_tools()
            enabled_tools = set(cfg.enabled_tools)
            allow_all_tools = "*" in enabled_tools
            registered_count = 0
            matched_enabled_tools: set[str] = set()
            available_raw_names = [tool_def.name for tool_def in tools.tools]
            available_wrapped_names = [f"mcp_{name}_{tool_def.name}" for tool_def in tools.tools]
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
                wrapper = MCPToolWrapper(session, name, tool_def, tool_timeout=cfg.tool_timeout)
                registry.register(wrapper)
                logger.debug("MCP: registered tool '{}' from server '{}'", wrapper.name, name)
                registered_count += 1
                if enabled_tools:
                    if tool_def.name in enabled_tools:
                        matched_enabled_tools.add(tool_def.name)
                    if wrapped_name in enabled_tools:
                        matched_enabled_tools.add(wrapped_name)

            if enabled_tools and not allow_all_tools:
                unmatched_enabled_tools = sorted(enabled_tools - matched_enabled_tools)
                if unmatched_enabled_tools:
                    logger.warning(
                        "MCP server '{}': enabledTools entries not found: {}. Available raw names: {}. "
                        "Available wrapped names: {}",
                        name,
                        ", ".join(unmatched_enabled_tools),
                        ", ".join(available_raw_names) or "(none)",
                        ", ".join(available_wrapped_names) or "(none)",
                    )

            logger.info("MCP server '{}': connected, {} tools registered", name, registered_count)
        except Exception as e:
            logger.error("MCP server '{}': failed to connect: {}", name, e)
