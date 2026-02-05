"""Telegram channel implementation using python-telegram-bot."""

import asyncio
import re

from loguru import logger
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TelegramConfig


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


class TelegramChannel(BaseChannel):
    """
    Telegram channel using long polling.
    
    Simple and reliable - no webhook/public IP needed.
    """
    
    name = "telegram"
    
    def __init__(self, config: TelegramConfig, bus: MessageBus, groq_api_key: str = ""):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        # Media group buffering: collect album parts before processing
        self._media_group_buffer: dict[str, list[Update]] = {}
        self._media_group_timers: dict[str, asyncio.TimerHandle] = {}
    
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
                (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE | filters.AUDIO | filters.Document.ALL)
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

        # Cancel pending media group timers
        for timer in self._media_group_timers.values():
            timer.cancel()
        self._media_group_buffer.clear()
        self._media_group_timers.clear()

        if self._app:
            logger.info("Stopping Telegram bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Telegram."""
        if not self._app:
            logger.warning("Telegram bot not running")
            return
        
        try:
            # chat_id should be the Telegram chat ID (integer)
            chat_id = int(msg.chat_id)
            # Convert markdown to Telegram HTML
            html_content = _markdown_to_telegram_html(msg.content)
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=html_content,
                parse_mode="HTML"
            )
        except ValueError:
            logger.error(f"Invalid chat_id: {msg.chat_id}")
        except Exception as e:
            # Fallback to plain text if HTML parsing fails
            logger.warning(f"HTML parse failed, falling back to plain text: {e}")
            try:
                await self._app.bot.send_message(
                    chat_id=int(msg.chat_id),
                    text=msg.content
                )
            except Exception as e2:
                logger.error(f"Error sending Telegram message: {e2}")
    
    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return
        
        user = update.effective_user
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm nanobot.\n\n"
            "Send me a message and I'll respond!"
        )
    
    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Route incoming messages: buffer media groups, process singles immediately."""
        if not update.message or not update.effective_user:
            return

        message = update.message

        if message.media_group_id:
            group_id = message.media_group_id

            if group_id not in self._media_group_buffer:
                self._media_group_buffer[group_id] = []
            self._media_group_buffer[group_id].append(update)

            # Cancel existing timer and set a new one (1s window)
            existing = self._media_group_timers.get(group_id)
            if existing:
                existing.cancel()

            loop = asyncio.get_running_loop()
            timer = loop.call_later(
                1.0,
                lambda gid=group_id: asyncio.ensure_future(self._process_media_group(gid)),
            )
            self._media_group_timers[group_id] = timer
        else:
            await self._process_single_message(update)

    async def _process_single_message(self, update: Update) -> None:
        """Process a single (non-media-group) message."""
        message = update.message
        user = update.effective_user
        chat_id = message.chat_id

        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        self._chat_ids[sender_id] = chat_id

        content_parts = []
        media_paths = []

        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        file_path, annotation = await self._download_media(message)
        if file_path:
            media_paths.append(file_path)
        if annotation:
            content_parts.append(annotation)

        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug(f"Telegram message from {sender_id}: {content[:50]}...")

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
                "is_group": message.chat.type != "private",
            }
        )

    async def _process_media_group(self, group_id: str) -> None:
        """Process a buffered media group as one logical message."""
        updates = self._media_group_buffer.pop(group_id, [])
        self._media_group_timers.pop(group_id, None)

        if not updates:
            return

        # Sort by message_id to maintain order
        updates.sort(key=lambda u: u.message.message_id)

        first = updates[0]
        user = first.effective_user
        chat_id = first.message.chat_id

        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        self._chat_ids[sender_id] = chat_id

        content_parts = []
        media_paths = []

        # Extract caption (only one message in a group typically has it)
        for u in updates:
            if u.message.caption:
                content_parts.append(u.message.caption)
                break

        # Download all media items
        for u in updates:
            file_path, annotation = await self._download_media(u.message)
            if file_path:
                media_paths.append(file_path)
            if annotation:
                content_parts.append(annotation)

        content = "\n".join(content_parts) if content_parts else "[media group]"

        logger.info(f"Processed media group {group_id}: {len(media_paths)} items")
        logger.debug(f"Telegram message from {sender_id}: {content}...")

        await self._handle_message(
            sender_id=sender_id,
            chat_id=str(chat_id),
            content=content,
            media=media_paths,
            metadata={
                "message_id": first.message.message_id,
                "media_group_id": group_id,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "is_group": first.message.chat.type != "private",
            }
        )
    
    async def _download_media(self, message) -> tuple[str | None, str | None]:
        """Download media from a message. Returns (file_path, content_annotation)."""
        media_file = None
        media_type = None

        if message.photo:
            media_file = message.photo[-1]  # Largest photo
            media_type = "image"
        elif message.video:
            media_file = message.video
            media_type = "video"
        elif message.voice:
            media_file = message.voice
            media_type = "voice"
        elif message.audio:
            media_file = message.audio
            media_type = "audio"
        elif message.document:
            media_file = message.document
            media_type = "file"

        if not media_file or not self._app:
            return None, None

        try:
            file = await self._app.bot.get_file(media_file.file_id)
            ext = self._get_extension(media_type, getattr(media_file, 'mime_type', None))

            from pathlib import Path
            media_dir = Path.home() / ".nanobot" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)

            file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
            await file.download_to_drive(str(file_path))

            # Handle voice/audio transcription
            if media_type in ("voice", "audio"):
                from nanobot.providers.transcription import GroqTranscriptionProvider
                transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
                transcription = await transcriber.transcribe(file_path)
                if transcription:
                    logger.info(f"Transcribed {media_type}: {transcription[:50]}...")
                    return str(file_path), f"[transcription: {transcription}]"
                else:
                    return str(file_path), f"[{media_type}: {file_path}]"

            logger.debug(f"Downloaded {media_type} to {file_path}")
            return str(file_path), f"[{media_type}: {file_path}]"
        except Exception as e:
            logger.error(f"Failed to download media: {e}")
            return None, f"[{media_type}: download failed]"

    def _get_extension(self, media_type: str, mime_type: str | None) -> str:
        """Get file extension based on media type."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
                "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]

        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "video": ".mp4", "file": ""}
        return type_map.get(media_type, "")
