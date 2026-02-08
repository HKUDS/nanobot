"""DingTalk channel implementation using dingtalk-stream SDK with WebSocket long connection."""

import asyncio
import json
import re
import threading
from collections import OrderedDict
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import DingTalkConfig

try:
    from dingtalk_stream import AckMessage, ChatbotMessage
    import dingtalk_stream
    DINGTALK_AVAILABLE = True
except ImportError:
    DINGTALK_AVAILABLE = False
    dingtalk_stream = None

# Message type display mapping
MSG_TYPE_MAP = {
    "picture": "[图片]",
    "audio": "[语音]",
    "video": "[视频]",
    "file": "[文件]",
    "richText": "[富文本]",
}


class DingTalkChannel(BaseChannel):
    """
    DingTalk channel using WebSocket long connection (Stream mode).

    Uses WebSocket to receive events - no public IP or webhook required.

    Requires:
    - Client ID (App Key) and Client Secret from DingTalk Open Platform
    - Bot capability enabled
    - Event subscription enabled (Stream mode)
    """

    name = "dingtalk"

    def __init__(self, config: DingTalkConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: DingTalkConfig = config
        self._client: Any = None
        self._stream_client: Any = None
        self._chatbot_handler: Any = None
        self._stream_thread: threading.Thread | None = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()  # Ordered dedup cache
        self._loop: asyncio.AbstractEventLoop | None = None
        self._access_token: str | None = None
        self._token_expiry: float = 0
        self._active_cards: dict[str, dict] = {}  # Track active AI cards by chat_id

    def _debug(self, msg: str) -> None:
        """Log debug message if debug mode is enabled."""
        if self.config.debug:
            logger.debug(f"[DingTalk] {msg}")

    async def start(self) -> None:
        """Start the DingTalk bot with WebSocket long connection."""
        if not DINGTALK_AVAILABLE:
            logger.error("DingTalk SDK not installed. Run: pip install dingtalk-stream")
            return

        if not self.config.client_id or not self.config.client_secret:
            logger.error("DingTalk client_id and client_secret not configured")
            return

        self._running = True
        self._loop = asyncio.get_running_loop()

        self._debug(f"Initializing DingTalk Stream client with client_id: {self.config.client_id[:10]}...")
        self._debug(f"Debug mode: {self.config.debug}")
        self._debug(f"Message type: {self.config.message_type}")
        self._debug(f"Robot code: {self.config.robot_code or 'using client_id'}")

        try:
            # Create credential config
            self._debug("Creating credential object...")
            credential = dingtalk_stream.Credential(
                self.config.client_id,
                self.config.client_secret
            )
            self._debug("Credential object created")

            # Create stream client (main client)
            self._debug("Creating DingTalkStreamClient instance...")
            self._stream_client = dingtalk_stream.DingTalkStreamClient(credential)
            self._debug("DingTalkStreamClient created successfully")

            # Create chatbot handler
            self._debug("Creating ChatbotHandler instance...")
            self._chatbot_handler = dingtalk_stream.ChatbotHandler()
            self._debug("ChatbotHandler created successfully")

            # Register our custom message handler to the chatbot handler
            # We need to override the process method
            original_process = self._chatbot_handler.process

            def custom_process(callback_message):
                self._debug(f"ChatbotHandler.process called with message")

                # Extract message data from callback_message.data
                if not hasattr(callback_message, 'data') or not callback_message.data:
                    logger.warning("callback_message has no data attribute")
                    return dingtalk_stream.AckMessage.STATUS_OK

                message_data = callback_message.data
                self._debug(f"Message data: msgId={message_data.get('msgId')}, msgtype={message_data.get('msgtype')}")

                # Schedule async handling in the main event loop
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._on_message(message_data),
                        self._loop
                    )
                # Return success response
                return dingtalk_stream.AckMessage.STATUS_OK

            self._chatbot_handler.process = custom_process
            self._debug("Custom message handler registered")

            # Register chatbot handler to stream client
            self._debug(f"Registering handler for topic: {dingtalk_stream.ChatbotMessage.TOPIC}")
            self._stream_client.register_callback_handler(
                dingtalk_stream.ChatbotMessage.TOPIC,
                self._chatbot_handler
            )
            self._debug("Handler registered to stream client")
        except Exception as e:
            logger.error(f"Failed to initialize DingTalk Stream client: {e}")
            logger.exception("Full traceback:")
            return

        # Start stream client in a separate thread
        def run_stream():
            try:
                self._debug("Starting stream client...")
                self._stream_client.start_forever()
            except Exception as e:
                logger.error(f"DingTalk Stream error: {e}")
                logger.exception("Full traceback:")

        self._stream_thread = threading.Thread(target=run_stream, daemon=True)
        self._stream_thread.start()

        logger.info("DingTalk bot started with WebSocket long connection")
        logger.info("No public IP required - using Stream mode to receive events")

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the DingTalk bot."""
        self._running = False
        if self._stream_client:
            try:
                self._stream_client.stop()
            except Exception as e:
                logger.warning(f"Error stopping Stream client: {e}")
        logger.info("DingTalk bot stopped")

    async def _create_ai_card(self, chat_id: str, conversation_id: str, is_group: bool) -> dict | None:
        """Create and deliver an AI Card."""
        import aiohttp
        from uuid import uuid4

        try:
            token = await self._get_access_token()
            card_id = f"card_{uuid4().hex}"

            self._debug(f"Creating AI Card: {card_id}")

            # Build the createAndDeliver request
            url = "https://api.dingtalk.com/v1.0/card/instances/createAndDeliver"

            payload = {
                "cardTemplateId": self.config.card_template_id,
                "outTrackId": card_id,
                "cardData": {
                    "cardParamMap": {}
                },
                "callbackType": "STREAM",
                "imGroupOpenSpaceModel": {"supportForward": True},
                "imRobotOpenSpaceModel": {"supportForward": True},
                "openSpaceId": f"dtv1.card//IM_GROUP.{conversation_id}" if is_group else f"dtv1.card//IM_ROBOT.{conversation_id}",
                "userIdType": 1,
            }

            if is_group:
                payload["imGroupOpenDeliverModel"] = {
                    "robotCode": self.config.robot_code or self.config.client_id
                }
            else:
                payload["imRobotOpenDeliverModel"] = {"spaceType": "IM_ROBOT"}

            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        result = await resp.text()
                        logger.error(f"Failed to create AI Card: {resp.status} {result}")
                        return None

                    result = await resp.json()
                    self._debug(f"AI Card created: {result}")

                    # Store card info
                    card_info = {
                        "card_id": card_id,
                        "conversation_id": conversation_id,
                        "is_group": is_group,
                        "state": "PROCESSING"
                    }
                    self._active_cards[chat_id] = card_info

                    return card_info

        except Exception as e:
            logger.error(f"Error creating AI Card: {e}")
            return None

    async def _update_ai_card(self, card_info: dict, content: str, finished: bool = False) -> bool:
        """Stream update AI Card content."""
        import aiohttp

        try:
            token = await self._get_access_token()
            card_id = card_info["card_id"]

            url = "https://api.dingtalk.com/v1.0/card/streaming"

            payload = {
                "outTrackId": card_id,
                "guid": card_id,
                "key": self.config.card_content_key,
                "content": content,
                "isFull": True,  # Always replace full content
                "isFinalize": finished,
                "isError": False
            }

            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.put(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        result = await resp.text()
                        logger.error(f"Failed to update AI Card: {resp.status} {result}")
                        return False

                    if finished:
                        card_info["state"] = "FINISHED"
                        self._debug(f"AI Card finished: {card_id}")
                    else:
                        card_info["state"] = "INPUTING"

                    return True

        except Exception as e:
            logger.error(f"Error updating AI Card: {e}")
            return False

    async def _get_access_token(self) -> str:
        """Get access token with caching."""
        import time
        import aiohttp

        # Return cached token if still valid
        if self._access_token and time.time() < self._token_expiry:
            self._debug(f"Using cached access token (expires in {int(self._token_expiry - time.time())}s)")
            return self._access_token

        # Get new token
        self._debug("Fetching new access token...")
        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        data = {
            "appKey": self.config.client_id,
            "appSecret": self.config.client_secret
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data) as resp:
                result = await resp.json()
                self._access_token = result["accessToken"]
                self._token_expiry = time.time() + result["expireIn"] - 60  # Refresh 60s early
                self._debug(f"Access token obtained, expires in {result['expireIn']}s")
                return self._access_token

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through DingTalk."""
        import aiohttp

        try:
            # Determine if it's a group or private chat
            # Group conversation IDs start with "cid", user IDs don't
            is_group = msg.chat_id.startswith("cid")
            self._debug(f"Sending message to {'group' if is_group else 'user'}: {msg.chat_id}")

            # Check if we should use Card mode
            if self.config.message_type == "card":
                self._debug("Using Card mode")

                # For Card mode, we need the actual conversation_id
                # For private chat, chat_id is staffId, we need to get conversationId from metadata
                # For now, we'll use chat_id as conversationId for groups
                conversation_id = msg.chat_id if is_group else msg.chat_id

                # Create AI Card
                card_info = await self._create_ai_card(msg.chat_id, conversation_id, is_group)
                if not card_info:
                    logger.error("Failed to create AI Card, falling back to markdown")
                    # Fall back to markdown mode
                else:
                    # Update card with content and mark as finished
                    success = await self._update_ai_card(card_info, msg.content, finished=True)
                    if success:
                        self._debug(f"Card message sent to {msg.chat_id}")
                        # Clean up card from active cards
                        if msg.chat_id in self._active_cards:
                            del self._active_cards[msg.chat_id]
                        return
                    else:
                        logger.error("Failed to update AI Card, falling back to markdown")
                        # Fall back to markdown mode

            # Standard markdown/text mode (or fallback from Card mode)
            token = await self._get_access_token()

            # Detect if content has markdown
            has_markdown = bool(re.search(r'[#*`\[\]_]|```', msg.content))
            use_markdown = self.config.message_type == "markdown" or (self.config.message_type == "card" and has_markdown)
            self._debug(f"Message format: {'markdown' if use_markdown else 'text'} (has_markdown={has_markdown})")

            # Build message body
            if use_markdown:
                # Extract title from first line or use default
                title = msg.content.split('\n')[0][:20] or "Nanobot 消息"
                title = re.sub(r'^[#*\s\->]+', '', title)

                body = {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": title,
                        "text": msg.content
                    }
                }
            else:
                body = {
                    "msgtype": "text",
                    "text": {
                        "content": msg.content
                    }
                }

            # Send via appropriate API
            if is_group:
                # Group message API
                url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
                payload = {
                    "robotCode": self.config.robot_code or self.config.client_id,
                    "msgKey": "sampleMarkdown" if use_markdown else "sampleText",
                    "msgParam": json.dumps({
                        "title": title if use_markdown else "",
                        "text": msg.content
                    } if use_markdown else {"content": msg.content}),
                    "openConversationId": msg.chat_id
                }
            else:
                # Private message API
                url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
                payload = {
                    "robotCode": self.config.robot_code or self.config.client_id,
                    "msgKey": "sampleMarkdown" if use_markdown else "sampleText",
                    "msgParam": json.dumps({
                        "title": title if use_markdown else "",
                        "text": msg.content
                    } if use_markdown else {"content": msg.content}),
                    "userIds": [msg.chat_id]
                }

            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json"
            }

            self._debug(f"Sending to API: {url}")
            if self.config.debug:
                # Mask sensitive data in debug output
                debug_payload = payload.copy()
                if "msgParam" in debug_payload:
                    debug_payload["msgParam"] = f"<{len(payload['msgParam'])} chars>"
                self._debug(f"Payload: {debug_payload}")

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        result = await resp.text()
                        logger.error(f"Failed to send DingTalk message: {resp.status} {result}")
                        self._debug(f"Error response: {result}")
                    else:
                        result = await resp.json()
                        self._debug(f"Message sent successfully: {result}")
                        logger.debug(f"DingTalk message sent to {msg.chat_id}")

        except Exception as e:
            logger.error(f"Error sending DingTalk message: {e}")

    def _on_message_sync(self, dingtalk_message: ChatbotMessage, *args) -> AckMessage:
        """
        Sync handler for incoming messages (called from Stream thread).
        Schedules async handling in the main event loop.
        """
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(dingtalk_message), self._loop)

        # Return ACK to DingTalk
        return AckMessage.STATUS_OK, "OK"

    async def _on_message(self, message_data: dict) -> None:
        """Handle incoming message from DingTalk."""
        try:
            # Get message data from dict
            msg_id = message_data.get('msgId')
            self._debug(f"Received message: msg_id={msg_id}")

            # Deduplication check
            if msg_id in self._processed_message_ids:
                self._debug(f"Duplicate message detected, skipping: {msg_id}")
                return
            self._processed_message_ids[msg_id] = None

            # Trim cache: keep most recent 500 when exceeds 1000
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            # Extract message info
            sender_id = message_data.get('senderId')
            sender_staff_id = message_data.get('senderStaffId')  # This is the actual staffId
            conversation_id = message_data.get('conversationId')
            conversation_type = message_data.get('conversationType')  # "1" for private, "2" for group
            msg_type = message_data.get('msgtype')

            self._debug(f"Message details: sender={sender_id}, staffId={sender_staff_id}, conversation={conversation_id}, type={conversation_type}, msgtype={msg_type}")

            # Check allowlist (use sender_id for allowlist check)
            if self.config.allow_from and sender_id not in self.config.allow_from:
                logger.debug(f"Ignoring message from non-allowed user: {sender_id}")
                self._debug(f"User {sender_id} not in allowlist: {self.config.allow_from}")
                return

            # Parse message content
            content = self._extract_content(message_data)
            self._debug(f"Extracted content: {content[:100]}..." if len(content) > 100 else f"Extracted content: {content}")

            if not content:
                self._debug("Empty content, skipping message")
                return

            # Determine reply target
            # For private chat (type="1"), use senderStaffId
            # For group chat (type="2"), use conversationId
            if conversation_type == "2":
                reply_to = conversation_id
            else:
                # For private chat, use staffId if available, otherwise use senderId
                reply_to = sender_staff_id if sender_staff_id else sender_id

            self._debug(f"Reply target: {reply_to} (type={'group' if conversation_type == '2' else 'private'})")

            # Forward to message bus
            await self._handle_message(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                metadata={
                    "message_id": msg_id,
                    "conversation_type": conversation_type,
                    "msg_type": msg_type,
                }
            )

        except Exception as e:
            logger.error(f"Error processing DingTalk message: {e}")

    def _extract_content(self, message_data: dict) -> str:
        """Extract text content from DingTalk message data."""
        msg_type = message_data.get('msgtype')
        self._debug(f"Extracting content from message type: {msg_type}")

        # Text message
        if msg_type == "text":
            text_obj = message_data.get('text')
            if text_obj and isinstance(text_obj, dict):
                content = text_obj.get('content', '').strip()
                self._debug(f"Text message content: {content}")
                return content
            self._debug("Text message has no content")
            return ""

        # Rich text message (contains text, @mentions, and inline images)
        if msg_type == "richText":
            content_obj = message_data.get('content')
            if content_obj and isinstance(content_obj, dict):
                rich_text_parts = content_obj.get('richText', [])
                self._debug(f"Rich text has {len(rich_text_parts)} parts")
                text_parts = []
                for i, part in enumerate(rich_text_parts):
                    if isinstance(part, dict):
                        if part.get('text'):
                            text_parts.append(part['text'])
                            self._debug(f"Part {i}: text='{part['text']}'")
                        elif part.get('type') == 'at' and part.get('atName'):
                            text_parts.append(f"@{part['atName']}")
                            self._debug(f"Part {i}: @mention={part['atName']}")
                        else:
                            self._debug(f"Part {i}: type={part.get('type', 'unknown')}")
                result = " ".join(text_parts).strip() or "[富文本消息]"
                self._debug(f"Rich text result: {result}")
                return result
            self._debug("Rich text has no content")
            return "[富文本消息]"

        # Other message types
        result = MSG_TYPE_MAP.get(msg_type, f"[{msg_type}消息]")
        self._debug(f"Unsupported message type, returning: {result}")
        return result
