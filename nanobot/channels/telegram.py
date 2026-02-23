"""Telegram channel implementation using python-telegram-bot."""

from __future__ import annotations

import asyncio
import re

from loguru import logger
from telegram import BotCommand, Update, ReplyParameters
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

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


def _split_message(content: str, max_len: int = 4000) -> list[str]:
    """Split content into chunks within max_len, preferring line breaks."""
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        pos = cut.rfind('\n')
        if pos == -1:
            pos = cut.rfind(' ')
        if pos == -1:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


class TelegramChannel(BaseChannel):
    """
    Telegram channel using long polling.
    
    Simple and reliable - no webhook/public IP needed.
    """
    
    name = "telegram"
    
    # Commands registered with Telegram's command menu
    BOT_COMMANDS = [
        BotCommand("start", "Start the bot"),
        BotCommand("new", "Start a new conversation"),
        BotCommand("help", "Show available commands"),
    ]
    
    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        groq_api_key: str = "",
    ):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        self._typing_tasks: dict[str, asyncio.Task] = {}  # chat_id -> typing loop task
        self._bot_username: str = ""
        self._bot_user_id: int | None = None
        self._group_history: dict[str, list[str]] = {}  # chat_id -> buffered group lines
    
    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return
        
        self._running = True
        
        # Build the application with larger connection pool to avoid pool-timeout on long runs
        req = HTTPXRequest(connection_pool_size=16, pool_timeout=5.0, connect_timeout=30.0, read_timeout=30.0)
        builder = Application.builder().token(self.config.token).request(req).get_updates_request(req)
        if self.config.proxy:
            builder = builder.proxy(self.config.proxy).get_updates_proxy(self.config.proxy)
        self._app = builder.build()
        self._app.add_error_handler(self._on_error)
        
        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("new", self._forward_command))
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
        self._bot_username = bot_info.username or ""
        self._bot_user_id = bot_info.id
        logger.info("Telegram bot @{} connected", bot_info.username)
        
        try:
            await self._app.bot.set_my_commands(self.BOT_COMMANDS)
            logger.debug("Telegram bot commands registered")
        except Exception as e:
            logger.warning("Failed to register bot commands: {}", e)
        
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
    
    @staticmethod
    def _get_media_type(path: str) -> str:
        """Guess media type from file extension."""
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in ("jpg", "jpeg", "png", "gif", "webp"):
            return "photo"
        if ext == "ogg":
            return "voice"
        if ext in ("mp3", "m4a", "wav", "aac"):
            return "audio"
        return "document"

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Telegram."""
        if not self._app:
            logger.warning("Telegram bot not running")
            return

        self._stop_typing(msg.chat_id)

        try:
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error("Invalid chat_id: {}", msg.chat_id)
            return

        reply_params = None
        if self.config.reply_to_message:
            reply_to_message_id = msg.metadata.get("message_id")
            if reply_to_message_id:
                reply_params = ReplyParameters(
                    message_id=reply_to_message_id,
                    allow_sending_without_reply=True
                )

        # Send media files
        for media_path in (msg.media or []):
            try:
                media_type = self._get_media_type(media_path)
                sender = {
                    "photo": self._app.bot.send_photo,
                    "voice": self._app.bot.send_voice,
                    "audio": self._app.bot.send_audio,
                }.get(media_type, self._app.bot.send_document)
                param = "photo" if media_type == "photo" else media_type if media_type in ("voice", "audio") else "document"
                with open(media_path, 'rb') as f:
                    await sender(
                        chat_id=chat_id, 
                        **{param: f},
                        reply_parameters=reply_params
                    )
            except Exception as e:
                filename = media_path.rsplit("/", 1)[-1]
                logger.error("Failed to send media {}: {}", media_path, e)
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=f"[Failed to send: {filename}]",
                    reply_parameters=reply_params
                )

        # Send text content
        if msg.content and msg.content != "[empty message]":
            for chunk in _split_message(msg.content):
                try:
                    html = _markdown_to_telegram_html(chunk)
                    await self._app.bot.send_message(
                        chat_id=chat_id, 
                        text=html, 
                        parse_mode="HTML",
                        reply_parameters=reply_params
                    )
                except Exception as e:
                    logger.warning("HTML parse failed, falling back to plain text: {}", e)
                    try:
                        await self._app.bot.send_message(
                            chat_id=chat_id, 
                            text=chunk,
                            reply_parameters=reply_params
                        )
                    except Exception as e2:
                        logger.error("Error sending Telegram message: {}", e2)
    
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

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command, bypassing ACL so all users can access it."""
        if not update.message:
            return
        await update.message.reply_text(
            "🐈 nanobot commands:\n"
            "/new — Start a new conversation\n"
            "/help — Show available commands"
        )

    @staticmethod
    def _sender_id(user) -> str:
        """Build sender_id with username for allowlist matching."""
        sid = str(user.id)
        return f"{sid}|{user.username}" if user.username else sid

    def _group_policy(self) -> str:
        """Resolve group handling policy."""
        policy = (self.config.group_policy or "open").strip().lower()
        if policy in {"open", "mention"}:
            return policy
        logger.warning("Invalid Telegram group_policy={}, falling back to open", self.config.group_policy)
        return "open"

    @staticmethod
    def _is_group_chat(message) -> bool:
        return getattr(message.chat, "type", "") != "private"

    def _is_reply_to_bot(self, message) -> bool:
        if not self.config.mention_by_reply:
            return False
        if self._bot_user_id is None:
            return False
        reply = getattr(message, "reply_to_message", None)
        from_user = getattr(reply, "from_user", None) if reply else None
        return bool(from_user and int(getattr(from_user, "id", 0)) == int(self._bot_user_id))

    def _is_mentioned(self, message, text: str) -> bool:
        """Check whether the bot is explicitly invoked in a group message."""
        username = self._bot_username.strip().lstrip("@")
        if username:
            pattern = rf"(?<!\w)@{re.escape(username)}(?!\w)"
            if re.search(pattern, text or "", flags=re.IGNORECASE):
                return True
        return self._is_reply_to_bot(message)

    def _strip_bot_mention(self, text: str) -> str:
        """Remove @botname from text so the model sees only user intent."""
        username = self._bot_username.strip().lstrip("@")
        if not text or not username:
            return text
        pattern = rf"(?<!\w)@{re.escape(username)}(?!\w)"
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _sender_label(user) -> str:
        first_name = (getattr(user, "first_name", "") or "").strip()
        last_name = (getattr(user, "last_name", "") or "").strip()
        username = (getattr(user, "username", "") or "").strip()
        user_id = str(getattr(user, "id", "unknown"))
        name = " ".join([p for p in (first_name, last_name) if p]).strip()
        if not name:
            name = f"@{username}" if username else f"user:{user_id}"
        if username:
            return f"{name} (@{username}, id:{user_id})"
        return f"{name} (id:{user_id})"

    def _format_group_line(self, user, content: str) -> str:
        text = (content or "").strip() or "[empty message]"
        return f"{self._sender_label(user)}: {text}"

    @staticmethod
    def _group_preview(message, raw_text: str) -> str:
        if raw_text.strip():
            return raw_text.strip()
        if message.photo:
            return "[sent a photo]"
        if message.voice:
            return "[sent a voice message]"
        if message.audio:
            return "[sent an audio message]"
        if message.document:
            return "[sent a file]"
        return "[sent a message]"

    def _append_group_history(self, chat_id: str, line: str) -> None:
        limit = max(0, int(self.config.group_history_on_mention))
        if limit <= 0:
            return
        history = self._group_history.setdefault(chat_id, [])
        history.append(line)
        if len(history) > limit:
            del history[:-limit]

    def _pop_group_history(self, chat_id: str) -> list[str]:
        return self._group_history.pop(chat_id, [])

    def _build_group_content(self, user, content: str, history_lines: list[str]) -> str:
        current = self._format_group_line(user, content)
        if not history_lines:
            return current
        history = "\n".join(history_lines)
        return f"Recent group messages before mention:\n{history}\n\nCurrent message:\n{current}"

    async def _forward_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Forward slash commands to the bus for unified handling in AgentLoop."""
        if not update.message or not update.effective_user:
            return
        await self._handle_message(
            sender_id=self._sender_id(update.effective_user),
            chat_id=str(update.message.chat_id),
            content=update.message.text,
        )
    
    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return
        
        message = update.message
        user = update.effective_user
        if self._bot_user_id is not None and int(user.id) == int(self._bot_user_id):
            return

        chat_id = message.chat_id
        str_chat_id = str(chat_id)
        is_group = self._is_group_chat(message)
        group_policy = self._group_policy()

        sender_id = self._sender_id(user)
        
        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id

        raw_text_parts: list[str] = []
        if message.text:
            raw_text_parts.append(message.text)
        if message.caption:
            raw_text_parts.append(message.caption)
        raw_text = "\n".join(raw_text_parts).strip()

        was_mentioned = is_group and self._is_mentioned(message, raw_text)
        history_lines: list[str] = []
        if is_group and group_policy == "mention":
            if not was_mentioned:
                preview = self._group_preview(message, raw_text)
                self._append_group_history(str_chat_id, self._format_group_line(user, preview))
                logger.debug(
                    "Skip Telegram group message (not mentioned) chat_id={} sender={}",
                    str_chat_id,
                    sender_id,
                )
                return
            history_lines = self._pop_group_history(str_chat_id)
        
        # Build content from text and/or media
        content_parts: list[str] = []
        media_paths: list[str] = []

        text_content = raw_text
        if is_group and was_mentioned:
            text_content = self._strip_bot_mention(text_content)
        if text_content:
            content_parts.append(text_content)
        
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
                        logger.info("Transcribed {}: {}...", media_type, transcription[:50])
                        content_parts.append(f"[transcription: {transcription}]")
                    else:
                        content_parts.append(f"[{media_type}: {file_path}]")
                else:
                    content_parts.append(f"[{media_type}: {file_path}]")
                    
                logger.debug("Downloaded {} to {}", media_type, file_path)
            except Exception as e:
                logger.error("Failed to download media: {}", e)
                content_parts.append(f"[{media_type}: download failed]")
        
        content = "\n".join(content_parts) if content_parts else "[empty message]"
        if is_group:
            content = self._build_group_content(user, content, history_lines)
        
        logger.debug("Telegram message from {}: {}...", sender_id, content[:50])

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
                "is_group": is_group,
                "chat_type": message.chat.type,
                "was_mentioned": was_mentioned,
                "group_policy": group_policy,
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
            logger.debug("Typing indicator stopped for {}: {}", chat_id, e)
    
    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log polling / handler errors instead of silently swallowing them."""
        logger.error("Telegram error: {}", context.error)

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
