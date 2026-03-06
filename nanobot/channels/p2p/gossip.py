"""Gossip protocol for P2P peer exchange."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

import httpx
from loguru import logger

from nanobot.channels.p2p.peer_manager import PeerManager


class GossipPayload(TypedDict):
    """Gossip message payload."""
    content: str
    sender_id: str


class BroadcastResult(TypedDict):
    """Broadcast delivery result."""
    peer_id: str
    delivered: bool
    error: str | None


@dataclass
class GossipMessage:
    """Gossip protocol message."""

    type: str  # "peer_exchange", "broadcast", "direct"
    sender_id: str
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)


class GossipProtocol:
    """Gossip protocol for peer discovery and message propagation."""

    def __init__(self, peer_manager: PeerManager, peer_id: str, address: str = ""):
        self.peer_manager = peer_manager
        self.peer_id = peer_id
        self.address = address

    async def exchange_peers(self, target_peer_id: str, remote_peers: dict[str, str]) -> dict[str, str]:
        """
        Exchange peer information with a remote peer.

        Args:
            target_peer_id: The peer we're exchanging with (to exclude from returned peers)
            remote_peers: Peers from remote

        Returns our known peers to share with the remote.
        """
        # Add new peers from remote
        for remote_peer_id, address in remote_peers.items():
            if remote_peer_id != self.peer_id:
                await self.peer_manager.add_peer(remote_peer_id, address)

        # Return our peers, excluding the target to avoid loops
        return {
            pid: peer.address
            for pid, peer in self.peer_manager.peers.items()
            if pid != self.peer_id and pid != target_peer_id and peer.is_online
        }

    async def broadcast(self, message: GossipPayload) -> list[BroadcastResult]:
        """
        Broadcast a message to all connected peers.

        Returns list of delivery results.
        """
        results: list[BroadcastResult] = []
        peers = self.peer_manager.get_online_peers()

        for peer in peers:
            try:
                url = f"http://{peer.address}/p2p/message"
                payload = {
                    "sender_id": self.peer_id,
                    "sender_address": self.address,
                    "content": message.get("content", ""),
                    "message_type": "broadcast",
                    "message_id": str(uuid.uuid4()),
                }

                logger.debug("Broadcasting to peer {} at {}", peer.id, url)

                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(url, json=payload)
                    results.append({"peer_id": peer.id, "delivered": resp.status_code == 200})

            except Exception as e:
                logger.warning("Failed to broadcast to {}: {}", peer.id, e)
                results.append({"peer_id": peer.id, "delivered": False, "error": str(e)})

        return results

    async def send_direct(self, peer_id: str, message: GossipPayload) -> bool:
        """
        Send a direct message to a specific peer.

        Returns True if delivery successful.
        """
        peer = self.peer_manager.get_peer(peer_id)
        if not peer:
            logger.warning("Unknown peer for direct message: {}", peer_id)
            return False

        try:
            # Send HTTP POST to peer's /p2p/message endpoint
            url = f"http://{peer.address}/p2p/message"
            payload = {
                "sender_id": self.peer_id,
                "sender_address": self.address,
                "receiver_id": peer_id,
                "content": message.get("content", ""),
                "message_type": "direct",
                "message_id": str(uuid.uuid4()),
            }

            logger.info("Sending direct message to {} at {}", peer_id, url)

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info("Message delivered to peer {}", peer_id)
                    return True
                else:
                    logger.warning("Failed to deliver to {}: {}", peer_id, resp.text)
                    return False

        except Exception as e:
            logger.warning("Failed to send direct to {}: {}", peer_id, e)
            return False

    def create_peer_exchange_message(self) -> GossipMessage:
        """Create a peer exchange message."""
        return GossipMessage(
            type="peer_exchange",
            sender_id=self.peer_id,
            payload={
                "peers": self.peer_manager.get_peers_for_exchange()
            }
        )

    def create_broadcast_message(self, content: str, message_id: str) -> GossipMessage:
        """Create a broadcast message."""
        return GossipMessage(
            type="broadcast",
            sender_id=self.peer_id,
            payload={
                "message_id": message_id,
                "content": content
            }
        )

    def create_direct_message(self, receiver_id: str, content: str, message_id: str) -> GossipMessage:
        """Create a direct message."""
        return GossipMessage(
            type="direct",
            sender_id=self.peer_id,
            payload={
                "receiver_id": receiver_id,
                "message_id": message_id,
                "content": content
            }
        )
