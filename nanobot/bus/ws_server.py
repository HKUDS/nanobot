"""WebSocket server to expose MessageBus for TUI and other clients."""

import asyncio
import json
from datetime import datetime
from typing import Optional
from loguru import logger

try:
    import websockets
    from websockets.server import serve, WebSocketServerProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    WebSocketServerProtocol = None

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


class BusWebSocketServer:
    """
    WebSocket server that exposes the MessageBus for external clients like TUI.
    
    Protocol (JSON messages):
    
    Client → Server (send message):
    {
        "type": "message",
        "content": "...",
        "channel": "telegram",
        "chat_id": "12345"
    }
    
    Server → Client (receive message):
    {
        "type": "message",
        "sender": "user_id",
        "content": "...",
        "channel": "telegram",
        "chat_id": "12345",
        "timestamp": "2024-01-15T10:30:00"
    }
    
    Server → Client (status):
    {
        "type": "status",
        "connected": true,
        "clients": 2
    }
    """
    
    def __init__(
        self,
        bus: MessageBus,
        host: str = "localhost",
        port: int = 8765,
    ):
        if not WEBSOCKETS_AVAILABLE:
            raise ImportError("websockets library not installed. Run: pip install websockets")
        
        self.bus = bus
        self.host = host
        self.port = port
        self._clients: set[WebSocketServerProtocol] = set()
        self._server: Optional[asyncio.Server] = None
        self._running = False
    
    @property
    def client_count(self) -> int:
        """Number of connected clients."""
        return len(self._clients)
    
    async def start(self) -> None:
        """Start the WebSocket server."""
        self._running = True
        
        # Subscribe to outbound messages from the bus
        self.bus.subscribe_outbound("websocket", self._handle_outbound)
        
        # Start the server
        self._server = await serve(
            self._handle_client,
            self.host,
            self.port,
        )
        logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")
    
    async def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        
        # Close all client connections
        for client in list(self._clients):
            await client.close()
        
        # Close the server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        
        logger.info("WebSocket server stopped")
    
    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a client connection."""
        client_addr = websocket.remote_address
        logger.info(f"WebSocket client connected: {client_addr}")
        
        self._clients.add(websocket)
        
        try:
            # Send initial status
            await self._send_status(websocket)
            
            # Broadcast client count to all
            await self._broadcast_status()
            
            # Handle incoming messages
            async for raw_message in websocket:
                try:
                    await self._handle_message(websocket, raw_message)
                except Exception as e:
                    logger.error(f"Error handling message from {client_addr}: {e}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": str(e),
                    }))
        
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info(f"WebSocket client disconnected: {client_addr}")
            await self._broadcast_status()
    
    async def _handle_message(
        self,
        websocket: WebSocketServerProtocol,
        raw_message: str,
    ) -> None:
        """Handle an incoming message from a client."""
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            await websocket.send(json.dumps({
                "type": "error",
                "message": "Invalid JSON",
            }))
            return
        
        msg_type = data.get("type", "message")
        
        if msg_type == "message":
            # Create inbound message and publish to bus
            inbound = InboundMessage(
                channel=data.get("channel", "tui"),
                sender_id=str(websocket.remote_address),
                chat_id=data.get("chat_id", ""),
                content=data.get("content", ""),
                timestamp=datetime.now(),
                metadata={"source": "websocket"},
            )
            await self.bus.publish_inbound(inbound)
            logger.debug(f"Published inbound message from TUI: {inbound.session_key}")
        
        elif msg_type == "ping":
            await websocket.send(json.dumps({"type": "pong"}))
        
        else:
            await websocket.send(json.dumps({
                "type": "error",
                "message": f"Unknown message type: {msg_type}",
            }))
    
    async def _handle_outbound(self, msg: OutboundMessage) -> None:
        """Handle outbound message from bus, broadcast to clients."""
        if not self._clients:
            return
        
        data = {
            "type": "message",
            "sender": "agent",
            "content": msg.content,
            "channel": msg.channel,
            "chat_id": msg.chat_id,
            "timestamp": datetime.now().isoformat(),
        }
        
        if msg.media:
            data["media"] = msg.media
        
        raw = json.dumps(data)
        
        # Broadcast to all connected clients
        # Could filter by chat_id/channel if needed
        await asyncio.gather(
            *[client.send(raw) for client in self._clients],
            return_exceptions=True,
        )
    
    async def _send_status(self, websocket: WebSocketServerProtocol) -> None:
        """Send status to a specific client."""
        await websocket.send(json.dumps({
            "type": "status",
            "connected": True,
            "clients": self.client_count,
        }))
    
    async def _broadcast_status(self) -> None:
        """Broadcast status to all clients."""
        if not self._clients:
            return
        
        data = json.dumps({
            "type": "status",
            "connected": True,
            "clients": self.client_count,
        })
        
        await asyncio.gather(
            *[client.send(data) for client in self._clients],
            return_exceptions=True,
        )


async def run_ws_server(
    bus: MessageBus,
    host: str = "localhost",
    port: int = 8765,
) -> BusWebSocketServer:
    """
    Create and start a WebSocket server for the given bus.
    
    Usage:
        bus = MessageBus()
        ws_server = await run_ws_server(bus)
        # ... run your application ...
        await ws_server.stop()
    """
    server = BusWebSocketServer(bus, host, port)
    await server.start()
    return server
