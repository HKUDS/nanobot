"""Telegram channel implementation using python-telegram-bot."""

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any

from loguru import logger
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TelegramConfig
from nanobot.utils.rate_limit import (
    transcription_rate_limiter,
    tts_rate_limiter,
    video_rate_limiter,
)

# Maximum file sizes for downloads (in bytes)
MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024  # 100MB
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB
MAX_AUDIO_SIZE = 50 * 1024 * 1024  # 50MB


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

    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        groq_api_key: str = "",
        tts_provider: Any = None,
        max_video_frames: int = 5,
        workspace: Path | None = None,
        cleanup_registry: Any = None,
    ):
        """
        Initialize the Telegram channel.

        Args:
            config: Telegram configuration.
            bus: Message bus for communication.
            groq_api_key: Groq API key for transcription.
            tts_provider: Optional TTS provider for voice output.
            max_video_frames: Maximum frames to extract from videos.
            workspace: Workspace path for video processing.
            cleanup_registry: Optional media cleanup registry.
        """
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self.tts_provider = tts_provider
        self.max_video_frames = max_video_frames
        self._workspace = workspace or Path.home() / ".nanobot" / "workspace"
        self._cleanup_registry = cleanup_registry
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        self._video_processor = None  # Lazy initialization
        self._tts_rate_limiter = tts_rate_limiter()
        self._transcription_rate_limiter = transcription_rate_limiter()
        self._video_rate_limiter = video_rate_limiter()

    def _check_file_size_limit(self, media_type: str, file_size: int) -> tuple[bool, str]:
        """
        Check if file size is within allowed limits.

        Args:
            media_type: Type of media (image, video, voice, audio, file).
            file_size: File size in bytes.

        Returns:
            Tuple of (is_allowed, error_message).
        """
        limits = {
            "image": MAX_IMAGE_SIZE,
            "video": MAX_VIDEO_SIZE,
            "voice": MAX_AUDIO_SIZE,
            "audio": MAX_AUDIO_SIZE,
            "file": MAX_DOWNLOAD_SIZE,
        }

        max_size = limits.get(media_type, MAX_DOWNLOAD_SIZE)

        if file_size > max_size:
            return False, f"{media_type.capitalize()} too large ({file_size / 1024 / 1024:.1f}MB > {max_size / 1024 / 1024:.0f}MB)"

        return True, ""

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
        """Send a message through Telegram."""
        if not self._app:
            logger.warning("Telegram bot not running")
            return

        try:
            chat_id = int(msg.chat_id)

            # Check if voice output is requested (from session metadata)
            if msg.metadata.get("voice"):
                if self.tts_provider:
                    user_id = msg.metadata.get("user_id", str(chat_id))
                    await self._send_as_voice(chat_id, msg.content, user_id=user_id)
                    return
                else:
                    logger.warning("Voice requested but TTS provider not configured")

            # Regular text message - convert markdown to HTML
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

    async def _send_as_voice(self, chat_id: int, text: str, user_id: str | None = None) -> None:
        """
        Send text as a voice message.

        Args:
            chat_id: Telegram chat ID.
            text: Text to synthesize and send.
            user_id: User ID for rate limiting.
        """
        if not self.tts_provider:
            logger.warning("TTS provider not available")
            return

        # Check rate limit
        user_key = user_id or str(chat_id)
        is_allowed, error_msg = self._tts_rate_limiter.is_allowed(user_key)
        if not is_allowed:
            logger.warning(f"TTS rate limit exceeded for {user_key}: {error_msg}")
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {error_msg} Voice output disabled temporarily."
            )
            return

        # Generate audio file path with UUID for safety
        media_dir = Path.home() / ".nanobot" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        # Use temporary file, then rename on success (atomic write pattern)
        temp_path = media_dir / f"voice_temp_{uuid.uuid4().hex}.mp3"
        final_path = media_dir / f"voice_{chat_id}_{uuid.uuid4().hex[:8]}.mp3"

        # Synthesize speech to temp file
        success, warning = await self.tts_provider.synthesize(text, temp_path)
        if not success:
            logger.warning("TTS synthesis failed, falling back to text")
            await self._app.bot.send_message(chat_id=chat_id, text=text)
            return

        # Warn user if text was truncated
        if warning:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {warning}"
            )

        # Atomic rename
        temp_path.rename(final_path)

        # Register for cleanup
        if self._cleanup_registry:
            self._cleanup_registry.register(final_path)

        # Send voice message
        try:
            with open(final_path, "rb") as f:
                await self._app.bot.send_voice(chat_id=chat_id, voice=f)
            logger.debug(f"Voice message sent to {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send voice message: {e}")
            # Fallback to text
            await self._app.bot.send_message(chat_id=chat_id, text=text)

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

        # Download media if present
        if media_file and self._app:
            try:
                # Check file size before downloading
                file_size = getattr(media_file, 'file_size', None)
                if file_size:
                    is_allowed, error_msg = self._check_file_size_limit(media_type, file_size)
                    if not is_allowed:
                        logger.warning(f"File size check failed: {error_msg}")
                        content_parts.append(f"[{media_type}: {error_msg}]")
                        # Skip to next message part
                        raise ValueError(error_msg)

                file = await self._app.bot.get_file(media_file.file_id)
                ext = self._get_extension(media_type, getattr(media_file, 'mime_type', None))

                # Save to workspace/media/
                from pathlib import Path
                media_dir = Path.home() / ".nanobot" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)

                file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                await file.download_to_drive(str(file_path))

                # Register for cleanup
                if self._cleanup_registry:
                    self._cleanup_registry.register(file_path)

                # Verify downloaded file size (double-check against limits)
                actual_size = file_path.stat().st_size
                is_allowed, error_msg = self._check_file_size_limit(media_type, actual_size)
                if not is_allowed:
                    file_path.unlink()  # Delete oversized file
                    raise ValueError(error_msg)

                # Handle video: extract frames and audio
                if media_type == "video":
                    content_parts.append(f"[video: {file_path}]")

                    # Check video rate limit
                    is_allowed, error_msg = self._video_rate_limiter.is_allowed(sender_id)
                    if not is_allowed:
                        logger.warning(f"Video rate limit exceeded: {error_msg}")
                        content_parts.append(f"[video processing: {error_msg}]")
                        # Skip processing but add file path to media
                        media_paths.append(str(file_path))
                        # Continue to next media item
                        continue

                    # Check ffmpeg availability
                    if not VideoProcessor.is_ffmpeg_available():
                        msg = (
                            "⚠️ Video processing requires ffmpeg. "
                            "Install with: apt install ffmpeg or brew install ffmpeg"
                        )
                        logger.warning(msg)
                        content_parts.append(f"[video processing: {msg}]")
                        media_paths.append(str(file_path))
                    else:
                        # Extract frames for vision analysis
                        if self._video_processor is None:
                            from nanobot.agent.video import VideoProcessor
                            self._video_processor = VideoProcessor(
                                self._workspace, max_frames=self.max_video_frames
                            )

                        # Extract key frames
                        frames = await self._video_processor.extract_key_frames(
                            file_path, max_frames=self.max_video_frames
                        )
                        if frames:
                            media_paths.extend(frames)
                            logger.info(f"Extracted {len(frames)} frames from video")
                        else:
                            content_parts.append("[video: frame extraction failed]")

                        # Extract audio for transcription
                        audio_path = await self._video_processor.extract_audio(file_path)
                        if audio_path:
                            # Check transcription rate limit
                            is_allowed, error_msg = self._transcription_rate_limiter.is_allowed(sender_id)
                            if not is_allowed:
                                logger.warning(f"Transcription rate limit exceeded: {error_msg}")
                                content_parts.append(f"[video audio: {error_msg}]")
                            else:
                                from nanobot.providers.transcription import (
                                    GroqTranscriptionProvider,
                                )
                                transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
                                transcription = await transcriber.transcribe(audio_path)
                                if transcription:
                                    content_parts.append(f"[video audio: {transcription}]")
                                    logger.info(f"Transcribed video audio: {transcription[:50]}...")

                        # Clean up extracted frames after processing
                        if frames:
                            self._video_processor.cleanup_frames(file_path)

                # Handle voice/audio transcription
                elif media_type == "voice" or media_type == "audio":
                    media_paths.append(str(file_path))

                    # Check transcription rate limit
                    is_allowed, error_msg = self._transcription_rate_limiter.is_allowed(sender_id)
                    if not is_allowed:
                        logger.warning(f"Transcription rate limit exceeded: {error_msg}")
                        content_parts.append(f"[{media_type}: {error_msg}]")
                    else:
                        from nanobot.providers.transcription import GroqTranscriptionProvider
                        transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
                        transcription = await transcriber.transcribe(file_path)
                        if transcription:
                            logger.info(f"Transcribed {media_type}: {transcription[:50]}...")
                            content_parts.append(f"[transcription: {transcription}]")
                        else:
                            content_parts.append(f"[{media_type}: {file_path}]")
                else:
                    # Images and other files
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
