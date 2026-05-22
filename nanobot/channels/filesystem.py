"""Filesystem inter-process channel for local bot-to-bot communication.

Each configured peer has an inbox directory (we watch for new files) and an
outbox directory (we write outgoing messages to). The entire contents of each
file are the message body. Files are sorted lexicographically for FIFO
ordering; hidden files and ``.tmp`` files are skipped so partial writes are
never read.

Outgoing messages are written via tmp + rename so readers never see a partial
file. After processing, inbound files are either deleted or moved into a
configured archive directory.

Typical layout for two bots A and B sharing a host::

    /shared/mailbox/inbox-A/   <- B writes here, A reads
    /shared/mailbox/inbox-B/   <- A writes here, B reads
    /shared/mailbox/archive/   <- optional, per-bot
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import FilesystemConfig, FilesystemPeerConfig


class FilesystemChannel(BaseChannel):
    """Watch peer inbox directories and route outbound messages to peer outboxes."""

    name = "fs"

    def __init__(self, config: FilesystemConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: FilesystemConfig = config
        self._peers_by_id: dict[str, FilesystemPeerConfig] = {
            p.peer_id: p for p in config.peers
        }
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        if not self.config.peers:
            logger.warning("Filesystem channel enabled but no peers configured")
            return

        for peer in self.config.peers:
            inbox = Path(peer.inbox).expanduser()
            outbox = Path(peer.outbox).expanduser()
            inbox.mkdir(parents=True, exist_ok=True)
            outbox.mkdir(parents=True, exist_ok=True)
            if peer.archive:
                Path(peer.archive).expanduser().mkdir(parents=True, exist_ok=True)
            logger.info(
                "FS channel watching peer {!r}: inbox={} outbox={}",
                peer.peer_id, inbox, outbox,
            )

        self._running = True
        interval = max(0.05, self.config.poll_interval_ms / 1000)
        self._tasks = [
            asyncio.create_task(self._watch_peer(peer, interval))
            for peer in self.config.peers
        ]
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def send(self, msg: OutboundMessage) -> None:
        peer = self._peers_by_id.get(msg.chat_id)
        if peer is None:
            logger.warning("FS channel: no peer matches chat_id={!r}", msg.chat_id)
            return
        outbox = Path(peer.outbox).expanduser()
        await asyncio.to_thread(self._atomic_write, outbox, msg.content)

    async def _watch_peer(self, peer: FilesystemPeerConfig, interval: float) -> None:
        inbox = Path(peer.inbox).expanduser()
        archive = Path(peer.archive).expanduser() if peer.archive else None
        while self._running:
            try:
                for path in sorted(inbox.iterdir()):
                    if not self._is_consumable(path):
                        continue
                    await self._process_inbound(peer, path, archive)
            except FileNotFoundError:
                inbox.mkdir(parents=True, exist_ok=True)
            except Exception as e:  # pragma: no cover - defensive
                logger.exception("FS channel watch error for {}: {}", peer.peer_id, e)
            await asyncio.sleep(interval)

    @staticmethod
    def _is_consumable(path: Path) -> bool:
        if not path.is_file():
            return False
        if path.name.startswith("."):
            return False
        if path.suffix == ".tmp":
            return False
        return True

    async def _process_inbound(
        self,
        peer: FilesystemPeerConfig,
        path: Path,
        archive: Path | None,
    ) -> None:
        try:
            content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except FileNotFoundError:
            return
        except Exception as e:
            logger.warning("FS channel failed to read {}: {}", path, e)
            return

        if content.strip():
            await self._handle_message(
                sender_id=peer.peer_id,
                chat_id=peer.peer_id,
                content=content,
                metadata={"source_file": str(path)},
            )

        try:
            if archive is not None:
                await asyncio.to_thread(path.rename, archive / path.name)
            else:
                await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("FS channel failed to retire {}: {}", path, e)

    @staticmethod
    def _atomic_write(outbox: Path, content: str) -> None:
        name_base = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        tmp = outbox / f".{name_base}.tmp"
        final = outbox / f"{name_base}.md"
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(final)
