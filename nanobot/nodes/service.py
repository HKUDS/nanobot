"""Node service for managing remote connections."""

import asyncio
import json
from typing import Any, Callable
import websockets
from websockets.server import WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed

from loguru import logger

from nanobot.nodes.types import NodeServerConfig, NodeClientConfig


class NodeServer:
    """
    WebSocket server that accepts connections from remote nodes.

    Runs on the main nanobot instance.
    """

    def __init__(self, config: NodeServerConfig):
        self.config = config
        self._clients: dict[str, WebSocketServerProtocol] = {}  # node_name -> websocket
        self._server: Any = None
        self._running = False

    @property
    def connected_nodes(self) -> list[str]:
        """Get list of connected node names."""
        return list(self._clients.keys())

    async def start(self) -> None:
        """Start the WebSocket server."""
        if not self.config.enabled:
            logger.info("Node server is disabled")
            return

        host = "0.0.0.0"
        port = self.config.port

        logger.info(f"Starting node server on {host}:{port}")

        async def handle_connection(websocket: WebSocketServerProtocol) -> None:
            """Handle a new node connection."""
            try:
                # Authentication
                auth_msg = await websocket.recv()
                auth_data = json.loads(auth_msg)

                if auth_data.get("type") != "auth":
                    logger.warning(f"Invalid auth message from {websocket.remote_address}")
                    await websocket.send(json.dumps({"type": "error", "message": "Auth required"}))
                    return

                token = auth_data.get("token")
                node_name = auth_data.get("node_name")

                if token != self.config.token:
                    logger.warning(f"Invalid token from {websocket.remote_address}")
                    await websocket.send(json.dumps({"type": "error", "message": "Invalid token"}))
                    return

                if not node_name:
                    logger.warning(f"No node_name from {websocket.remote_address}")
                    await websocket.send(json.dumps({"type": "error", "message": "node_name required"}))
                    return

                logger.info(f"Node '{node_name}' connected from {websocket.remote_address}")

                # Send success response
                await websocket.send(json.dumps({"type": "auth_success"}))

                # Store client
                self._clients[node_name] = websocket

                # Keep connection alive and handle commands
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        if data.get("type") == "heartbeat":
                            await websocket.send(json.dumps({"type": "heartbeat_ack"}))
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from {node_name}")

            except ConnectionClosed:
                logger.info(f"Node '{node_name}' disconnected")
            except Exception as e:
                logger.error(f"Error handling node connection: {e}")
            finally:
                # Remove client
                if node_name in self._clients:
                    del self._clients[node_name]

        self._server = await websockets.serve(handle_connection, host, port)
        self._running = True
        logger.info(f"Node server started on {host}:{port}")

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._running = False
            logger.info("Node server stopped")

    async def exec(self, node: str, command: str, timeout: int = 60) -> str:
        """
        Execute a command on a remote node.

        Args:
            node: Node name
            command: Command to execute
            timeout: Timeout in seconds

        Returns:
            Command output
        """
        if node not in self._clients:
            return f"Error: Node '{node}' not connected"

        websocket = self._clients[node]

        try:
            # Send command
            await websocket.send(json.dumps({
                "type": "exec",
                "command": command,
                "timeout": timeout
            }))

            # Wait for response with timeout
            response = await asyncio.wait_for(websocket.recv(), timeout=timeout + 10)
            data = json.loads(response)

            if data.get("type") == "exec_result":
                return data.get("output", "")
            elif data.get("type") == "error":
                return f"Error: {data.get('message', 'Unknown error')}"
            else:
                return f"Error: Unexpected response type: {data.get('type')}"

        except asyncio.TimeoutError:
            return f"Error: Command timeout after {timeout}s"
        except ConnectionClosed:
            # Remove disconnected node
            if node in self._clients:
                del self._clients[node]
            return f"Error: Node '{node}' disconnected"
        except Exception as e:
            logger.error(f"Error executing command on {node}: {e}")
            return f"Error: {str(e)}"


class NodeClient:
    """
    WebSocket client that connects to the main nanobot instance.

    Runs on remote nodes.
    """

    def __init__(self, config: NodeClientConfig):
        self.config = config
        self._websocket: Any = None
        self._running = False

    async def run(self) -> None:
        """Connect to the server and handle commands."""
        if not self.config.enabled:
            logger.info("Node client is disabled")
            return

        logger.info(f"Connecting to {self.config.server_url} as '{self.config.name}'")

        while self._running:
            try:
                async with websockets.connect(self.config.server_url) as websocket:
                    self._websocket = websocket

                    # Send authentication
                    await websocket.send(json.dumps({
                        "type": "auth",
                        "token": self.config.token,
                        "node_name": self.config.name
                    }))

                    # Wait for auth response
                    auth_response = await websocket.recv()
                    auth_data = json.loads(auth_response)

                    if auth_data.get("type") != "auth_success":
                        logger.error(f"Auth failed: {auth_data.get('message', 'Unknown error')}")
                        await asyncio.sleep(10)
                        continue

                    logger.info(f"Connected to server as '{self.config.name}'")

                    # Main loop: handle commands
                    async for message in websocket:
                        try:
                            data = json.loads(message)

                            if data.get("type") == "exec":
                                await self._handle_exec(websocket, data)
                            elif data.get("type") == "heartbeat":
                                await websocket.send(json.dumps({"type": "heartbeat_ack"}))

                        except json.JSONDecodeError:
                            logger.warning(f"Invalid JSON from server")
                        except Exception as e:
                            logger.error(f"Error handling message: {e}")

            except ConnectionClosed:
                logger.warning("Connection to server closed, reconnecting...")
            except Exception as e:
                logger.error(f"Connection error: {e}")

            if self._running:
                await asyncio.sleep(5)

    async def _handle_exec(self, websocket: Any, data: dict) -> None:
        """Handle an exec command from the server."""
        command = data.get("command", "")
        timeout = data.get("timeout", 60)

        logger.info(f"Executing: {command}")

        try:
            # Execute command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                output = stdout.decode("utf-8", errors="replace")
                error = stderr.decode("utf-8", errors="replace")

                if error:
                    output += f"\n[stderr]\n{error}"

                await websocket.send(json.dumps({
                    "type": "exec_result",
                    "output": output,
                    "exit_code": process.returncode
                }))

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": f"Command timeout after {timeout}s"
                }))

        except Exception as e:
            logger.error(f"Error executing command: {e}")
            await websocket.send(json.dumps({
                "type": "error",
                "message": str(e)
            }))

    async def stop(self) -> None:
        """Stop the client."""
        self._running = False
        if self._websocket:
            await self._websocket.close()
        logger.info("Node client stopped")