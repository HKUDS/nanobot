"""Stdio transport for local MCP servers."""

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.mcp.transport.base import Transport, TransportError


class StdioTransport(Transport):
    """
    Transport that communicates with a local MCP server via stdin/stdout.
    
    Spawns a subprocess and communicates via pipes.
    
    Example:
        transport = StdioTransport(
            name="calculator",
            command="python",
            args=["/path/to/calc.py"]
        )
        read_stream, write_stream = await transport.connect()
    """
    
    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ):
        super().__init__(name)
        self.command = command
        self.args = args
        self.env = env
        self._process: asyncio.subprocess.Process | None = None
    
    async def connect(self) -> tuple[Any, Any]:
        """Spawn subprocess and return read/write streams."""
        if self._connected:
            raise TransportError(f"Transport '{self.name}' already connected")
        
        # Validate script path if provided
        if self.args:
            script_path = Path(self.args[0])
            if script_path.suffix in ('.py', '.js') and not script_path.exists():
                raise TransportError(f"Server script not found: {script_path}")
        
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
            )
            
            self._connected = True
            logger.debug(f"StdioTransport '{self.name}': spawned {self.command}")
            
            # Return streams compatible with MCP client
            return self._process.stdout, self._process.stdin
            
        except Exception as e:
            raise TransportError(f"Failed to spawn process: {e}") from e
    
    async def disconnect(self) -> None:
        """Terminate subprocess and cleanup."""
        if not self._connected or not self._process:
            return
        
        try:
            # Graceful termination
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                # Force kill if not terminated
                self._process.kill()
                await self._process.wait()
        except Exception as e:
            logger.warning(f"Error terminating process for '{self.name}': {e}")
        finally:
            self._process = None
            self._connected = False
            logger.debug(f"StdioTransport '{self.name}': disconnected")
