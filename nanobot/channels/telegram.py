"""Telegram channel implementation using python-telegram-bot."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from telegram import BotCommand, InputMediaPhoto, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TelegramConfig

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


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
    
    # Commands registered with Telegram's command menu
    BOT_COMMANDS = [
        BotCommand("start", "Start the bot"),
        BotCommand("reset", "Reset conversation history"),
        BotCommand("help", "Show available commands"),
    ]
    
    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        groq_api_key: str = "",
        session_manager: SessionManager | None = None,
    ):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self.session_manager = session_manager
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        self._typing_tasks: dict[str, asyncio.Task] = {}  # chat_id -> typing loop task
    
    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return
        
        self._running = True
        
        # Build the application
        builder = Application.builder().token(self.config.token)
        if self.config.proxy:
            builder = builder.proxy(self.config.proxy).get_updates_proxy(self.config.proxy)
        self._app = builder.build()
        
        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("reset", self._on_reset))
        self._app.add_handler(CommandHandler("help", self._on_help))
        
        # Add message handler for text, photos, voice, documents
        self._app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL) 
                & ~filters.COMMAND, 
                self._on_message
            )
        )
        
        logger.info("Starting Telegram bot (polling mode)...")
        
        # Initialize and start polling
        await self._app.initialize()
        await self._app.start()
        
        # Get bot info and register command menu
        bot_info = await self._app.bot.get_me()
        logger.info(f"Telegram bot @{bot_info.username} connected")
        
        try:
            await self._app.bot.set_my_commands(self.BOT_COMMANDS)
            logger.debug("Telegram bot commands registered")
        except Exception as e:
            logger.warning(f"Failed to register bot commands: {e}")
        
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
        
        # Cancel all typing indicators
        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)
        
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
        
        # Stop typing indicator for this chat
        self._stop_typing(msg.chat_id)
        
        try:
            # chat_id should be the Telegram chat ID (integer)
            chat_id = int(msg.chat_id)
            reply_to_message_id = self._resolve_reply_to_message_id(msg)
            logger.debug(
                "Sending Telegram message to chat_id={} reply_to_message_id={}",
                chat_id,
                reply_to_message_id,
            )

            # Check for media (images)
            valid_media = [p for p in (msg.media or []) if Path(p).is_file()]

            if valid_media:
                await self._send_with_media(chat_id, msg.content, valid_media, reply_to_message_id)
            else:
                await self._send_text(chat_id, msg.content, reply_to_message_id)

        except ValueError:
            logger.error(f"Invalid chat_id: {msg.chat_id}")
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")

    async def _send_text(self, chat_id: int, content: str, reply_to_message_id: int | None) -> None:
        """Send a text-only message."""
        html_content = _markdown_to_telegram_html(content)
        send_kwargs: dict = {
            "chat_id": chat_id,
            "text": html_content,
            "parse_mode": "HTML",
        }
        if reply_to_message_id is not None:
            send_kwargs["reply_to_message_id"] = reply_to_message_id
            send_kwargs["allow_sending_without_reply"] = True
        try:
            await self._app.bot.send_message(**send_kwargs)
        except Exception:
            # Fallback to plain text if HTML parsing fails
            logger.warning("HTML parse failed, falling back to plain text")
            fallback_kwargs: dict = {"chat_id": chat_id, "text": content}
            if reply_to_message_id is not None:
                fallback_kwargs["reply_to_message_id"] = reply_to_message_id
                fallback_kwargs["allow_sending_without_reply"] = True
            await self._app.bot.send_message(**fallback_kwargs)

    async def _send_with_media(self, chat_id: int, content: str, media_paths: list[str], reply_to_message_id: int | None) -> None:
        """Send message with photo(s)."""
        html_caption = _markdown_to_telegram_html(content) if content else None
        reply_kwargs: dict = {}
        if reply_to_message_id is not None:
            reply_kwargs["reply_to_message_id"] = reply_to_message_id
            reply_kwargs["allow_sending_without_reply"] = True

        if len(media_paths) == 1:
            # Single photo
            with open(media_paths[0], "rb") as f:
                await self._app.bot.send_photo(
                    chat_id=chat_id,
                    photo=f,
                    caption=html_caption,
                    parse_mode="HTML" if html_caption else None,
                    **reply_kwargs,
                )
        else:
            # Multiple photos as media group
            media_group = []
            for i, path in enumerate(media_paths):
                media_group.append(
                    InputMediaPhoto(
                        media=open(path, "rb"),
                        caption=html_caption if i == 0 else None,
                        parse_mode="HTML" if (i == 0 and html_caption) else None,
                    )
                )
            await self._app.bot.send_media_group(
                chat_id=chat_id,
                media=media_group,
                **reply_kwargs,
            )
        logger.info(f"Sent {len(media_paths)} photo(s) to chat_id={chat_id}")

    @staticmethod
    def _resolve_reply_to_message_id(msg: OutboundMessage) -> int | None:
        """
        Resolve Telegram message ID for quote reply.
        
        Only use explicit OutboundMessage.reply_to to avoid automatic quote replies.
        """
        if msg.reply_to is None:
            return None
        try:
            resolved = int(msg.reply_to)
            logger.debug("Resolved explicit Telegram reply target message_id={}", resolved)
            return resolved
        except (TypeError, ValueError):
            logger.debug("Invalid explicit Telegram reply target: {}", msg.reply_to)
            return None
    
    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return
        
        user = update.effective_user
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm nanobot.\n\n"
            "Send me a message and I'll respond!\n"
            "Type /help to see available commands."
        )
    
    async def _on_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /reset command — clear conversation history."""
        if not update.message or not update.effective_user:
            return
        
        chat_id = str(update.message.chat_id)
        session_key = f"{self.name}:{chat_id}"
        
        if self.session_manager is None:
            logger.warning("/reset called but session_manager is not available")
            await update.message.reply_text("⚠️ Session management is not available.")
            return
        
        session = self.session_manager.get_or_create(session_key)
        msg_count = len(session.messages)
        session.clear()
        self.session_manager.save(session)
        
        logger.info(f"Session reset for {session_key} (cleared {msg_count} messages)")
        await update.message.reply_text("🔄 Conversation history cleared. Let's start fresh!")
    
    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command — show available commands."""
        if not update.message:
            return
        
        help_text = (
            "🐈 <b>nanobot commands</b>\n\n"
            "/start — Start the bot\n"
            "/reset — Reset conversation history\n"
            "/help — Show this help message\n\n"
            "Just send me a text message to chat!"
        )
        await update.message.reply_text(help_text, parse_mode="HTML")
    
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
        is_group = message.chat.type != "private"
        sender_context = self._build_sender_context(message, user)
        if sender_context:
            content_parts.append(sender_context)
        reply_meta = self._extract_reply_metadata(message)
        reply_context = self._build_reply_context(reply_meta)
        if reply_context:
            content_parts.append(reply_context)
            logger.debug(
                "Telegram inbound reply detected: source={} from_user_id={} reply_to_message_id={} reply_to_user_id={}",
                reply_meta.get("reply_source"),
                user.id,
                reply_meta.get("reply_to_message_id"),
                reply_meta.get("reply_to_user_id"),
            )
        
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
        
        str_chat_id = str(chat_id)
        
        # Start typing indicator before processing
        self._start_typing(str_chat_id)
        
        # Forward to the message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
            media=media_paths,
            metadata={
                "message_id": message.message_id,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "sender_display": self._resolve_sender_display(user),
                "chat_title": getattr(message.chat, "title", None),
                "is_group": is_group,
                **reply_meta,
            }
        )
    
    def _start_typing(self, chat_id: str) -> None:
        """Start sending 'typing...' indicator for a chat."""
        # Cancel any existing typing task for this chat
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))
    
    def _stop_typing(self, chat_id: str) -> None:
        """Stop the typing indicator for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
    
    async def _typing_loop(self, chat_id: str) -> None:
        """Repeatedly send 'typing' action until cancelled."""
        try:
            while self._app:
                await self._app.bot.send_chat_action(chat_id=int(chat_id), action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Typing indicator stopped for {chat_id}: {e}")
    
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

    @staticmethod
    def _extract_reply_metadata(message) -> dict[str, object]:
        """Extract reply target metadata from Telegram message."""
        replied = message.reply_to_message
        quote = getattr(message, "quote", None)

        if replied:
            replied_user = getattr(replied, "from_user", None)
            replied_text = getattr(replied, "text", None) or getattr(replied, "caption", None)
            if isinstance(replied_text, str):
                replied_text = " ".join(replied_text.split())[:200]
            else:
                replied_text = None
            if not replied_text and quote and isinstance(getattr(quote, "text", None), str):
                replied_text = " ".join(quote.text.split())[:200]

            return {
                "is_reply": True,
                "reply_source": "reply_to_message",
                "reply_to_message_id": getattr(replied, "message_id", None),
                "reply_to_user_id": getattr(replied_user, "id", None),
                "reply_to_username": getattr(replied_user, "username", None),
                "reply_to_first_name": getattr(replied_user, "first_name", None),
                "reply_to_text": replied_text,
            }

        external = getattr(message, "external_reply", None)
        if external:
            origin = getattr(external, "origin", None)
            user = getattr(origin, "sender_user", None)
            sender_chat = getattr(origin, "sender_chat", None) or getattr(origin, "chat", None)
            replied_text = None
            if quote and isinstance(getattr(quote, "text", None), str):
                replied_text = " ".join(quote.text.split())[:200]
            return {
                "is_reply": True,
                "reply_source": "external_reply",
                "reply_to_message_id": getattr(external, "message_id", None),
                "reply_to_user_id": getattr(user, "id", None),
                "reply_to_username": getattr(user, "username", None),
                "reply_to_first_name": getattr(user, "first_name", None),
                "reply_to_chat_title": getattr(sender_chat, "title", None),
                "reply_to_text": replied_text,
            }

        if quote and isinstance(getattr(quote, "text", None), str):
            return {
                "is_reply": True,
                "reply_source": "quote_only",
                "reply_to_text": " ".join(quote.text.split())[:200],
            }

        return {}

    @staticmethod
    def _build_reply_context(reply_meta: dict[str, object]) -> str:
        """Build a short text prefix so the agent can see who is being replied to."""
        if not reply_meta:
            return ""

        target_name = (
            reply_meta.get("reply_to_username")
            or reply_meta.get("reply_to_first_name")
            or reply_meta.get("reply_to_chat_title")
            or reply_meta.get("reply_to_user_id")
            or "unknown"
        )
        target_text = reply_meta.get("reply_to_text")
        if target_text:
            return f"[reply_to: {target_name}, text: {target_text}]"
        return f"[reply_to: {target_name}]"

    @staticmethod
    def _resolve_sender_display(user) -> str:
        """Resolve stable display name for current sender."""
        if getattr(user, "username", None):
            return f"@{user.username}"
        if getattr(user, "full_name", None):
            return user.full_name
        if getattr(user, "first_name", None):
            return user.first_name
        return str(getattr(user, "id", "unknown"))

    @classmethod
    def _build_sender_context(cls, message, user) -> str:
        """
        Build sender prefix for inbound messages.
        
        Only prepend in group chats to help the agent identify who is speaking.
        """
        if message.chat.type == "private":
            return ""
        sender = cls._resolve_sender_display(user)
        chat_title = getattr(message.chat, "title", None)
        if chat_title:
            return f"[from: {sender}, group: {chat_title}]"
        return f"[from: {sender}]"
