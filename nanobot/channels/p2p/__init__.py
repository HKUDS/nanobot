"""P2P channel for peer-to-peer communication."""

import asyncio
import json
from typing import Any

import httpx
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.p2p.gossip import GossipProtocol
from nanobot.channels.p2p.peer_manager import PeerManager


class P2PChannel(BaseChannel):
    """P2P channel for peer-to-peer nanobot communication."""

    name: str = "p2p"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)

        # Generate peer_id if not provided
        peer_id = config.peer_id or f"nanobot_{config.port}"

        # Initialize components
        self.peer_id = peer_id
        self.host = config.host
        self.port = config.port
        self.gossip_interval = config.gossip_interval

        self.peer_manager = PeerManager(peer_id)
        self.gossip_protocol = GossipProtocol(self.peer_manager, peer_id, f"{config.host}:{config.port}")

        # Track seen message IDs for deduplication
        self._seen_message_ids: set[str] = set()
        self._max_seen_ids = 1000

        # HTTP server task
        self._server_task: asyncio.Task | None = None
        self._gossip_task: asyncio.Task | None = None
        self._running = False

        # Bootstrap peers
        self._bootstrap_peers = config.bootstrap_peers or []

        logger.info("P2P channel initialized with peer_id: {}", self.peer_id)

    async def start(self) -> None:
        """Start the P2P channel."""
        self._running = True

        # Connect to bootstrap peers
        for peer_addr in self._bootstrap_peers:
            try:
                if ":" in peer_addr:
                    # Try to get peer's actual peer_id via HTTP
                    peer_id = await self._discover_peer_id(peer_addr)
                    if peer_id:
                        await self.peer_manager.add_peer(peer_id, peer_addr)
                        logger.info("Connected to bootstrap peer {} as {}", peer_addr, peer_id)
                    else:
                        # Fallback to address-based ID
                        host, port = peer_addr.rsplit(":", 1)
                        peer_id = f"peer_{port}"
                        await self.peer_manager.add_peer(peer_id, peer_addr)
                        logger.info("Connected to bootstrap peer {} (fallback: {})", peer_addr, peer_id)
            except Exception as e:
                logger.warning("Failed to connect to bootstrap peer {}: {}", peer_addr, e)

        # Try to start HTTP server, but don't fail if it can't
        try:
            self._server_task = asyncio.create_task(self._run_server())
        except Exception as e:
            logger.warning("Could not start P2P server: {}", e)

        # Start gossip protocol
        self._gossip_task = asyncio.create_task(self._run_gossip())

        logger.info("P2P channel started on {}:{}", self.host, self.port)

    async def _discover_peer_id(self, address: str) -> str | None:
        """Discover a peer's actual peer_id via HTTP request."""
        try:
            import httpx
            url = f"http://{address}/p2p/id"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    peer_id = data.get("peer_id")
                    if peer_id:
                        logger.debug("Discovered peer_id {} from {}", peer_id, address)
                        return peer_id
        except Exception as e:
            logger.debug("Failed to discover peer_id from {}: {}", address, e)
        return None

    async def stop(self) -> None:
        """Stop the P2P channel."""
        self._running = False

        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass

        if self._gossip_task:
            self._gossip_task.cancel()
            try:
                await self._gossip_task
            except asyncio.CancelledError:
                pass

        logger.info("P2P channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message to a peer.

        For P2P, the chat_id is the peer_id to send to.
        """
        peer_id = msg.chat_id

        # Check if target peer exists in our peer list
        if not self.peer_manager.get_peer(peer_id):
            logger.warning("Cannot send message: peer {} not found in P2P network", peer_id)
            return

        # Check if it's a broadcast
        if msg.metadata.get("broadcast"):
            await self.gossip_protocol.broadcast({
                "content": msg.content,
                "sender_id": self.peer_id,
            })
        else:
            # Direct message
            await self.gossip_protocol.send_direct(peer_id, {
                "content": msg.content,
                "sender_id": self.peer_id,
            })

        logger.debug("Sent message to peer: {}", peer_id)

    async def _run_server(self) -> None:
        """Run the HTTP server for receiving P2P messages."""
        try:
            from aiohttp import web
        except ImportError:
            logger.warning("aiohttp not available, P2P server not started")
            return

        async def handle_message(request):
            """Handle incoming P2P message."""
            try:
                data = await request.json()
                # Get sender's address from HTTP request
                remote = request.remote
                await self._handle_p2p_message(data, remote)
                return web.json_response({"status": "ok"})
            except json.JSONDecodeError:
                return web.json_response({"error": "invalid json"}, status=400)
            except Exception as e:
                logger.error("Error handling P2P message: {}", e)
                return web.json_response({"error": str(e)}, status=500)

        async def handle_peers(request):
            """Get list of known peers."""
            peers = self.peer_manager.get_peers_for_exchange()
            return web.json_response({"peers": peers})

        async def handle_id(request):
            """Get our own peer_id."""
            return web.json_response({"peer_id": self.peer_id})

        async def handle_connect(request):
            """Connect to a new peer."""
            try:
                data = await request.json()
                peer_id = data.get("peer_id")
                address = data.get("address")
                if peer_id and address:
                    await self.peer_manager.add_peer(peer_id, address)
                    return web.json_response({"status": "connected"})
                return web.json_response({"error": "missing peer_id or address"}, status=400)
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        async def handle_disconnect(request):
            """Disconnect from a peer."""
            try:
                data = await request.json()
                peer_id = data.get("peer_id")
                if peer_id:
                    await self.peer_manager.remove_peer(peer_id)
                    return web.json_response({"status": "disconnected"})
                return web.json_response({"error": "missing peer_id"}, status=400)
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        async def handle_exchange(request):
            """Exchange peers with a remote node."""
            try:
                data = await request.json()
                remote_peers = data.get("peers", {})

                # Process peer exchange - add new peers to our list
                for peer_id, address in remote_peers.items():
                    if peer_id != self.peer_id:
                        await self.peer_manager.add_peer(peer_id, address)

                # Return our peers (excluding ourselves)
                our_peers = self.peer_manager.get_peers_for_exchange()
                return web.json_response({"peers": our_peers})
            except Exception as e:
                logger.error("Peer exchange error: {}", e)
                return web.json_response({"error": str(e)}, status=500)

        app = web.Application()
        app.router.add_post("/p2p/message", handle_message)
        app.router.add_get("/p2p/peers", handle_peers)
        app.router.add_get("/p2p/id", handle_id)
        app.router.add_post("/p2p/connect", handle_connect)
        app.router.add_post("/p2p/disconnect", handle_disconnect)
        app.router.add_post("/p2p/exchange", handle_exchange)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        logger.info("P2P HTTP server started on {}:{}", self.host, self.port)

        # Keep running
        while self._running:
            await asyncio.sleep(1)

    async def _run_gossip(self) -> None:
        """Run periodic gossip protocol to exchange peers."""
        while self._running:
            try:
                await asyncio.sleep(self.gossip_interval)

                # Exchange peers with each known peer
                peers = self.peer_manager.get_online_peers()
                for peer in peers:
                    try:
                        # Get our peers to share
                        # Include ourselves so the remote knows we exist
                        # Exclude only the target peer to avoid echo
                        our_peers = {
                            pid: p.address
                            for pid, p in self.peer_manager.peers.items()
                            if pid != peer.id  # Don't send back to them what they just sent us
                        }
                        # Always include ourselves so they know we exist
                        our_peers[self.peer_id] = f"{self.host}:{self.port}"

                        # Send HTTP POST to remote peer's /p2p/exchange endpoint
                        url = f"http://{peer.address}/p2p/exchange"
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            resp = await client.post(url, json={"peers": our_peers})
                            if resp.status_code == 200:
                                # Process response - add new peers from remote
                                data = resp.json()
                                remote_peers = data.get("peers", {})
                                for remote_peer_id, address in remote_peers.items():
                                    if remote_peer_id != self.peer_id:
                                        await self.peer_manager.add_peer(remote_peer_id, address)
                                logger.debug("Gossip exchange with {} successful", peer.id)
                            else:
                                logger.debug("Gossip exchange with {} failed: {}", peer.id, resp.status_code)
                    except Exception as e:
                        logger.debug("Gossip exchange with {} failed: {}", peer.id, e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Gossip error: {}", e)

    async def _handle_p2p_message(self, data: dict[str, Any], remote: str | None = None) -> None:
        """Handle an incoming P2P message."""
        try:
            # Extract message fields
            sender_id = data.get("sender_id", "unknown")
            content = data.get("content", "")
            sender_address = data.get("sender_address", "")
            message_id = data.get("message_id", "")
            message_type = data.get("message_type", "direct")

            # Check for self-message
            if sender_id == self.peer_id:
                logger.debug("Ignoring message from self")
                return

            # Check for duplicate
            if message_id and self._is_duplicate(message_id):
                logger.debug("Ignoring duplicate message: {}", message_id)
                return

            # Auto-add sender to peer manager if we don't know them
            if sender_address and not self.peer_manager.get_peer(sender_id):
                await self.peer_manager.add_peer(sender_id, sender_address)
                logger.debug("Auto-added peer {} at {}", sender_id, sender_address)

            # Handle peer exchange
            if message_type == "peer_exchange":
                peers = data.get("peers", {})
                await self.gossip_protocol.exchange_peers(sender_id, peers)
                return

            # Create inbound message for the agent
            msg = InboundMessage(
                channel=self.name,
                sender_id=sender_id,
                chat_id=sender_id,  # Reply to sender
                content=content,
                metadata={
                    "peer_id": sender_id,
                    "message_id": message_id,
                    "message_type": message_type,
                },
            )

            await self.bus.publish_inbound(msg)
            logger.debug("Published inbound from peer: {}", sender_id)

        except Exception as e:
            logger.error("Error handling P2P message: {}", e)

    def _is_duplicate(self, message_id: str) -> bool:
        """Check if message is a duplicate."""
        if message_id in self._seen_message_ids:
            return True

        self._seen_message_ids.add(message_id)

        # Trim if too many
        if len(self._seen_message_ids) > self._max_seen_ids:
            seen_list = list(self._seen_message_ids)
            self._seen_message_ids = set(seen_list[len(seen_list)//2:])

        return False
