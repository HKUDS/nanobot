"""MCP client manager: connects to MCP servers and discovers tools."""

from __future__ import annotations

from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport, StdioTransport
from loguru import logger

from nanobot.config.schema import McpConfig, McpServerConfig
from nanobot.mcp.tools import McpToolAdapter


class McpClientManager:
    """
    Manages connections to one or more MCP servers.

    Call :meth:`start` to connect to every *enabled* server listed in the
    config, discover their tools, and create :class:`McpToolAdapter` wrappers.
    Call :meth:`stop` to tear down all connections.
    """

    def __init__(self, config: McpConfig) -> None:
        self._config = config
        self._clients: dict[str, Any] = {}        # server_name -> FastMCP Client
        self._contexts: dict[str, Any] = {}        # server_name -> async-context manager state
        self._tools: list[McpToolAdapter] = []
        self._started = False

    # -- public API -----------------------------------------------------------

    async def start(self) -> list[McpToolAdapter]:
        """Connect to all enabled MCP servers and return discovered tools."""
        if self._started:
            return self._tools

        self._tools = []

        for name, server_cfg in self._config.servers.items():
            if not server_cfg.enabled:
                logger.info(f"MCP server '{name}' is disabled, skipping")
                continue

            try:
                transport = self._build_transport(name, server_cfg)
                client = Client(transport)

                # Enter the async-with context so the connection stays open
                ctx = client.__aenter__()
                await ctx
                self._clients[name] = client
                self._contexts[name] = client

                # Discover tools
                remote_tools = await client.list_tools()
                logger.info(
                    f"MCP server '{name}': connected, {len(remote_tools)} tool(s) found"
                )

                for tool in remote_tools:
                    adapter = McpToolAdapter(
                        server_name=name,
                        tool_name=tool.name,
                        tool_description=tool.description or "",
                        input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
                        client=client,
                    )
                    self._tools.append(adapter)

            except Exception as e:
                logger.warning(f"MCP server '{name}' failed to connect: {e}")

        self._started = True
        return self._tools

    async def stop(self) -> None:
        """Disconnect all MCP clients."""
        for name, client in list(self._contexts.items()):
            try:
                await client.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"Error closing MCP client '{name}': {e}")
        self._clients.clear()
        self._contexts.clear()
        self._tools.clear()
        self._started = False

    def get_tools(self) -> list[McpToolAdapter]:
        """Return the list of discovered MCP tool adapters (after start)."""
        return list(self._tools)

    @property
    def is_started(self) -> bool:
        return self._started

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _build_transport(
        name: str, cfg: McpServerConfig
    ) -> Any:
        """Create the appropriate FastMCP transport from config."""
        if cfg.type == "http":
            if not cfg.url:
                raise ValueError(f"MCP server '{name}': HTTP transport requires a 'url'")
            return StreamableHttpTransport(
                url=cfg.url,
                headers=cfg.headers or {},
            )
        elif cfg.type == "stdio":
            if not cfg.command:
                raise ValueError(f"MCP server '{name}': stdio transport requires a 'command'")
            return StdioTransport(
                command=cfg.command,
                args=cfg.args or [],
                env=cfg.env or {},
            )
        else:
            raise ValueError(
                f"MCP server '{name}': unsupported transport type '{cfg.type}' "
                f"(expected 'http' or 'stdio')"
            )
