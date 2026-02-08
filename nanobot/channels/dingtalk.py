"""DingTalk (钉钉) channel implementation using Stream Mode (WebSocket).

Uses the official dingtalk-stream SDK for proper WebSocket communication.
"""

import asyncio
import json
import logging
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import DingTalkConfig

try:
    import dingtalk_stream
    DINGTALK_AVAILABLE = True
except ImportError:
    DINGTALK_AVAILABLE = False

if TYPE_CHECKING:
    from dingtalk_stream import ChatbotMessage


class DingTalkChannel(BaseChannel):
    """
    DingTalk channel using Stream Mode (WebSocket).

    Uses the official dingtalk-stream SDK for proper WebSocket communication.
    No public IP or webhook required.

    Requires:
    - AppKey and AppSecret from DingTalk Open Platform
    - Bot created in DingTalk Developer Console
    - Stream Mode enabled
    """

    name = "dingtalk"

    def __init__(self, config: DingTalkConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: DingTalkConfig = config
        self._client: Any = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._message_handler: "DingTalkMessageHandler | None" = None
        self._access_token: str | None = None

    async def start(self) -> None:
        """Start the DingTalk bot with Stream Mode."""
        if not DINGTALK_AVAILABLE:
            logger.error("dingtalk-stream library not installed. Run: pip install dingtalk-stream")
            return

        if not self.config.app_key or not self.config.app_secret:
            logger.error("DingTalk app_key and app_secret not configured")
            return

        self._running = True

        # Get the current event loop
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = asyncio.get_event_loop()

        try:
            # Create credential
            credential = dingtalk_stream.Credential(
                client_id=self.config.app_key,
                client_secret=self.config.app_secret
            )

            # Create message handler with event loop
            self._message_handler = DingTalkMessageHandler(
                channel=self,
                loop=self._loop,
                max_workers=8
            )

            # Create client
            self._client = dingtalk_stream.DingTalkStreamClient(credential)

            # Register callback handler for chatbot messages
            self._client.register_callback_handler(
                dingtalk_stream.ChatbotMessage.TOPIC,
                self._message_handler
            )

            logger.info("DingTalk bot starting with Stream Mode...")
            logger.info("No public IP required - using official SDK")

            # Get access token for sending messages
            self._access_token = await self._get_access_token()

            # Start the client in a separate thread (it's blocking)
            def run_client():
                try:
                    self._client.start_forever()
                except Exception as e:
                    logger.error(f"DingTalk client error: {e}")

            client_thread = threading.Thread(target=run_client, daemon=True)
            client_thread.start()

            # Wait a bit for the client to connect
            await asyncio.sleep(2)
            logger.info("DingTalk Stream Mode client started")

            # Keep running until stopped
            while self._running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error starting DingTalk client: {e}")

    async def stop(self) -> None:
        """Stop the DingTalk bot."""
        self._running = False
        if self._client:
            try:
                # The SDK doesn't have a clean shutdown method
                # We'll just mark ourselves as stopped
                pass
            except Exception:
                pass
        logger.info("DingTalk bot stopped")

    async def _get_access_token(self) -> str | None:
        """Get access token from DingTalk API for sending messages."""
        if not self._client:
            return None
        try:
            return self._client.get_access_token()
        except Exception as e:
            logger.error(f"Error getting access token: {e}")
            return None

    @staticmethod
    def _convert_markdown_tables(content: str) -> str:
        """
        Convert markdown tables to code blocks (DingTalk doesn't support tables).

        This function detects markdown tables and converts them to code blocks
        so they can be displayed in DingTalk.
        """
        import re

        lines = content.split('\n')
        result = []
        in_table = False
        table_lines = []

        for line in lines:
            # Check if this line looks like a table row
            # Table rows contain | separators and have content
            if '|' in line and line.strip().startswith('|'):
                if not in_table:
                    in_table = True
                    table_lines = []
                table_lines.append(line)
            elif in_table:
                # Table has ended
                in_table = False
                # Convert table to code block
                if table_lines:
                    table_text = '\n'.join(table_lines)
                    result.append('```\n' + table_text + '\n```')
                    result.append('')  # Add empty line after table
                table_lines = []
                result.append(line)
            else:
                result.append(line)

        # Handle table at the end
        if in_table and table_lines:
            table_text = '\n'.join(table_lines)
            if result:
                result[-1] = '```\n' + table_text + '\n```'
            else:
                result.append('```\n' + table_text + '\n```')

        return '\n'.join(result)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through DingTalk."""
        if not DINGTALK_AVAILABLE:
            logger.warning("dingtalk-stream library not available")
            return

        # Get sessionWebhook from metadata
        session_webhook = msg.metadata.get("session_webhook", "")

        if not session_webhook:
            logger.warning("No session_webhook available for sending reply")
            return

        try:
            import requests

            # Convert markdown tables to code blocks (DingTalk doesn't support tables)
            converted_content = self._convert_markdown_tables(msg.content)

            # Use sessionWebhook for sending replies with markdown format
            data = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "Bot Message",
                    "text": converted_content
                }
            }

            headers = {
                "Content-Type": "application/json"
            }

            logger.info(f"Sending via sessionWebhook (markdown) - content: {msg.content[:50]}...")

            # Send the message
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(session_webhook, headers=headers, json=data, timeout=10)
            )

            result = response.json()

            # sessionWebhook returns {"errcode": 0} on success
            if result.get("errcode") == 0:
                logger.info("DingTalk message sent successfully via sessionWebhook")
            else:
                logger.error(
                    f"Failed to send DingTalk message via sessionWebhook. Status: {response.status_code}, Response: {result}"
                )

        except Exception as e:
            logger.error(f"Error sending DingTalk message: {e}")


class DingTalkMessageHandler(dingtalk_stream.AsyncChatbotHandler if DINGTALK_AVAILABLE else object):
    """
    Handler for DingTalk chatbot messages using the official SDK.

    This class extends AsyncChatbotHandler from the dingtalk-stream SDK
    to receive and process incoming messages.

    Note: The process method must NOT be async - SDK handles threading internally.
    """

    def __init__(self, channel: DingTalkChannel, loop: asyncio.AbstractEventLoop, max_workers: int = 8):
        if DINGTALK_AVAILABLE:
            super().__init__(max_workers=max_workers)
        self.channel = channel
        self._loop = loop  # Store the event loop from the channel
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()

    def process(self, message: dingtalk_stream.CallbackMessage) -> tuple[int, str]:
        """
        Process an incoming chatbot message.

        This method is called by the SDK when a new message is received.
        Note: This must be synchronous - SDK handles threading internally.

        Args:
            message: CallbackMessage object from the SDK

        Returns:
            Tuple of (status_code, message) for ACK response
        """
        try:
            # CallbackMessage.data contains the actual message content (already parsed as dict)
            message_dict = message.data

            # Extract message data from CallbackMessage
            msg_id = message_dict.get("msgId", "")
            sender_id = message_dict.get("senderId", "")
            sender_nick = message_dict.get("senderNick", "")
            sender_staff_id = message_dict.get("senderStaffId", "")
            conversation_id = message_dict.get("conversationId", "")
            conversation_type = message_dict.get("conversationType", "")
            chatbot_id = message_dict.get("chatbotUserId", "")
            session_webhook = message_dict.get("sessionWebhook", "")  # Webhook for sending replies

            # Extract content from message
            content = self._extract_text_content(message_dict)

            # Deduplication check
            if msg_id in self._processed_message_ids:
                logger.debug(f"Duplicate message ignored: {msg_id}")
                return dingtalk_stream.AckMessage.STATUS_OK, "OK"

            self._processed_message_ids[msg_id] = None

            # Trim cache: keep most recent 500 when exceeds 1000
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            if not content:
                logger.debug("Empty message content received")
                return dingtalk_stream.AckMessage.STATUS_OK, "OK"

            # Determine chat_id
            # For group chats (conversationType=1), use conversation_id
            # For p2p chats (conversationType=2), use sender_id
            chat_id = conversation_id if conversation_type == "1" else sender_id

            logger.info(
                f"Received DingTalk message from {sender_nick}({sender_staff_id}) "
                f"in {conversation_type}: {content[:50]}..."
            )

            # Forward to message bus using asyncio
            async def forward_message():
                await self.channel._handle_message(
                    sender_id=sender_staff_id or sender_id,
                    chat_id=chat_id,
                    content=content,
                    metadata={
                        "message_id": msg_id,
                        "sender_nick": sender_nick,
                        "sender_staff_id": sender_staff_id,
                        "conversation_id": conversation_id,
                        "conversation_type": conversation_type,
                        "chatbot_id": chatbot_id,
                        "session_webhook": session_webhook,  # Include webhook for replies
                    }
                )

            # Run the async function in the event loop (from thread pool)
            asyncio.run_coroutine_threadsafe(forward_message(), self._loop)

            return dingtalk_stream.AckMessage.STATUS_OK, "OK"

        except Exception as e:
            logger.error(f"Error processing DingTalk message: {e}", exc_info=True)
            return dingtalk_stream.AckMessage.STATUS_SYSTEM_EXCEPTION, str(e)

    def _extract_text_content(self, message_dict: dict) -> str:
        """Extract text content from a message dict."""
        try:
            # Check msgtype - for text messages it should be "text"
            msg_type = message_dict.get("msgtype", "")

            # For text messages, content is in the "text" field
            if msg_type == "text":
                text_field = message_dict.get("text", {})
                if isinstance(text_field, dict):
                    return text_field.get("content", "")
                elif isinstance(text_field, str):
                    return text_field

            # Try direct text field in message (fallback)
            if "text" in message_dict:
                text_field = message_dict["text"]
                if isinstance(text_field, dict):
                    return text_field.get("content", "")
                elif isinstance(text_field, str):
                    return text_field

            return ""
        except Exception as e:
            logger.debug(f"Error extracting text content: {e}")
            return ""
