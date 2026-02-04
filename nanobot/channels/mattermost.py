"""Mattermost channel implementation using mattermostdriver."""

import asyncio
import json
from urllib.parse import urlparse

from loguru import logger
from mattermostdriver import Driver

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import MattermostConfig


class MattermostChannel(BaseChannel):
    """
    Mattermost channel using WebSocket connection.

    Connects to Mattermost via mattermostdriver and listens for messages.
    """

    name = "mattermost"

    def __init__(self, config: MattermostConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: MattermostConfig = config
        self._driver: Driver | None = None
        self._bot_user_id: str | None = None

    async def start(self) -> None:
        """Start the Mattermost client with WebSocket connection."""
        if not self.config.url or not self.config.token:
            logger.error("Mattermost URL and token must be configured")
            return

        # Parse the URL to extract scheme, host, and port
        parsed = urlparse(self.config.url)

        # Extract scheme (default to https)
        scheme = parsed.scheme or "https"

        # Extract host (without scheme)
        host = parsed.netloc or parsed.path

        # Extract port from netloc if present
        port = None
        if ':' in host:
            host, port_str = host.rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                port = None

        # Default port based on scheme if not specified
        if port is None:
            port = 443 if scheme == "https" else 80

        # Create driver with parsed options
        self._driver = Driver({
            'url': host,
            'token': self.config.token,
            'scheme': scheme,
            'port': port
        })

        try:
            # Login to Mattermost
            self._driver.login()

            # Get bot user info
            user_info = self._driver.users.get_user('me')
            self._bot_user_id = user_info['id']

            logger.info(f"Mattermost bot @{user_info.get('username', 'unknown')} connected")

            # Initialize WebSocket with event handler
            self._driver.init_websocket(self._event_handler)

            self._running = True

            # Keep running until stopped
            while self._running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Failed to start Mattermost client: {e}")
            self._running = False

    def _event_handler(self, event: str) -> None:
        """
        Handle WebSocket events from Mattermost.

        This is called by mattermostdriver's WebSocket in a sync context.
        We need to schedule the async handler.
        """
        try:
            # Parse the event JSON
            data = json.loads(event)

            # Check if this is a posted message event
            if data.get('event') != 'posted':
                return

            # Extract post data
            post_data = data.get('data', {}).get('post', '{}')
            post = json.loads(post_data)

            # Extract message details
            user_id = post.get('user_id')
            channel_id = post.get('channel_id')
            message = post.get('message', '')

            # Ignore messages from the bot itself
            if user_id == self._bot_user_id:
                return

            # Check if sender is allowed
            if not self.is_allowed(user_id):
                logger.debug(f"Ignoring message from unauthorized user: {user_id}")
                return

            # Schedule async message handling
            asyncio.create_task(
                self._handle_message(
                    sender_id=user_id,
                    chat_id=channel_id,
                    content=message
                )
            )

        except Exception as e:
            logger.error(f"Error handling Mattermost event: {e}")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Mattermost."""
        if not self._driver:
            logger.warning("Mattermost driver not running")
            return

        try:
            # Mattermost supports standard markdown, no conversion needed
            self._driver.posts.create_post({
                "channel_id": msg.chat_id,
                "message": msg.content
            })
        except Exception as e:
            logger.error(f"Error sending Mattermost message: {e}")

    async def stop(self) -> None:
        """Stop the Mattermost client."""
        self._running = False

        if self._driver:
            logger.info("Stopping Mattermost client...")
            try:
                self._driver.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting Mattermost: {e}")
            self._driver = None
