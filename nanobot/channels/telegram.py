"""Telegram channel implementation using python-telegram-bot."""

import asyncio
import mimetypes
import re
from pathlib import Path

from loguru import logger
from telegram import Update, InputFile
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TelegramConfig


# Supported image MIME types for Telegram photos
TELEGRAM_PHOTO_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Maximum caption length for Telegram
MAX_CAPTION_LENGTH = 1024


def _markdown_to_telegram_html(text: str) -> str:
    """
    Convert markdown to Telegram-safe HTML.
    """
    if not text:
        return ""

    # 1. Extract and protect code blocks (preserve content from other processing)
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

    # 3. Headers # Title -> just the title text
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # 4. Blockquotes > text -> just the text (before HTML escaping)
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)

    # 5. Escape HTML special characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Links [text](url) - must be before bold/italic to handle nested cases
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # 7. Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # 8. Italic _text_ (avoid matching inside words like some_var_name)
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)

    # 9. Strikethrough ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # 10. Bullet lists - item -> • item
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 11. Restore inline code with HTML tags
    for i, code in enumerate(inline_codes):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 12. Restore code blocks with HTML tags
    for i, code in enumerate(code_blocks):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text


def _is_image_file(path: Path) -> bool:
    """Check if a file is an image that can be sent as a Telegram photo."""
    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type in TELEGRAM_PHOTO_TYPES:
        return True
    # Also check by extension for common cases
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _truncate_caption(text: str, max_length: int = MAX_CAPTION_LENGTH) -> str:
    """Truncate text to fit Telegram's caption limit."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


class TelegramChannel(BaseChannel):
    """
    Telegram channel using long polling.

    Supports:
    - Text messages with markdown formatting
    - Photo/image sending with captions
    - Document sending

    Simple and reliable - no webhook/public IP needed.
    """

    name = "telegram"

    def __init__(self, config: TelegramConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies

    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return

        self._running = True

        # Build the application
        self._app = (
            Application.builder()
            .token(self.config.token)
            .build()
        )

        # Add message handler for text, photos, voice, documents
        self._app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL)
                & ~filters.COMMAND,
                self._on_message
            )
        )

        # Add /start command handler
        from telegram.ext import CommandHandler
        self._app.add_handler(CommandHandler("start", self._on_start))

        logger.info("Starting Telegram bot (polling mode)...")

        # Initialize and start polling
        await self._app.initialize()
        await self._app.start()

        # Get bot info
        bot_info = await self._app.bot.get_me()
        logger.info(f"Telegram bot @{bot_info.username} connected")

        # Start polling (this runs until stopped)
        await self._app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True  # Ignore old messages on startup
        )

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False

        if self._app:
            logger.info("Stopping Telegram bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through Telegram.

        Handles:
        - Text-only messages
        - Single photo with caption
        - Multiple photos as media group
        - Documents/files
        """
        if not self._app:
            logger.warning("Telegram bot not running")
            return

        try:
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error(f"Invalid chat_id: {msg.chat_id}")
            return

        # Check if we have media to send
        if msg.media:
            await self._send_with_media(chat_id, msg)
        else:
            await self._send_text(chat_id, msg.content)

    async def _send_text(self, chat_id: int, content: str) -> None:
        """Send a text-only message."""
        if not self._app:
            return

        try:
            html_content = _markdown_to_telegram_html(content)
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=html_content,
                parse_mode="HTML"
            )
        except Exception as e:
            # Fallback to plain text if HTML parsing fails
            logger.warning(f"HTML parse failed, falling back to plain text: {e}")
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=content
                )
            except Exception as e2:
                logger.error(f"Error sending Telegram message: {e2}")

    async def _send_with_media(self, chat_id: int, msg: OutboundMessage) -> None:
        """Send message with media attachments."""
        if not self._app:
            return

        # Separate images from documents
        images: list[Path] = []
        documents: list[Path] = []

        for media_path in msg.media:
            path = Path(media_path).expanduser().resolve()

            if not path.exists():
                logger.warning(f"Media file not found: {media_path}")
                continue

            if _is_image_file(path):
                images.append(path)
            else:
                documents.append(path)

        # Send images
        if images:
            await self._send_images(chat_id, images, msg.content)
        elif msg.content:
            # No images but we have content - send as text
            await self._send_text(chat_id, msg.content)

        # Send documents separately (after images)
        for doc_path in documents:
            await self._send_document(chat_id, doc_path)

    async def _send_images(self, chat_id: int, images: list[Path], caption: str) -> None:
        """Send one or more images."""
        if not self._app or not images:
            return

        try:
            if len(images) == 1:
                # Single image - send as photo with caption
                await self._send_single_photo(chat_id, images[0], caption)
            else:
                # Multiple images - send as media group
                await self._send_media_group(chat_id, images, caption)

        except Exception as e:
            logger.error(f"Error sending images: {e}")
            # Fallback: try sending as documents
            for image in images:
                try:
                    await self._send_document(chat_id, image)
                except Exception as e2:
                    logger.error(f"Failed to send {image} as document: {e2}")

    async def _send_single_photo(self, chat_id: int, image_path: Path, caption: str) -> None:
        """Send a single photo with caption."""
        if not self._app:
            return

        # Prepare caption (truncate if needed)
        html_caption = ""
        if caption:
            html_caption = _truncate_caption(_markdown_to_telegram_html(caption))

        try:
            with open(image_path, "rb") as photo_file:
                await self._app.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(photo_file, filename=image_path.name),
                    caption=html_caption if html_caption else None,
                    parse_mode="HTML" if html_caption else None
                )
                logger.info(f"Sent photo: {image_path.name} to {chat_id}")

        except Exception as e:
            logger.error(f"Error sending photo {image_path}: {e}")
            # Try sending as document as fallback
            await self._send_document(chat_id, image_path)

    async def _send_media_group(self, chat_id: int, images: list[Path], caption: str) -> None:
        """Send multiple images as a media group."""
        if not self._app or not images:
            return

        from telegram import InputMediaPhoto

        try:
            media_group = []
            file_handles = []

            for i, image_path in enumerate(images[:10]):  # Telegram limit: 10 items
                file_handle = open(image_path, "rb")
                file_handles.append(file_handle)

                # Only first image gets the caption
                img_caption = None
                if i == 0 and caption:
                    img_caption = _truncate_caption(_markdown_to_telegram_html(caption))

                media_group.append(InputMediaPhoto(
                    media=InputFile(file_handle, filename=image_path.name),
                    caption=img_caption,
                    parse_mode="HTML" if img_caption else None
                ))

            await self._app.bot.send_media_group(
                chat_id=chat_id,
                media=media_group
            )
            logger.info(f"Sent media group with {len(images)} images to {chat_id}")

        except Exception as e:
            logger.error(f"Error sending media group: {e}")
            raise
        finally:
            # Close all file handles
            for fh in file_handles:
                try:
                    fh.close()
                except Exception:
                    pass

    async def _send_document(self, chat_id: int, doc_path: Path) -> None:
        """Send a file as a document."""
        if not self._app:
            return

        try:
            with open(doc_path, "rb") as doc_file:
                await self._app.bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(doc_file, filename=doc_path.name)
                )
                logger.info(f"Sent document: {doc_path.name} to {chat_id}")

        except Exception as e:
            logger.error(f"Error sending document {doc_path}: {e}")

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return

        user = update.effective_user
        await update.message.reply_text(
            f"Hi {user.first_name}! I'm Nanobot.\n\n"
            "Send me a message and I'll respond!"
        )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id

        # Use stable numeric ID, but keep username for allowlist compatibility
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id

        # Build content from text and/or media
        content_parts = []
        media_paths = []

        # Text content
        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        # Handle media files
        media_file = None
        media_type = None

        if message.photo:
            media_file = message.photo[-1]  # Largest photo
            media_type = "image"
        elif message.voice:
            media_file = message.voice
            media_type = "voice"
        elif message.audio:
            media_file = message.audio
            media_type = "audio"
        elif message.document:
            media_file = message.document
            media_type = "file"

        # Download media if present
        if media_file and self._app:
            try:
                file = await self._app.bot.get_file(media_file.file_id)
                ext = self._get_extension(media_type, getattr(media_file, 'mime_type', None))

                # Save to workspace/media/
                media_dir = Path.home() / ".nanobot" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)

                file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                await file.download_to_drive(str(file_path))

                media_paths.append(str(file_path))
                content_parts.append(f"[{media_type}: {file_path}]")
                logger.debug(f"Downloaded {media_type} to {file_path}")
            except Exception as e:
                logger.error(f"Failed to download media: {e}")
                content_parts.append(f"[{media_type}: download failed]")

        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug(f"Telegram message from {sender_id}: {content[:50]}...")

        # Forward to the message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str(chat_id),
            content=content,
            media=media_paths,
            metadata={
                "message_id": message.message_id,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "is_group": message.chat.type != "private"
            }
        )

    def _get_extension(self, media_type: str, mime_type: str | None) -> str:
        """Get file extension based on media type."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]

        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        return type_map.get(media_type, "")
