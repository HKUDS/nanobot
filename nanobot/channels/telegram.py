"""Telegram channel implementation using python-telegram-bot."""

import asyncio
import re

from loguru import logger
from telegram import Update
from telegram.error import Conflict
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TelegramConfig


def _split_long_message(text: str, max_length: int = 4096) -> list[str]:
    """
    Split a message into chunks that fit Telegram's character limit.
    
    Tries to split at paragraph boundaries to maintain readability.
    Max length for Telegram is 4096 characters per message.
    """
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    remaining = text
    
    while len(remaining) > max_length:
        # Try to split at double newline (paragraph boundary)
        chunk = remaining[:max_length]
        split_pos = chunk.rfind('\n\n')
        
        if split_pos > max_length * 0.7:  # Found a paragraph break in the last 30%
            split_pos += 2  # Include the newlines
        else:
            # Try to split at single newline
            split_pos = chunk.rfind('\n')
            if split_pos > max_length * 0.7:
                split_pos += 1
            else:
                # Try to split at space
                split_pos = chunk.rfind(' ')
                if split_pos <= max_length * 0.7:
                    # Last resort: split at max_length
                    split_pos = max_length
                else:
                    split_pos += 1
        
        chunks.append(remaining[:split_pos].rstrip())
        remaining = remaining[split_pos:].lstrip()
    
    if remaining:
        chunks.append(remaining)
    
    return chunks


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
        self._polling_started = False
        self._last_conflict_time = 0  # Track last conflict for debouncing
    
    async def start(self) -> None:
        """Start the Telegram bot with long polling (lightweight version)."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return
        
        self._running = True
        retry_count = 0
        max_retries = 3
        consecutive_failures = 0
        max_consecutive_failures = 10  # Track consecutive failures for exponential backoff
        
        while self._running:
            try:
                # Build the application
                self._app = (
                    Application.builder()
                    .token(self.config.token)
                    .build()
                )
                
                # Add message handler
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

                # Initialize and start
                await self._app.initialize()
                await self._app.start()

                # Get bot info
                bot_info = await self._app.bot.get_me()
                logger.info(f"Telegram bot @{bot_info.username} connected")

                # Start polling and wait for it to run
                self._polling_started = True
                consecutive_failures = 0  # Reset on successful connection
                logger.info("Telegram polling active")

                await self._app.updater.start_polling(
                    allowed_updates=["message"],
                    drop_pending_updates=True
                )

                # Keep running until stopped - polling runs in background
                while self._running and self._polling_started:
                    await asyncio.sleep(1)

                    # Check if updater is still running
                    if not self._app.updater.running:
                        logger.warning("Updater stopped running")
                        break

                # If we get here, polling was stopped
                if not self._running:
                    # User requested shutdown
                    logger.info("Telegram polling stopped by user request")
                    break
                else:
                    # Unexpected stop, clean up and retry
                    self._polling_started = False
                    logger.warning("Telegram polling stopped unexpectedly, cleaning up...")

                    # Clean up the application completely
                    if self._app:
                        try:
                            await self._app.updater.stop()
                            await self._app.stop()
                            await self._app.shutdown()
                        except Exception as cleanup_error:
                            logger.debug(f"Cleanup error (expected): {cleanup_error}")
                        self._app = None

                    # Wait longer to ensure old instance is fully released
                    consecutive_failures += 1
                    wait_time = min(2 ** consecutive_failures, 60)
                    logger.info(f"Will retry in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                
            except Conflict as e:
                self._polling_started = False
                retry_count += 1
                consecutive_failures += 1

                logger.error(
                    f"Telegram polling conflict (attempt {retry_count}/{max_retries}): {e}"
                )
                logger.warning("Another bot instance may be running. Cleaning up completely...")

                # Clean up on conflict - must stop updater first
                if self._app:
                    try:
                        await self._app.updater.stop()
                        await self._app.stop()
                        await self._app.shutdown()
                    except Exception as cleanup_error:
                        logger.debug(f"Cleanup error (expected): {cleanup_error}")
                    self._app = None

                # Retry with increasing delay
                if self._running:
                    # Use exponential backoff, but cap at 5 minutes
                    wait_time = min(2 ** consecutive_failures, 300)

                    if retry_count >= max_retries:
                        logger.warning(
                            f"Max retries reached. Entering keep-alive mode with {wait_time}s backoff. "
                            "Will continue attempting to reconnect..."
                        )
                        # Reset retry_count to allow continuous retries
                        retry_count = 0

                    logger.info(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    
            except Exception as e:
                self._polling_started = False
                consecutive_failures += 1
                logger.error(f"Telegram error: {type(e).__name__}: {e}")

                # Clean up completely
                if self._app:
                    try:
                        await self._app.updater.stop()
                        await self._app.stop()
                        await self._app.shutdown()
                    except Exception as cleanup_error:
                        logger.debug(f"Cleanup error (expected): {cleanup_error}")
                    self._app = None

                # Enter keep-alive mode with exponential backoff
                if self._running:
                    wait_time = min(2 ** consecutive_failures, 300)  # Cap at 5 minutes
                    logger.warning(
                        f"Entering keep-alive mode with {wait_time}s backoff. "
                        "Will continue attempting to reconnect..."
                    )
                    await asyncio.sleep(wait_time)
    async def stop(self) -> None:
        """Stop the Telegram bot."""
        logger.info("Stopping Telegram bot...")
        self._running = False
        self._polling_started = False
        
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                logger.debug(f"Cleanup error: {e}")
            finally:
                self._app = None
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Telegram, splitting if necessary."""
        if not self._app or not self._polling_started:
            logger.warning("Telegram bot not ready to send messages")
            return
        
        try:
            chat_id = int(msg.chat_id)
            html_content = _markdown_to_telegram_html(msg.content)
            
            # Split message if it exceeds Telegram's 4096 character limit
            message_chunks = _split_long_message(html_content, max_length=4096)
            
            if len(message_chunks) > 1:
                logger.info(f"Message too long ({len(html_content)} chars), splitting into {len(message_chunks)} parts")
            
            for i, chunk in enumerate(message_chunks, 1):
                try:
                    await self._app.bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        parse_mode="HTML"
                    )
                except Exception as chunk_error:
                    # If HTML formatting fails, try plain text
                    if "parse mode" in str(chunk_error).lower():
                        try:
                            await self._app.bot.send_message(
                                chat_id=chat_id,
                                text=chunk
                            )
                        except Exception as plain_error:
                            logger.error(f"Failed to send message chunk {i}/{len(message_chunks)}: {plain_error}")
                            raise
                    else:
                        raise
                        
        except ValueError:
            logger.error(f"Invalid chat_id: {msg.chat_id}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
    
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
                from pathlib import Path
                media_dir = Path.home() / ".nanobot" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)
                
                file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                await file.download_to_drive(str(file_path))
                
                media_paths.append(str(file_path))
                
                # Handle voice transcription
                if media_type == "voice" or media_type == "audio":
                    from nanobot.providers.transcription import GroqTranscriptionProvider
                    transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
                    transcription = await transcriber.transcribe(file_path)
                    if transcription:
                        logger.info(f"Transcribed {media_type}: {transcription[:50]}...")
                        content_parts.append(f"[transcription: {transcription}]")
                    else:
                        content_parts.append(f"[{media_type}: {file_path}]")
                else:
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
