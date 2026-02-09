import asyncio
from typing import Any

from nio import AsyncClient, MatrixRoom, RoomMessageText

from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage


class MatrixChannel(BaseChannel):
    """
    Matrix (Element) channel using long-polling sync.
    """

    name = "matrix"

    def __init__(self, config: Any, bus):
        super().__init__(config, bus)
        self.client: AsyncClient | None = None
        self._sync_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True

        self.client = AsyncClient(
             homeserver=self.config.homeserver,
             user=self.config.user_id,
            )
        
        self.client.access_token = self.config.access_token

        self.client.add_event_callback(
            self._on_message,
            RoomMessageText
        )

        self._sync_task = asyncio.create_task(self._sync_loop())

    async def stop(self) -> None:
        self._running = False
        if self._sync_task:
            self._sync_task.cancel()
        if self.client:
            await self.client.close()

    async def send(self, msg: OutboundMessage) -> None:
        if not self.client:
            return

        await self.client.room_send(
            room_id=msg.chat_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": msg.content},
        )

    async def _sync_loop(self) -> None:
        while self._running:
            try:
                await self.client.sync(timeout=30000)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(2)

    async def _on_message(
        self,
        room: MatrixRoom,
        event: RoomMessageText
    ) -> None:
        # Ignore self messages
        if event.sender == self.config.user_id:
            return

        await self._handle_message(
            sender_id=event.sender,
            chat_id=room.room_id,
            content=event.body,
            metadata={"room": room.display_name},
        )