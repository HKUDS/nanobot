import asyncio
from typing import Any

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage


class SlackChannel(BaseChannel):
    """
    Slack channel integration using Socket Mode.
    """

    name = "slack"

    def __init__(self, config: Any, bus):
        super().__init__(config, bus)
        self.web_client = None
        self.socket_client = None


    async def start(self) -> None:
        self._running = True
        
        self.web_client = AsyncWebClient(token=self.config.bot_token)
        self.socket_client = SocketModeClient(
            app_token=self.config.app_token,
            web_client=self.web_client,
            )

        self.socket_client.socket_mode_request_listeners.append(
            self._handle_socket_event
            )

        await self.socket_client.connect()

    async def stop(self) -> None:
        self._running = False
        if self.socket_client:
            await self.socket_client.close()


    async def send(self, msg: OutboundMessage) -> None:
        await self.web_client.chat_postMessage(
            channel=msg.chat_id,
            text=msg.content
        )

    async def _handle_socket_event(
        self,
        client: SocketModeClient,
        req: SocketModeRequest
    ):
        # Acknowledge event
        await client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )

        if req.type != "events_api":
            return

        event = req.payload.get("event", {})
        if event.get("type") != "message":
            return

        # Ignore bot messages
        if event.get("bot_id"):
            return

        sender_id = event.get("user")
        chat_id = event.get("channel")
        text = event.get("text", "")

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=text,
            metadata=event
        )