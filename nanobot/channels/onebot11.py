"""OneBot 11 channel implementation using reverse WebSocket."""

import asyncio
import json
from collections import deque
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import OneBot11Config

try:
    import websockets

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    websockets = None


def _parse_onebot_message(message: str | list[dict]) -> str:
    """Parse OneBot message (CQ code or array format) to plain text."""
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts = []
        for segment in message:
            seg_type = segment.get("type", "")
            if seg_type == "text":
                parts.append(segment.get("data", {}).get("text", ""))
            elif seg_type == "at":
                qq = segment.get("data", {}).get("qq", "")
                parts.append(f"@{qq}")
            elif seg_type == "face":
                face_id = segment.get("data", {}).get("id", "")
                parts.append(f"[face:{face_id}]")
            elif seg_type in ("image", "record", "video", "file"):
                file_id = segment.get("data", {}).get("file", "")
                parts.append(f"[{seg_type}:{file_id}]")
            elif seg_type == "reply":
                msg_id = segment.get("data", {}).get("id", "")
                parts.append(f"[reply:{msg_id}]")
        return "".join(parts)
    return str(message)


def _format_onebot_message(content: str) -> str:
    """Format message for sending to OneBot."""
    return content


class OneBot11Channel(BaseChannel):
    """OneBot 11 channel using reverse WebSocket connection."""

    name = "onebot11"

    def __init__(self, config: OneBot11Config, bus: MessageBus):
        super().__init__(config, bus)
        self.config: OneBot11Config = config
        self._websocket: websockets.WebSocketClientProtocol | None = None
        self._processed_ids: deque = deque(maxlen=1000)
        self._connect_task: asyncio.Task | None = None
        self._running = False
        self._self_id: int | None = None
        self._reconnect_delay = 3.0

    async def start(self) -> None:
        """Start the OneBot 11 connection."""
        if not WEBSOCKETS_AVAILABLE:
            logger.error("websockets library not installed")
            return

        self._running = True
        self._connect_task = asyncio.create_task(self._run_connection())
        logger.info(f"OneBot 11 channel started (connecting to {self.config.ws_reverse_url})")

    async def _run_connection(self) -> None:
        """Run the WebSocket connection with auto-reconnect."""
        # Build URL with access_token as query parameter
        base_url = self.config.ws_reverse_url

        if self.config.access_token:
            parsed = urlparse(base_url)
            query = parse_qs(parsed.query) if parsed.query else {}
            query["access_token"] = self.config.access_token
            new_query = urlencode(query, doseq=True)
            base_url = parsed._replace(query=new_query).geturl()

        while self._running:
            try:
                async with websockets.connect(
                    base_url,
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    self._websocket = ws
                    logger.info("OneBot 11 connected")

                    # Receive messages
                    async for message in ws:
                        try:
                            event = json.loads(message)
                            await self._handle_onebot_event(event)
                        except json.JSONDecodeError:
                            pass

            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as e:
                logger.error(f"OneBot 11 connection error: {e}")

            if self._running:
                await asyncio.sleep(self._reconnect_delay)

    async def stop(self) -> None:
        """Stop the OneBot 11 connection."""
        self._running = False
        if self._websocket:
            await self._websocket.close()
        if self._connect_task:
            self._connect_task.cancel()
            try:
                await self._connect_task
            except asyncio.CancelledError:
                pass
        logger.info("OneBot 11 channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through OneBot."""
        if not self._websocket:
            return

        try:
            chat_id = msg.chat_id
            message_type = msg.metadata.get("message_type", "") if msg.metadata else ""
            group_id = msg.metadata.get("group_id", "") if msg.metadata else ""

            # For group messages, use group_id from metadata; for private, use chat_id
            if message_type == "group" and group_id:
                target_id = group_id
            else:
                target_id = chat_id

            if message_type == "group" and group_id:
                params = {
                    "group_id": int(target_id),
                    "message": _format_onebot_message(msg.content),
                }
            else:
                params = {
                    "user_id": int(target_id),
                    "message": _format_onebot_message(msg.content),
                }

            request = {
                "action": "send_msg",
                "params": params,
            }

            await self._websocket.send(json.dumps(request))

        except Exception as e:
            logger.error(f"Error sending OneBot message: {e}")

    async def _handle_onebot_event(self, event: dict[str, Any]) -> None:
        """Handle incoming event from OneBot."""
        post_type = event.get("post_type", "")

        if post_type == "message":
            await self._handle_message_event(event)
        elif post_type == "meta_event":
            if event.get("meta_event_type") == "lifecycle" and event.get("sub_type") == "connect":
                self._self_id = event.get("self_id")

    async def _handle_message_event(self, event: dict[str, Any]) -> None:
        """Handle incoming message event."""
        try:
            message_id = event.get("message_id", 0)

            if message_id in self._processed_ids:
                return
            self._processed_ids.append(message_id)

            message_type = event.get("message_type", "")
            user_id = str(event.get("user_id", ""))
            group_id = str(event.get("group_id", ""))

            raw_message = event.get("raw_message", "")
            message = event.get("message", "")
            content = _parse_onebot_message(message) or raw_message

            if not content:
                return

            if self.config.allow_groups and message_type == "group":
                if group_id not in self.config.allow_groups:
                    return

            if message_type == "group":
                sender_id = user_id
                chat_id = group_id
            else:
                sender_id = user_id
                chat_id = user_id

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                metadata={
                    "message_id": message_id,
                    "message_type": message_type,
                    "raw_message": raw_message,
                    "group_id": group_id,
                }
            )

        except Exception as e:
            logger.error(f"Error handling OneBot message: {e}")

    def is_allowed(self, sender_id: str) -> bool:
        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list:
            return True
        sender_str = str(sender_id)
        if sender_str in allow_list:
            return True
        if "|" in sender_str:
            for part in sender_str.split("|"):
                if part and part in allow_list:
                    return True
        return False
