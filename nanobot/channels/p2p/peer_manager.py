"""Peer manager for P2P network."""

from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger


@dataclass
class Peer:
    """Represents a peer in the P2P network."""

    id: str
    address: str
    last_seen: datetime = field(default_factory=datetime.now)
    is_online: bool = True


class PeerManager:
    """Manages peer connections and discovery."""

    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self.peers: dict[str, Peer] = {}

    async def add_peer(self, peer_id: str, address: str) -> None:
        """Add or update a peer."""
        if peer_id == self.peer_id:
            logger.debug("Ignoring self-peer {}", peer_id)
            return

        existing = self.peers.get(peer_id)
        if existing:
            existing.last_seen = datetime.now()
            existing.address = address
            existing.is_online = True
            logger.debug("Updated peer {} at {}", peer_id, address)
        else:
            self.peers[peer_id] = Peer(id=peer_id, address=address)
            logger.info("Discovered new peer: {} at {}", peer_id, address)

    async def remove_peer(self, peer_id: str) -> None:
        """Remove a peer."""
        if peer_id in self.peers:
            del self.peers[peer_id]
            logger.info("Removed peer: {}", peer_id)

    def get_online_peers(self) -> list[Peer]:
        """Get all online peers."""
        return [p for p in self.peers.values() if p.is_online]

    def get_peers_for_exchange(self) -> dict[str, str]:
        """Get peers for gossip exchange (id -> address)."""
        return {
            pid: peer.address
            for pid, peer in self.peers.items()
            if pid != self.peer_id and peer.is_online
        }

    async def mark_offline(self, peer_id: str) -> None:
        """Mark a peer as offline."""
        if peer_id in self.peers:
            self.peers[peer_id].is_online = False
            logger.debug("Peer {} marked offline", peer_id)

    def get_peer(self, peer_id: str) -> Peer | None:
        """Get a specific peer."""
        return self.peers.get(peer_id)

    def __len__(self) -> int:
        return len(self.peers)
