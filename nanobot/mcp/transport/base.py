"""Abstract base class for MCP transports."""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class TransportError(Exception):
    """Base exception for transport errors."""
    pass


class Transport(ABC):
    """
    Abstract base class for MCP transport implementations.
    
    Transports handle the low-level communication between MCP client and server.
    Implementations: StdioTransport (local processes), SSETransport (HTTP/SSE)
    
    Usage:
        transport = StdioTransport(command="python", args=["server.py"])
        await transport.connect()
        await transport.send({"jsonrpc": "2.0", ...})
        response = await transport.receive()
        await transport.disconnect()
    """
    
    def __init__(self, name: str):
        self.name = name
        self._connected = False
    
    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._connected
    
    @abstractmethod
    async def connect(self) -> tuple[Any, Any]:
        """
        Establish connection to the server.
        
        Returns:
            Tuple of (read_stream, write_stream) for JSON-RPC communication
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection and cleanup resources."""
        pass
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
