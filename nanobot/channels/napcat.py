"""NapCat channel implementation using OneBot 11 protocol via WebSocket."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import websockets
from loguru import logger
from websockets.client import WebSocketClientProtocol

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import NapCatConfig


class NapCatChannel(BaseChannel):
    """
    NapCat channel using OneBot 11 protocol.

    Connects to NapCatQQ via WebSocket for real-time QQ message handling.
    """

    name = "napcat"
    display_name = "NapCat (QQ)"

    def __init__(self, config: NapCatConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: NapCatConfig = config
        self._ws: WebSocketClientProtocol | None = None
        self._echo_counter = 0
        self._pending_responses: dict[str, asyncio.Future] = {}
        self._bot_qq: int | None = None
        self._http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Start WebSocket connection to NapCatQQ."""
        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)
        logger.info("napcat: connecting to {}", self.config.ws_url)

        while self._running:
            try:
                headers = {}
                if self.config.access_token:
                    headers["Authorization"] = f"Bearer {self.config.access_token}"

                async with websockets.connect(
                    self.config.ws_url,
                    additional_headers=headers,
                ) as ws:
                    self._ws = ws
                    logger.success("napcat: connected")

                    # Get bot info
                    bot_info = await self._call_api("get_login_info")
                    if bot_info:
                        self._bot_qq = bot_info.get("user_id")
                        logger.info("napcat: bot QQ = {}", self._bot_qq)

                    # Listen for events
                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_ws_message(message)

            except Exception as e:
                logger.error("napcat: connection error: {}", e)
                self._pending_responses.clear()
                if self._running:
                    await asyncio.sleep(5)
                else:
                    break

        self._ws = None
        logger.info("napcat: stopped")

    async def stop(self) -> None:
        """Stop the channel."""
        self._running = False
        self._pending_responses.clear()
        if self._ws:
            await self._ws.close()
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send message via OneBot API."""
        if not self._ws:
            logger.warning("napcat: not connected, cannot send message")
            return

        # Get message type from metadata
        is_group = msg.metadata.get("is_group", False)
        target_id = int(msg.chat_id)

        try:
            # Build message content
            if msg.media:
                # Send with media
                await self._send_with_media(target_id, is_group, msg.content, msg.media)
            else:
                # Send text only
                action = "send_group_msg" if is_group else "send_private_msg"
                params = {
                    ("group_id" if is_group else "user_id"): target_id,
                    "message": msg.content
                }
                await self._call_api(action, params)
        except Exception as e:
            logger.error("napcat: send failed: {}", e)

    async def _send_with_media(self, target_id: int, is_group: bool, content: str, media: list[str]) -> None:
        """Send message with media attachments."""
        message_segments = []

        if content:
            message_segments.append({"type": "text", "data": {"text": content}})

        for media_path in media:
            file_param = media_path if media_path.startswith("http") else f"file://{media_path}"
            # Check if it's audio file
            if media_path.endswith(('.mp3', '.wav', '.ogg', '.amr', '.silk')):
                message_segments.append({"type": "record", "data": {"file": file_param}})
            else:
                message_segments.append({"type": "image", "data": {"file": file_param}})

        action = "send_group_msg" if is_group else "send_private_msg"
        params = {
            ("group_id" if is_group else "user_id"): target_id,
            "message": message_segments
        }
        await self._call_api(action, params)

    async def _download_image(self, url: str) -> str | None:
        """Download image from URL and return local path."""
        if not self._http:
            return None

        try:
            resp = await self._http.get(url)
            resp.raise_for_status()

            media_dir = get_media_dir(self.name)
            filename = Path(url).name or f"image_{asyncio.get_event_loop().time()}.jpg"
            filepath = media_dir / filename

            filepath.write_bytes(resp.content)
            return str(filepath)
        except Exception as e:
            logger.warning("napcat: failed to download image {}: {}", url, e)
            return None

    async def _download_audio(self, url: str) -> str | None:
        """Download audio from URL and return local path."""
        if not self._http:
            return None

        try:
            resp = await self._http.get(url)
            resp.raise_for_status()

            media_dir = get_media_dir(self.name)
            filename = f"audio_{asyncio.get_event_loop().time()}.mp3"
            filepath = media_dir / filename

            filepath.write_bytes(resp.content)
            return str(filepath)
        except Exception as e:
            logger.warning("napcat: failed to download audio: {}", e)
            return None

    async def _parse_message_segments(self, message: list | str) -> tuple[str, list[str]]:
        """Parse OneBot 11 message segments, extract text and media."""
        if isinstance(message, str):
            return message, []

        text_parts = []
        media_urls = []

        for seg in message:
            seg_type = seg.get("type")
            data = seg.get("data", {})

            if seg_type == "text":
                text_parts.append(data.get("text", ""))
            elif seg_type == "image":
                file_url = data.get("url") or data.get("file")
                if file_url and file_url.startswith("http"):
                    local_path = await self._download_image(file_url)
                    if local_path:
                        media_urls.append(local_path)
            elif seg_type == "record":
                file_url = data.get("url") or data.get("file")
                if file_url:
                    local_path = await self._download_audio(file_url)
                    if local_path:
                        media_urls.append(local_path)
                        text_parts.append("[语音消息]")
            elif seg_type == "at":
                qq = data.get("qq")
                text_parts.append(f"@{qq}" if qq != "all" else "@全体成员")

        return "".join(text_parts), media_urls

    async def _call_api(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Call OneBot API and wait for response."""
        if not self._ws:
            return None

        self._echo_counter += 1
        echo = f"echo_{self._echo_counter}"

        request = {
            "action": action,
            "params": params or {},
            "echo": echo
        }

        future: asyncio.Future = asyncio.Future()
        self._pending_responses[echo] = future

        try:
            await self._ws.send(json.dumps(request))
            result = await asyncio.wait_for(future, timeout=10.0)
            return result
        except asyncio.TimeoutError:
            logger.warning("napcat: API call {} timeout", action)
            return None
        finally:
            self._pending_responses.pop(echo, None)

    async def _handle_ws_message(self, message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("napcat: invalid JSON: {}", message)
            return

        # Handle API response
        if "echo" in data:
            echo = data["echo"]
            if echo in self._pending_responses:
                future = self._pending_responses[echo]
                if data.get("status") == "ok":
                    future.set_result(data.get("data", {}))
                else:
                    future.set_result(None)
                return

        # Handle event
        post_type = data.get("post_type")
        if post_type == "message":
            await self._handle_message_event(data)
        elif post_type == "notice":
            if self.config.handle_notice_events:
                await self._handle_notice_event(data)
        elif post_type == "request":
            if self.config.handle_request_events:
                await self._handle_request_event(data)

    async def _handle_message_event(self, event: dict[str, Any]) -> None:
        """Handle OneBot message event."""
        message_type = event.get("message_type")
        user_id = str(event.get("user_id", ""))
        raw_message = event.get("message", "")

        if not user_id:
            return

        # Parse message segments
        content, media = await self._parse_message_segments(raw_message)
        if not content and not media:
            return

        # Handle private message
        if message_type == "private":
            if not self.is_allowed(user_id):
                logger.debug("napcat: access denied for user {}", user_id)
                return

            session_key = f"{user_id}:{self.name}"
            await self._handle_message(
                sender_id=user_id,
                chat_id=user_id,
                content=content,
                media=media,
                metadata={"is_group": False},
                session_key=session_key
            )

        # Handle group message
        elif message_type == "group":
            group_id = str(event.get("group_id", ""))
            if not group_id:
                return

            # Check group policy
            if self.config.group_policy == "mention":
                # Check if bot is mentioned
                if isinstance(raw_message, list):
                    mentioned = any(
                        seg.get("type") == "at" and seg.get("data", {}).get("qq") == self._bot_qq
                        for seg in raw_message
                    )
                else:
                    mentioned = self._bot_qq and f"[CQ:at,qq={self._bot_qq}]" in str(raw_message)

                if not mentioned:
                    return

            if not self.is_allowed(user_id):
                logger.debug("napcat: access denied for user {} in group {}", user_id, group_id)
                return

            session_key = f"{group_id}:{self.name}:group"
            await self._handle_message(
                sender_id=user_id,
                chat_id=group_id,
                content=content,
                media=media,
                metadata={"is_group": True},
                session_key=session_key
            )

    async def get_group_member_list(self, group_id: int) -> list[dict]:
        """Get group member list."""
        result = await self._call_api("get_group_member_list", {"group_id": group_id})
        return result if result else []

    async def get_group_member_info(self, group_id: int, user_id: int) -> dict | None:
        """Get group member info."""
        return await self._call_api("get_group_member_info", {
            "group_id": group_id,
            "user_id": user_id
        })

    async def get_friend_list(self) -> list[dict]:
        """Get friend list."""
        result = await self._call_api("get_friend_list")
        return result if result else []

    async def get_group_list(self) -> list[dict]:
        """Get group list."""
        result = await self._call_api("get_group_list")
        return result if result else []

    async def _handle_notice_event(self, event: dict) -> None:
        """Handle notice events."""
        notice_type = event.get("notice_type")

        if notice_type == "group_increase":
            group_id = event.get("group_id")
            user_id = event.get("user_id")
            logger.info("napcat: user {} joined group {}", user_id, group_id)

        elif notice_type == "group_decrease":
            group_id = event.get("group_id")
            user_id = event.get("user_id")
            logger.info("napcat: user {} left group {}", user_id, group_id)

        elif notice_type == "friend_add":
            user_id = event.get("user_id")
            logger.info("napcat: user {} added as friend", user_id)

    async def _handle_request_event(self, event: dict) -> None:
        """Handle request events."""
        request_type = event.get("request_type")
        flag = event.get("flag")
        user_id = event.get("user_id")
        comment = event.get("comment", "")

        if request_type == "friend":
            logger.info("napcat: friend request from {}: {}", user_id, comment)
            if self.config.auto_approve_friend:
                await self._call_api("set_friend_add_request", {
                    "flag": flag,
                    "approve": True
                })
                logger.info("napcat: auto approved friend request from {}", user_id)

        elif request_type == "group":
            sub_type = event.get("sub_type")
            group_id = event.get("group_id")

            if sub_type == "add":
                logger.info("napcat: group join request from {} to group ", user_id, group_id)
            elif sub_type == "invite":
                logger.info("napcat: group invite from {} to group {}", user_id, group_id)

