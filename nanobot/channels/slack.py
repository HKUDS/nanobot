"""Slack channel implementation using slack-bolt with Socket Mode."""

import asyncio
import re

from loguru import logger
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import SlackConfig


def _markdown_to_slack_mrkdwn(text: str) -> str:
    """
    Convert markdown to Slack mrkdwn format.
    """
    if not text:
        return ""

    # 1. Extract and protect code blocks
    code_blocks: list[str] = []
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)

    # 2. Extract and protect inline code
    inline_codes: list[str] = []
    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # 3. Convert bold **text** to *text*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

    # 4. Convert links [text](url) to <url|text>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<\2|\1>', text)

    # 5. Restore inline code with backticks
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00IC{i}\x00", f"`{code}`")

    # 6. Restore code blocks with triple backticks
    for i, code in enumerate(code_blocks):
        text = text.replace(f"\x00CB{i}\x00", f"```{code}```")

    return text


class SlackChannel(BaseChannel):
    """
    Slack channel using Socket Mode (WebSocket).

    No public server needed - uses WebSocket connection.
    """

    name = "slack"

    def __init__(self, config: SlackConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: SlackConfig = config
        self._app: AsyncApp | None = None
        self._handler: AsyncSocketModeHandler | None = None
        self._bot_user_id: str | None = None

    async def start(self) -> None:
        """Start the Slack bot with Socket Mode."""
        if not self.config.bot_token or not self.config.app_token:
            logger.error("Slack bot_token and app_token must be configured")
            return

        self._running = True

        # Create Slack app
        self._app = AsyncApp(token=self.config.bot_token)

        # Register message event handler
        @self._app.event("message")
        async def handle_message(event, say):
            await self._on_message(event, say)

        # Get bot user ID
        try:
            auth_response = await self._app.client.auth_test()
            self._bot_user_id = auth_response["user_id"]
            logger.info(f"Slack bot user ID: {self._bot_user_id}")
        except Exception as e:
            logger.error(f"Failed to get bot user ID: {e}")
            return

        # Create Socket Mode handler
        self._handler = AsyncSocketModeHandler(self._app, self.config.app_token)

        logger.info("Starting Slack bot (Socket Mode)...")

        # Start the handler (non-blocking)
        await self._handler.start_async()

        logger.info("Slack bot connected via Socket Mode")

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Slack bot."""
        self._running = False

        if self._handler:
            logger.info("Stopping Slack bot...")
            await self._handler.close_async()
            self._handler = None

        self._app = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Slack."""
        if not self._app:
            logger.warning("Slack bot not running")
            return

        try:
            # Convert markdown to Slack mrkdwn
            mrkdwn_content = _markdown_to_slack_mrkdwn(msg.content)

            await self._app.client.chat_postMessage(
                channel=msg.chat_id,
                text=mrkdwn_content
            )
        except Exception as e:
            logger.error(f"Error sending Slack message: {e}")

    async def _on_message(self, event, say) -> None:
        """Handle incoming messages from Slack."""
        # Extract event fields
        user = event.get("user")
        channel = event.get("channel")
        text = event.get("text", "")
        subtype = event.get("subtype")

        # Ignore bot's own messages
        if user == self._bot_user_id:
            return

        # Ignore messages with subtypes (edits, joins, etc.)
        if subtype:
            return

        # Check if user is allowed
        if not user or not self.is_allowed(user):
            return

        logger.debug(f"Slack message from {user}: {text[:50]}...")

        # Forward to the message bus
        await self._handle_message(
            sender_id=user,
            chat_id=channel,
            content=text
        )
