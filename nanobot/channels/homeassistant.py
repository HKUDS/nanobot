"""Home Assistant channel implementation.

Nanobot connects to HA via WebSocket and acts as a conversation agent.
Communication flow:
1. Nanobot connects to HA WebSocket API with long-lived access token
2. Nanobot subscribes to 'nanobot_conversation_request' events
3. When user speaks to HA Assist, HA fires this event
4. Nanobot processes the request via AgentLoop
5. Nanobot fires 'nanobot_conversation_response' event with the reply
6. HA custom component receives response and returns to user
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import HomeAssistantConfig

# Events for communication with HA custom component
EVENT_CONVERSATION_REQUEST = "nanobot_conversation_request"
EVENT_CONVERSATION_RESPONSE = "nanobot_conversation_response"


class HomeAssistantChannel(BaseChannel):
    """
    Home Assistant channel using WebSocket connection.

    Connects to HA as a client, subscribes to conversation request events,
    and responds via firing response events.
    """

    name = "homeassistant"

    def __init__(self, config: HomeAssistantConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: HomeAssistantConfig = config
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._message_id: int = 0
        self._pending_results: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._subscription_id: int | None = None

    def _next_id(self) -> int:
        """Get next message ID for WebSocket communication."""
        self._message_id += 1
        return self._message_id

    async def start(self) -> None:
        """Start the Home Assistant channel."""
        if not self.config.access_token:
            logger.error("Home Assistant access token not configured")
            return

        self._running = True
        self._session = aiohttp.ClientSession()

        while self._running:
            try:
                await self._connect_and_run()
            except Exception as e:
                logger.error("Home Assistant connection error: {}", e)
                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)

    async def _connect_and_run(self) -> None:
        """Connect to HA WebSocket and run the message loop."""
        logger.info("Connecting to Home Assistant at {}", self.config.url)

        async with self._session.ws_connect(self.config.url) as ws:
            self._ws = ws

            # Wait for auth_required message
            msg = await ws.receive_json()
            if msg.get("type") != "auth_required":
                raise ConnectionError(f"Unexpected message: {msg}")

            # Send authentication
            await ws.send_json({
                "type": "auth",
                "access_token": self.config.access_token,
            })

            # Wait for auth result
            msg = await ws.receive_json()
            if msg.get("type") != "auth_ok":
                raise ConnectionError(f"Authentication failed: {msg}")

            logger.info("Connected to Home Assistant (version {})", msg.get("ha_version"))

            # Subscribe to conversation request events
            await self._subscribe_events()

            # Main message loop
            await self._message_loop()

    async def _subscribe_events(self) -> None:
        """Subscribe to conversation request events."""
        msg_id = self._next_id()

        await self._ws.send_json({
            "id": msg_id,
            "type": "subscribe_events",
            "event_type": EVENT_CONVERSATION_REQUEST,
        })

        # Wait for subscription confirmation
        msg = await self._ws.receive_json()
        if msg.get("success"):
            self._subscription_id = msg_id
            logger.info("Subscribed to {} events", EVENT_CONVERSATION_REQUEST)
        else:
            raise ConnectionError(f"Failed to subscribe: {msg}")

    async def _message_loop(self) -> None:
        """Process incoming WebSocket messages."""
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    logger.error("Invalid JSON from HA: {}", e)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error("WebSocket error: {}", self._ws.exception())
                break
            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                logger.info("WebSocket closed")
                break

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Handle a message from HA WebSocket."""
        msg_type = data.get("type")

        if msg_type == "event":
            event = data.get("event", {})
            event_type = event.get("event_type")

            if event_type == EVENT_CONVERSATION_REQUEST:
                await self._handle_conversation_request(event.get("data", {}))

        elif msg_type == "result":
            msg_id = data.get("id")
            if msg_id in self._pending_results:
                self._pending_results[msg_id].set_result(data)

    async def _handle_conversation_request(self, event_data: dict[str, Any]) -> None:
        """Handle an incoming conversation request from HA."""
        request_id = event_data.get("request_id")
        message = event_data.get("message", "")
        conversation_id = event_data.get("conversation_id")
        language = event_data.get("language")

        if not request_id or not message:
            logger.warning("Invalid conversation request: {}", event_data)
            return

        logger.debug("HA conversation request [{}]: {}", request_id, message[:50])

        # Use request_id as both sender_id and chat_id since HA handles user identity
        # The session will be keyed by conversation_id if provided
        session_key = f"ha:{conversation_id}" if conversation_id else None

        await super()._handle_message(
            sender_id="homeassistant",
            chat_id=request_id,  # Use request_id as chat_id for routing response
            content=message,
            metadata={
                "request_id": request_id,
                "conversation_id": conversation_id,
                "language": language,
            },
            session_key=session_key,
        )

    async def _fire_event(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Fire an event on HA."""
        if not self._ws:
            logger.warning("Cannot fire event: not connected to HA")
            return

        msg_id = self._next_id()

        await self._ws.send_json({
            "id": msg_id,
            "type": "fire_event",
            "event_type": event_type,
            "event_data": event_data,
        })

        logger.debug("Fired HA event {}: {}", event_type, event_data.get("request_id"))

    async def send(self, msg: OutboundMessage) -> None:
        """Send a response back to HA via event."""
        if not self._ws:
            logger.warning("Cannot send: not connected to HA")
            return

        # Skip progress messages - HA expects a single final response
        if msg.metadata.get("_progress"):
            return

        request_id = msg.chat_id  # We used request_id as chat_id
        conversation_id = msg.metadata.get("conversation_id")

        await self._fire_event(EVENT_CONVERSATION_RESPONSE, {
            "request_id": request_id,
            "response": msg.content,
            "conversation_id": conversation_id,
        })

        logger.debug("Sent HA response [{}]: {}...", request_id, (msg.content or "")[:50])

    async def stop(self) -> None:
        """Stop the Home Assistant channel."""
        self._running = False

        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._ws = None

        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

        logger.info("Home Assistant channel stopped")
