"""WeChat Official Account channel implementation."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WeChatConfig

if TYPE_CHECKING:
    from nanobot.channels.webhook_server import WebhookServer


class WeChatChannel(BaseChannel):
    """
    WeChat Official Account channel using webhooks.

    WeChat Official Account uses a webhook-based API where:
    - GET requests are for server verification
    - POST requests contain XML-formatted messages
    - Media files are downloaded from temporary URLs
    - Voice messages can be transcribed using Groq

    Features:
    - Text messaging
    - Voice/audio transcription
    - Image and file sharing
    - Signature verification
    - Access control via OpenID
    """

    name = "wechat"

    def __init__(self, config: WeChatConfig, bus: MessageBus, groq_api_key: str = ""):
        super().__init__(config, bus)
        self.config: WeChatConfig = config
        self.groq_api_key = groq_api_key
        self._client = None
        self._message_api = None
        self._webhook_server: "WebhookServer | None" = None

        # Initialize wechatpy client
        self._init_wechat_client()

    def _init_wechat_client(self) -> None:
        """Initialize WeChat client with credentials."""
        if not self.config.app_id or not self.config.app_secret:
            logger.warning("WeChat app_id or app_secret not configured")
            return

        try:
            from wechatpy import WeChatClient
            from wechatpy.client.api import WeChatMessage
            from wechatpy.session.memorystorage import MemoryStorage

            # Create client with automatic token management
            self._client = WeChatClient(
                appid=self.config.app_id,
                secret=self.config.app_secret,
                session=MemoryStorage()
            )
            self._message_api = WeChatMessage(self._client)
            logger.info("WeChat client initialized successfully")

        except ImportError:
            logger.error(
                "wechatpy not installed. Install with: pip install wechatpy"
            )
        except Exception as e:
            logger.error(f"Failed to initialize WeChat client: {e}")

    def register_with_server(self, server: "WebhookServer") -> None:
        """
        Register webhook handlers with the webhook server.

        Args:
            server: The WebhookServer instance to register with.
        """
        self._webhook_server = server
        path = self.config.webhook_path

        # Register both GET (verification) and POST (messages) handlers
        server.register_handler(path, self._handle_request, methods=["GET", "POST"])
        logger.info(f"WeChat webhook registered at {path}")

    async def start(self) -> None:
        """
        Start the WeChat channel.

        Note: The actual HTTP server is managed by WebhookServer.
        This method just marks the channel as running.
        """
        if not self.config.app_id or not self.config.app_secret:
            logger.error("WeChat credentials not configured")
            return

        self._running = True
        logger.info("WeChat channel started")

        # Keep the channel running
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the WeChat channel."""
        self._running = False

        if self._webhook_server:
            self._webhook_server.unregister_handler(self.config.webhook_path)

        logger.info("WeChat channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through WeChat.

        Args:
            msg: The message to send.
        """
        if not self._message_api:
            logger.warning("WeChat client not initialized")
            return

        try:
            # Send text message to user
            self._message_api.send_text(
                user_id=msg.chat_id,
                content=msg.content
            )
            logger.debug(f"Sent WeChat message to {msg.chat_id}")

        except Exception as e:
            logger.error(f"Error sending WeChat message: {e}")

    async def _handle_request(self, request: web.Request) -> web.Response:
        """
        Handle incoming webhook requests.

        GET requests: Server verification
        POST requests: Incoming messages
        """
        if request.method == "GET":
            return await self._handle_verification(request)
        elif request.method == "POST":
            return await self._handle_webhook(request)
        else:
            return web.Response(status=405, text="Method not allowed")

    async def _handle_verification(self, request: web.Request) -> web.Response:
        """
        Handle WeChat server verification (GET request).

        When configuring the webhook in WeChat admin panel, WeChat sends
        a GET request with signature, timestamp, nonce, and echostr params.
        We need to verify the signature and return the echostr.

        Args:
            request: The aiohttp GET request.

        Returns:
            Response with echostr if valid, error otherwise.
        """
        try:
            from wechatpy.utils import check_signature
            from wechatpy.exceptions import InvalidSignatureException

            # Extract query parameters
            signature = request.query.get("signature", "")
            timestamp = request.query.get("timestamp", "")
            nonce = request.query.get("nonce", "")
            echostr = request.query.get("echostr", "")

            logger.info(
                f"WeChat verification request from {request.remote}: "
                f"signature={signature[:8]}..., timestamp={timestamp}"
            )

            # Verify signature
            check_signature(self.config.token, signature, timestamp, nonce)

            logger.info("WeChat signature verification successful")
            return web.Response(text=echostr)

        except InvalidSignatureException:
            logger.error("WeChat signature verification failed - invalid signature")
            return web.Response(status=403, text="Invalid signature")
        except Exception as e:
            logger.error(f"WeChat verification error: {e}")
            return web.Response(status=400, text=f"Verification error: {e}")

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """
        Handle incoming WeChat messages (POST request).

        WeChat sends XML-formatted messages in the POST body.
        We need to verify the signature, parse the message, and route it.

        Args:
            request: The aiohttp POST request.

        Returns:
            Success response (must respond within 5 seconds).
        """
        try:
            from wechatpy.utils import check_signature
            from wechatpy.exceptions import InvalidSignatureException
            from wechatpy.messages import MESSAGE_TYPES
            from wechatpy import parse_message

            # Extract query parameters for signature verification
            signature = request.query.get("signature", "")
            timestamp = request.query.get("timestamp", "")
            nonce = request.query.get("nonce", "")

            # Verify signature
            try:
                check_signature(self.config.token, signature, timestamp, nonce)
            except InvalidSignatureException:
                logger.error("WeChat webhook signature verification failed")
                return web.Response(status=403, text="Invalid signature")

            # Read XML body
            xml_body = await request.text()

            # Parse message
            msg = parse_message(xml_body)
            logger.debug(f"WeChat message type: {msg.type}, from: {msg.source}")

            # Process message asynchronously (WeChat requires response within 5 seconds)
            asyncio.create_task(self._process_message(msg))

            # Return success immediately
            return web.Response(text="success")

        except Exception as e:
            logger.error(f"WeChat webhook error: {e}")
            return web.Response(status=500, text="Internal error")

    async def _process_message(self, msg) -> None:
        """
        Process a WeChat message asynchronously.

        This runs in the background so we can respond to WeChat quickly
        while processing the message fully.

        Args:
            msg: Parsed wechatpy message object.
        """
        try:
            sender_id = msg.source  # WeChat OpenID
            chat_id = msg.source

            # Route by message type
            if msg.type == "text":
                await self._handle_text_message(msg, sender_id, chat_id)
            elif msg.type == "voice":
                await self._handle_voice_message(msg, sender_id, chat_id)
            elif msg.type == "image":
                await self._handle_image_message(msg, sender_id, chat_id)
            elif msg.type == "file":
                await self._handle_file_message(msg, sender_id, chat_id)
            else:
                logger.debug(f"Unsupported WeChat message type: {msg.type}")

        except Exception as e:
            logger.error(f"Error processing WeChat message: {e}")

    async def _handle_text_message(self, msg, sender_id: str, chat_id: str) -> None:
        """Handle text messages."""
        content = msg.content
        logger.debug(f"WeChat text from {sender_id}: {content[:50]}...")

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            metadata={
                "message_id": msg.id,
                "create_time": msg.create_time
            }
        )

    async def _handle_voice_message(self, msg, sender_id: str, chat_id: str) -> None:
        """
        Handle voice messages.

        Downloads the voice file and transcribes it using Groq.
        """
        try:
            # Download voice file
            media_id = msg.media_id
            voice_path = await self._download_media(media_id, "voice")

            # Transcribe using Groq
            transcription = None
            if self.groq_api_key and voice_path:
                try:
                    from nanobot.providers.transcription import GroqTranscriptionProvider
                    transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
                    transcription = await transcriber.transcribe(voice_path)
                    if transcription:
                        logger.info(f"Transcribed WeChat voice: {transcription[:50]}...")
                except Exception as e:
                    logger.error(f"Voice transcription failed: {e}")

            # Build content
            if transcription:
                content = f"[transcription: {transcription}]"
            else:
                content = f"[voice: {voice_path}]"

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=[str(voice_path)] if voice_path else [],
                metadata={
                    "message_id": msg.id,
                    "media_id": media_id,
                    "format": getattr(msg, "format", "unknown")
                }
            )

        except Exception as e:
            logger.error(f"Error handling WeChat voice message: {e}")
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content="[voice: download failed]"
            )

    async def _handle_image_message(self, msg, sender_id: str, chat_id: str) -> None:
        """Handle image messages."""
        try:
            media_id = msg.media_id
            image_path = await self._download_media(media_id, "image")

            content = f"[image: {image_path}]" if image_path else "[image: download failed]"

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=[str(image_path)] if image_path else [],
                metadata={
                    "message_id": msg.id,
                    "media_id": media_id,
                    "pic_url": getattr(msg, "pic_url", "")
                }
            )

        except Exception as e:
            logger.error(f"Error handling WeChat image message: {e}")

    async def _handle_file_message(self, msg, sender_id: str, chat_id: str) -> None:
        """Handle file messages."""
        try:
            media_id = msg.media_id
            file_path = await self._download_media(media_id, "file")

            content = f"[file: {file_path}]" if file_path else "[file: download failed]"

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=[str(file_path)] if file_path else [],
                metadata={
                    "message_id": msg.id,
                    "media_id": media_id
                }
            )

        except Exception as e:
            logger.error(f"Error handling WeChat file message: {e}")

    async def _download_media(self, media_id: str, media_type: str) -> Path | None:
        """
        Download media from WeChat servers.

        Args:
            media_id: WeChat media ID.
            media_type: Type of media (voice, image, file).

        Returns:
            Path to downloaded file, or None if download failed.
        """
        if not self._client:
            logger.error("WeChat client not initialized")
            return None

        try:
            # Create media directory
            media_dir = Path.home() / ".nanobot" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)

            # Download media
            response = self._client.media.download(media_id)

            # Determine file extension
            ext = self._get_extension(media_type, response.headers.get("Content-Type"))

            # Save file
            file_path = media_dir / f"wechat_{media_id[:16]}{ext}"
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)

            logger.debug(f"Downloaded WeChat {media_type} to {file_path}")
            return file_path

        except Exception as e:
            logger.error(f"Failed to download WeChat media {media_id}: {e}")
            return None

    def _get_extension(self, media_type: str, content_type: str | None) -> str:
        """Get file extension based on media type and content type."""
        # Try content type first
        if content_type:
            ext_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "audio/amr": ".amr",
                "audio/speex": ".speex",
                "audio/mp3": ".mp3",
                "audio/mpeg": ".mp3",
            }
            if content_type in ext_map:
                return ext_map[content_type]

        # Fallback to media type
        type_map = {
            "image": ".jpg",
            "voice": ".amr",
            "audio": ".mp3",
            "file": ""
        }
        return type_map.get(media_type, "")
