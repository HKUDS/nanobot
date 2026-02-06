"""SSE (Server-Sent Events) transport for remote MCP servers."""

import asyncio
import json
from typing import Any
from urllib.parse import urljoin

import anyio
import httpx
from loguru import logger
from mcp import types
from mcp.shared.session import SessionMessage

from nanobot.mcp.transport.base import Transport, TransportError


class SSETransport(Transport):
    """
    Transport that communicates with a remote MCP server via HTTP/SSE.
    
    MCP SSE Protocol:
    1. Connect to SSE endpoint, receive 'endpoint' event with POST URL
    2. POST messages to endpoint, receive 202 Accepted
    3. Read JSON-RPC responses from SSE stream
    
    Uses anyio memory streams to be compatible with MCP's ClientSession.
    
    Example:
        transport = SSETransport(
            name="remote-server",
            url="https://mcp.example.com/server"
        )
        read_stream, write_stream = await transport.connect()
    """
    
    def __init__(
        self,
        name: str,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ):
        super().__init__(name)
        self.base_url = url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._endpoint_url: str | None = None
        
        # anyio memory streams (like stdio_client)
        self._read_stream: anyio.MemoryObjectReceiveStream | None = None
        self._read_stream_writer: anyio.MemoryObjectSendStream | None = None
        self._write_stream: anyio.MemoryObjectSendStream | None = None
        self._write_stream_reader: anyio.MemoryObjectReceiveStream | None = None
        
        self._sse_task: asyncio.Task | None = None
        self._writer_task: asyncio.Task | None = None
    
    async def connect(self) -> tuple[Any, Any]:
        """Establish SSE connection and return anyio memory streams."""
        if self._connected:
            raise TransportError(f"Transport '{self.name}' already connected")
        
        try:
            # Create HTTP client
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
            )
            
            # Create anyio memory streams (like stdio_client)
            self._read_stream_writer, self._read_stream = anyio.create_memory_object_stream(0)
            self._write_stream, self._write_stream_reader = anyio.create_memory_object_stream(0)
            
            # Start SSE listener to get endpoint
            sse_started = asyncio.Event()
            sse_error: list[Exception] = []  # Use list as mutable container
            self._sse_task = asyncio.create_task(
                self._sse_listener(sse_started, sse_error)
            )
            
            # Wait for endpoint
            try:
                await asyncio.wait_for(sse_started.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                raise TransportError("Timeout waiting for SSE endpoint event")
            
            if sse_error:
                raise sse_error[0]
            
            if not self._endpoint_url:
                raise TransportError("No endpoint received from SSE stream")
            
            # Start writer task
            self._writer_task = asyncio.create_task(self._writer_loop())
            
            self._connected = True
            logger.info(f"SSETransport '{self.name}': connected")
            logger.debug(f"  Endpoint: {self._endpoint_url}")
            
            return self._read_stream, self._write_stream
            
        except Exception as e:
            await self.disconnect()
            raise TransportError(f"Failed to connect: {e}") from e
    
    async def disconnect(self) -> None:
        """Close HTTP connection and cleanup."""
        was_connected = self._connected
        self._connected = False
        
        # Cancel tasks
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
        
        if self._writer_task and not self._writer_task.done():
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
        
        # Close streams
        if self._read_stream:
            await self._read_stream.aclose()
        if self._read_stream_writer:
            await self._read_stream_writer.aclose()
        if self._write_stream:
            await self._write_stream.aclose()
        if self._write_stream_reader:
            await self._write_stream_reader.aclose()
        
        # Close HTTP client
        if self._client:
            await self._client.aclose()
            self._client = None
        
        self._endpoint_url = None
        
        if was_connected:
            logger.debug(f"SSETransport '{self.name}': disconnected")
    
    async def _sse_listener(
        self,
        started_event: asyncio.Event,
        error_container: list[Exception]
    ) -> None:
        """Listen for SSE events and forward JSON-RPC messages to read stream."""
        try:
            async with self._client.stream("GET", self.base_url, timeout=None) as response:
                response.raise_for_status()
                
                current_event = None
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    
                    if line.startswith("event: "):
                        current_event = line[7:].strip()
                    elif line.startswith("data: "):
                        data = line[6:]
                        
                        if current_event == "endpoint":
                            # First event: endpoint URL
                            endpoint = data.strip()
                            self._endpoint_url = urljoin(self.base_url, endpoint)
                            started_event.set()
                            logger.debug(f"SSE endpoint: {self._endpoint_url}")
                            
                        elif self._read_stream_writer:
                            # JSON-RPC message - parse and send as SessionMessage
                            try:
                                message = types.JSONRPCMessage.model_validate_json(data)
                                session_message = SessionMessage(message=message)
                                await self._read_stream_writer.send(session_message)
                            except Exception as exc:
                                logger.exception("Failed to parse JSONRPC message")
                                await self._read_stream_writer.send(exc)
                        
                        current_event = None
                        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not started_event.is_set():
                error_container.append(e)  # Append to list (mutable)
            started_event.set()
            if self._connected:
                logger.error(f"SSE listener error: {e}")
    
    async def _writer_loop(self) -> None:
        """Read SessionMessages from write stream and POST to endpoint."""
        try:
            async with self._write_stream_reader:
                async for session_message in self._write_stream_reader:
                    # Break if not connected or no endpoint available
                    if not self._connected:
                        break
                    
                    if not self._endpoint_url:
                        logger.error("Cannot send: no endpoint URL available")
                        break
                    
                    try:
                        json_str = session_message.message.model_dump_json(
                            by_alias=True, exclude_none=True
                        )
                        json_data = json.loads(json_str)
                        
                        response = await self._client.post(
                            self._endpoint_url,
                            json=json_data,
                            timeout=30.0,
                        )
                        
                        # Accept 200 OK or 202 Accepted
                        if response.status_code not in (200, 202):
                            response.raise_for_status()
                        
                    except Exception as e:
                        logger.error(f"Failed to send message: {e}")
                        
        except asyncio.CancelledError:
            pass
        except anyio.ClosedResourceError:
            pass
