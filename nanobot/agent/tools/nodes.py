"""Nodes tool for managing remote nodes."""

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class NodesTool(Tool):
    """Tool for managing and interacting with remote nodes."""

    def __init__(self, node_server: Any = None):
        """
        Initialize the nodes tool.

        Args:
            node_server: NodeServer instance (optional, if None, tool will be read-only)
        """
        self._node_server = node_server

    def set_node_server(self, node_server: Any) -> None:
        """Set the node server instance."""
        self._node_server = node_server

    @property
    def name(self) -> str:
        return "nodes"

    @property
    def description(self) -> str:
        return "Manage and interact with remote nanobot nodes (list, run commands, check status)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "run", "status"],
                    "description": "Action to perform: list (connected nodes), run (execute command), status (check node status)"
                },
                "node": {
                    "type": "string",
                    "description": "Node name (required for 'run' and 'status' actions)"
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute (required for 'run' action)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds for command execution (default: 60)",
                    "default": 60
                }
            },
            "required": ["action"]
        }

    async def execute(
        self,
        action: str,
        node: str | None = None,
        command: str | None = None,
        timeout: int = 60,
        **kwargs: Any
    ) -> str:
        """Execute the nodes tool action."""

        if action == "list":
            return await self._list_nodes()
        elif action == "run":
            return await self._run_command(node, command, timeout)
        elif action == "status":
            return await self._check_status(node)
        else:
            return f"Error: Unknown action '{action}'. Use 'list', 'run', or 'status'."

    async def _list_nodes(self) -> str:
        """List all connected nodes."""
        if not self._node_server:
            return "Node server is not available. This tool can only be used on the main nanobot instance."

        nodes = self._node_server.connected_nodes

        if not nodes:
            return "No nodes currently connected."

        return f"Connected nodes ({len(nodes)}):\n" + "\n".join(f"  - {n}" for n in nodes)

    async def _run_command(self, node: str | None, command: str | None, timeout: int) -> str:
        """Run a command on a remote node."""
        if not self._node_server:
            return "Node server is not available. This tool can only be used on the main nanobot instance."

        if not node:
            return "Error: 'node' parameter is required for 'run' action."

        if not command:
            return "Error: 'command' parameter is required for 'run' action."

        logger.info(f"Running command on node '{node}': {command}")

        result = await self._node_server.exec(node, command, timeout)

        return f"Node: {node}\nCommand: {command}\nOutput:\n{result}"

    async def _check_status(self, node: str | None) -> str:
        """Check the status of a node."""
        if not self._node_server:
            return "Node server is not available. This tool can only be used on the main nanobot instance."

        if not node:
            return "Error: 'node' parameter is required for 'status' action."

        nodes = self._node_server.connected_nodes

        if node in nodes:
            return f"Node '{node}' is connected and active."
        else:
            return f"Node '{node}' is not connected.\n\nConnected nodes:\n" + "\n".join(f"  - {n}" for n in nodes)