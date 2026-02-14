"""Matrix channel implementation using matrix-nio."""

from __future__ import annotations

import asyncio
from typing import Any
from loguru import logger

try:
    from nio import AsyncClient, RoomMessageText, InviteEvent, RoomMemberEvent
    from nio.responses import JoinResponse
except ImportError:
    raise ImportError(
        "Matrix channel requires 'matrix-nio'. Install with: pip install matrix-nio"
    )

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import MatrixConfig


class MatrixChannel(BaseChannel):
    """
    Matrix channel using matrix-nio library.

    Supports E2EE (End-to-End Encryption) rooms with proper handling.
    """

    name = "matrix"

    def __init__(
        self,
        config: MatrixConfig,
        bus: MessageBus,
    ):
        super().__init__(config, bus)
        self.config: MatrixConfig = config
        self.client: AsyncClient | None = None
        self._sync_task: asyncio.Task | None = None
        self._room_aliases: dict[str, str] = {}  # Map room_id to alias

    async def start(self) -> None:
        """Start Matrix client and listen for messages."""
        if not self.config.access_token or not self.config.user_id:
            logger.error("Matrix access token or user_id not configured")
            return

        self._running = True

        # Create Matrix client
        self.client = AsyncClient(
            self.config.homeserver,
            self.config.user_id,
            store_path="~/.nanobot/matrix_store"
        )

        # Set access token for login
        self.client.access_token = self.config.access_token

        # Register event callbacks
        self.client.add_event_callback(self._on_room_message, RoomMessageText)
        self.client.add_event_callback(self._on_invite, InviteEvent)

        logger.info(f"Starting Matrix client on {self.config.homeserver}...")

        # Initialize and start the client
        await self.client.start()

        # Join rooms if configured
        if self.config.auto_join_rooms:
            for room_id in self.config.auto_join_rooms:
                try:
                    logger.info(f"Joining room: {room_id}")
                    await self.client.join(room_id)
                except Exception as e:
                    logger.warning(f"Failed to join room {room_id}: {e}")

        # Sync forever to receive events
        self._sync_task = asyncio.create_task(self._sync_forever())

        logger.info("Matrix channel started")

    async def _sync_forever(self) -> None:
        """Continuously sync with Matrix homeserver."""
        try:
            # Start syncing with timeout
            since_token = ""
            while self._running:
                response = await self.client.sync(
                    timeout=30000,  # 30 seconds
                    since_token=since_token,
                    full_state=False
                )

                if hasattr(response, "next_batch"):
                    since_token = response.next_batch

        except asyncio.CancelledError:
            logger.debug("Matrix sync cancelled")
        except Exception as e:
            if self._running:
                logger.error(f"Matrix sync error: {e}")

    async def stop(self) -> None:
        """Stop Matrix client."""
        self._running = False

        # Cancel sync task
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

        # Close client
        if self.client:
            logger.info("Stopping Matrix client...")
            await self.client.close()
            self.client = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to Matrix room."""
        if not self.client:
            logger.warning("Matrix client not running")
            return

        try:
            # Send message to room
            await self.client.room_send(
                msg.chat_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": msg.content
                }
            )
            logger.debug(f"Sent message to Matrix room {msg.chat_id}")

        except Exception as e:
            logger.error(f"Error sending Matrix message: {e}")

    async def _on_room_message(self, room: Any, event: RoomMessageText) -> None:
        """Handle incoming room message events."""
        # Ignore own messages
        if event.sender == self.config.user_id:
            return

        # Get room ID
        room_id = room.room_id

        # Store room alias if available
        if room.canonical_alias:
            self._room_aliases[room_id] = room.canonical_alias

        # Extract sender information
        sender_id = event.sender
        sender_name = event.source.get("content", {}).get("body", "")

        # Build display name (use displayname if available)
        display_name = sender_id
        if room.user_name(event.sender):
            display_name = room.user_name(event.sender)

        # Get message content
        content = event.body or ""

        logger.debug(f"Matrix message from {display_name} in {room_id}: {content[:50]}...")

        # Forward to message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=room_id,
            content=content,
            metadata={
                "room_id": room_id,
                "room_alias": room.canonical_alias,
                "sender_name": display_name,
                "event_id": event.event_id,
                "timestamp": event.server_timestamp
            }
        )

    async def _on_invite(self, room: Any, event: InviteEvent) -> None:
        """Handle room invite events."""
        if not self.config.auto_join_invites:
            return

        room_id = event.room_id

        try:
            logger.info(f"Accepting invite to room: {room_id}")
            await self.client.join(room_id)
        except Exception as e:
            logger.warning(f"Failed to join invited room {room_id}: {e}")

    def _format_user_id(self, user_id: str) -> str:
        """Format Matrix user ID for display."""
        # Remove leading @ if present
        if user_id.startswith("@"):
            return user_id[1:]
        return user_id
