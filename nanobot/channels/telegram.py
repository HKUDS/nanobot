"""Telegram channel implementation using python-telegram-bot."""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any
from loguru import logger
from telegram import BotCommand, InputMediaPhoto, ReactionTypeEmoji, Update
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
    _LOG_PREVIEW_LIMIT = 320
    
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
        self._recent_messages: dict[str, OrderedDict[int, dict[str, Any]]] = {}
        self._recent_message_limit = 500
    
    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return
        
        self._running = True
        
        # Build the application with larger connection pool to avoid pool-timeout on long runs.
        # If proxy is configured, it must be set on HTTPXRequest directly (PTB forbids
        # combining builder.proxy(...) with a custom request instance).
        request_kwargs: dict[str, Any] = {
            "connection_pool_size": 16,
            "pool_timeout": 5.0,
            "connect_timeout": 30.0,
            "read_timeout": 30.0,
        }
        if self.config.proxy:
            request_kwargs["proxy"] = self.config.proxy
        req = HTTPXRequest(**request_kwargs)
        builder = Application.builder().token(self.config.token).request(req).get_updates_request(req)
        self._app = builder.build()
        self._app.add_error_handler(self._on_error)
        
        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("new", self._forward_command))
        self._app.add_handler(CommandHandler("help", self._on_help))
        
        # Add message handler for text, photos, voice, audio, documents, stickers
        self._app.add_handler(
            MessageHandler(
                (
                    filters.TEXT
                    | filters.PHOTO
                    | filters.VOICE
                    | filters.AUDIO
                    | filters.Document.ALL
                    | filters.Sticker.ALL
                )
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

        if self._is_progress_notice(msg):
            logger.debug("Drop Telegram progress notice for chat_id={}", msg.chat_id)
            return

        self._stop_typing(msg.chat_id)

        # Silent message: only stop typing, don't send anything
        if msg.silent:
            logger.debug("Silent outbound for chat_id={}, typing stopped", msg.chat_id)
            return

        try:
            chat_id = int(msg.chat_id)
            reply_to_message_id = self._resolve_reply_to_message_id(msg)
            if reply_to_message_id is None and self.config.reply_to_message:
                meta_message_id = (msg.metadata or {}).get("message_id")
                if meta_message_id is not None:
                    try:
                        reply_to_message_id = int(meta_message_id)
                    except (TypeError, ValueError):
                        logger.debug("Invalid metadata Telegram message_id: {}", meta_message_id)
            logger.debug(
                "Sending Telegram message to chat_id={} reply_to_message_id={}",
                chat_id,
                reply_to_message_id,
            )

            # Handle reaction
            reaction_emoji = msg.reaction or (msg.metadata.get("reaction") if msg.metadata else None)
            reaction_msg_id = (
                msg.reaction_message_id
                or (msg.metadata.get("reaction_message_id") if msg.metadata else None)
            )
            if reaction_emoji and reaction_msg_id:
                try:
                    await self._app.bot.set_message_reaction(
                        chat_id=chat_id,
                        message_id=int(reaction_msg_id),
                        reaction=[ReactionTypeEmoji(emoji=reaction_emoji)],
                    )
                    logger.debug("Set reaction {} on message {}", reaction_emoji, reaction_msg_id)
                except Exception as e:
                    logger.error("Error setting reaction: {}", e)
                # If reaction-only (no text/media/sticker), return early
                if not (msg.content or "").strip() and not msg.media and not (msg.sticker_id or "").strip():
                    return

            sticker_id = (msg.sticker_id or "").strip()
            if sticker_id:
                await self._send_sticker(chat_id, sticker_id, reply_to_message_id)
                if (msg.content or "").strip():
                    await self._send_text(chat_id, msg.content, reply_to_message_id)
                return

            # Check for media (images, audio, documents, etc.)
            valid_media = [p for p in (msg.media or []) if Path(p).is_file()]

            if valid_media:
                await self._send_with_media(chat_id, msg.content, valid_media, reply_to_message_id)
            else:
                await self._send_text(chat_id, msg.content, reply_to_message_id)

        except ValueError:
            logger.error("Invalid chat_id: {}", msg.chat_id)
            raise
        except Exception as e:
            logger.error("Error sending Telegram message: {}", e)
            raise

    async def _send_text(self, chat_id: int, content: str, reply_to_message_id: int | None) -> None:
        """Send a text-only message, splitting if too long."""
        if not content:
            return
        for chunk in _split_message(content):
            html_content = _markdown_to_telegram_html(chunk)
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
                fallback_kwargs: dict = {"chat_id": chat_id, "text": chunk}
                if reply_to_message_id is not None:
                    fallback_kwargs["reply_to_message_id"] = reply_to_message_id
                    fallback_kwargs["allow_sending_without_reply"] = True
                try:
                    await self._app.bot.send_message(**fallback_kwargs)
                except Exception as e2:
                    logger.error("Error sending Telegram message: {}", e2)
            # Only reply_to on the first chunk
            reply_to_message_id = None

    async def _send_sticker(self, chat_id: int, sticker_id: str, reply_to_message_id: int | None) -> None:
        """Send a Telegram sticker by file_id."""
        send_kwargs: dict = {
            "chat_id": chat_id,
            "sticker": sticker_id,
        }
        if reply_to_message_id is not None:
            send_kwargs["reply_to_message_id"] = reply_to_message_id
            send_kwargs["allow_sending_without_reply"] = True
        await self._app.bot.send_sticker(**send_kwargs)

    def _lookup_sticker(self, file_id: str) -> dict | None:
        """Lookup sticker info from workspace sticker map JSON by file_id."""
        import json
        sticker_map_path = Path.home() / ".nanobot" / "workspace" / "skills" / "sticker-kit" / "data" / "sticker_received.json"
        try:
            if sticker_map_path.exists():
                data = json.loads(sticker_map_path.read_text())
                return data.get(file_id)
        except Exception as e:
            logger.warning(f"Failed to lookup sticker: {e}")
        return None

    def _persist_sticker(self, file_id: str, emoji: str, set_name: str) -> None:
        """Auto-persist sticker file_id to workspace sticker map JSON."""
        import json
        sticker_map_path = Path.home() / ".nanobot" / "workspace" / "skills" / "sticker-kit" / "data" / "sticker_received.json"
        try:
            if sticker_map_path.exists():
                data = json.loads(sticker_map_path.read_text())
            else:
                sticker_map_path.parent.mkdir(parents=True, exist_ok=True)
                data = {}
            if file_id not in data:
                data[file_id] = {"emoji": emoji, "set_name": set_name, "description": ""}
                sticker_map_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                logger.debug(f"Persisted new sticker: {emoji} ({set_name}) -> {file_id[:20]}...")
        except Exception as e:
            logger.warning(f"Failed to persist sticker: {e}")

    async def _send_with_media(self, chat_id: int, content: str, media_paths: list[str], reply_to_message_id: int | None) -> None:
        """Send message with media files (photos, audio, documents)."""
        reply_kwargs: dict = {}
        if reply_to_message_id is not None:
            reply_kwargs["reply_to_message_id"] = reply_to_message_id
            reply_kwargs["allow_sending_without_reply"] = True

        # Separate photos from other media types
        photos = [p for p in media_paths if self._get_media_type(p) == "photo"]
        others = [p for p in media_paths if self._get_media_type(p) != "photo"]

        # Send photos (with caption on first)
        if photos:
            html_caption = _markdown_to_telegram_html(content) if content else None
            if len(photos) == 1:
                with open(photos[0], "rb") as f:
                    await self._app.bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=html_caption,
                        parse_mode="HTML" if html_caption else None,
                        **reply_kwargs,
                    )
            else:
                media_group = []
                for i, path in enumerate(photos):
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
            logger.info(f"Sent {len(photos)} photo(s) to chat_id={chat_id}")
            # Text already sent as caption for photos
            content = None

        # Send non-photo media (voice, audio, documents)
        for media_path in others:
            try:
                media_type = self._get_media_type(media_path)
                sender = {
                    "voice": self._app.bot.send_voice,
                    "audio": self._app.bot.send_audio,
                }.get(media_type, self._app.bot.send_document)
                param = media_type if media_type in ("voice", "audio") else "document"
                with open(media_path, 'rb') as f:
                    await sender(chat_id=chat_id, **{param: f}, **reply_kwargs)
            except Exception as e:
                filename = media_path.rsplit("/", 1)[-1]
                logger.error("Failed to send media {}: {}", media_path, e)
                await self._app.bot.send_message(chat_id=chat_id, text=f"[Failed to send: {filename}]")
            # Only reply_to on the first media
            reply_kwargs = {}

        # Send remaining text content (if not already sent as photo caption)
        if content and content.strip():
            await self._send_text(chat_id, content, None)

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
        """Handle incoming messages (text, photos, voice, documents, stickers)."""
        if not update.message or not update.effective_user:
            return
        
        message = update.message
        user = update.effective_user
        chat_id = message.chat_id
        sender_id = self._sender_id(user)
        
        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id
        
        # Build content from text and/or media
        content_parts = []
        media_paths = []
        is_group = message.chat.type != "private"
        sender_context = self._build_sender_context(message, user)
        if sender_context:
            content_parts.append(sender_context)
        str_chat_id = str(chat_id)
        reply_meta = self._extract_reply_metadata(message)
        reply_meta = self._enrich_reply_metadata(str_chat_id, reply_meta)
        reply_context = self._build_reply_context(reply_meta)
        if reply_context:
            content_parts.append(reply_context)
        if reply_meta.get("is_reply"):
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

        # Sticker metadata (no file download needed)
        if message.sticker:
            sticker = message.sticker
            emoji = (sticker.emoji or "").strip()
            set_name = (sticker.set_name or "").strip()
            file_id = (sticker.file_id or "").strip()
            description = ""

            # Try to enrich from local sticker map
            if file_id:
                saved = self._lookup_sticker(file_id)
                if saved:
                    # Fill in missing emoji/set_name from saved data
                    if not emoji:
                        emoji = (saved.get("emoji") or "").strip()
                    if not set_name:
                        set_name = (saved.get("set_name") or "").strip()
                    description = (saved.get("description") or "").strip()

            # Build sticker description: [sticker: emoji (set_name) description file_id=xxx]
            parts = []
            if emoji:
                parts.append(emoji)
            if set_name:
                parts.append(f"({set_name})")
            if description:
                parts.append(description)
            if file_id:
                parts.append(f"file_id={file_id}")
            if parts:
                content_parts.append(f"[sticker: {' '.join(parts)}]")
            else:
                content_parts.append("[sticker]")
            # Auto-persist sticker to workspace sticker map
            if file_id:
                self._persist_sticker(file_id, emoji, set_name)
        
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

        preview = content[: self._LOG_PREVIEW_LIMIT]
        if len(content) > self._LOG_PREVIEW_LIMIT:
            preview += "...(truncated)"
        logger.debug("Telegram message from {}: {}", sender_id, preview)

        # Keep a small per-chat index for reply fallback by message_id.
        self._remember_message(
            chat_id=str_chat_id,
            message_id=getattr(message, "message_id", None),
            sender_display=self._resolve_sender_display(user),
            text=self._build_index_text(message, media_type),
        )

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
                "sticker_file_id": getattr(message.sticker, "file_id", None),
                "sticker_emoji": getattr(message.sticker, "emoji", None),
                "sticker_set_name": getattr(message.sticker, "set_name", None),
                **reply_meta,
            },
            timestamp=getattr(message, "date", None),
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

    @staticmethod
    def _extract_reply_metadata(message) -> dict[str, object]:
        """Extract reply target metadata from Telegram message."""
        replied = message.reply_to_message
        quote = getattr(message, "quote", None)
        reply_to_message_id = getattr(message, "reply_to_message_id", None)

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
                "reply_to_message_id": getattr(replied, "message_id", None) or reply_to_message_id,
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

        if quote:
            quote_text = getattr(quote, "text", None)
            normalized_quote_text = (
                " ".join(str(quote_text).split())[:200]
                if isinstance(quote_text, str) and quote_text.strip()
                else None
            )
            return {
                "is_reply": True,
                "reply_source": "quote_only",
                "reply_to_message_id": reply_to_message_id,
                "reply_to_text": normalized_quote_text,
            }

        if reply_to_message_id is not None:
            return {
                "is_reply": True,
                "reply_source": "reply_to_message_id_only",
                "reply_to_message_id": reply_to_message_id,
            }

        return {}

    def _enrich_reply_metadata(self, chat_id: str, reply_meta: dict[str, object]) -> dict[str, object]:
        """Fill reply target info from local per-chat message index when possible."""
        if not reply_meta or not reply_meta.get("is_reply"):
            return reply_meta

        reply_id = reply_meta.get("reply_to_message_id")
        try:
            reply_id_int = int(reply_id) if reply_id is not None else None
        except (TypeError, ValueError):
            reply_id_int = None
        if reply_id_int is None:
            return reply_meta

        cached = (self._recent_messages.get(chat_id) or {}).get(reply_id_int)
        if not cached:
            return reply_meta

        enriched = dict(reply_meta)
        if not enriched.get("reply_to_first_name") and not enriched.get("reply_to_username"):
            cached_name = str(cached.get("sender_display") or "").strip()
            if cached_name:
                enriched["reply_to_first_name"] = cached_name
        if not enriched.get("reply_to_text"):
            cached_text = str(cached.get("text") or "").strip()
            if cached_text:
                enriched["reply_to_text"] = cached_text[:200]
        return enriched

    def _remember_message(
        self,
        chat_id: str,
        message_id: Any,
        sender_display: str,
        text: str,
    ) -> None:
        """Remember recent inbound messages for reply fallback."""
        try:
            msg_id = int(message_id)
        except (TypeError, ValueError):
            return

        if chat_id not in self._recent_messages:
            self._recent_messages[chat_id] = OrderedDict()

        cache = self._recent_messages[chat_id]
        cache[msg_id] = {
            "sender_display": sender_display or "unknown",
            "text": text[:200] if text else "",
        }
        cache.move_to_end(msg_id)

        while len(cache) > self._recent_message_limit:
            cache.popitem(last=False)

    @staticmethod
    def _build_index_text(message, media_type: str | None) -> str:
        """Build short plain text for local message index."""
        text = (getattr(message, "text", None) or "").strip()
        if text:
            return text
        caption = (getattr(message, "caption", None) or "").strip()
        if caption:
            return caption
        sticker = getattr(message, "sticker", None)
        if sticker:
            emoji = (getattr(sticker, "emoji", None) or "").strip()
            set_name = (getattr(sticker, "set_name", None) or "").strip()
            if emoji and set_name:
                return f"[sticker: {emoji} ({set_name})]"
            if emoji:
                return f"[sticker: {emoji}]"
            if set_name:
                return f"[sticker: {set_name}]"
            return "[sticker]"
        if media_type:
            return f"[{media_type}]"
        return "[empty message]"

    @staticmethod
    def _build_reply_context(reply_meta: dict[str, object]) -> str:
        """Build a short text prefix so the agent can see who is being replied to."""
        if not reply_meta:
            return ""

        reply_id = reply_meta.get("reply_to_message_id")
        target_name = (
            reply_meta.get("reply_to_username")
            or reply_meta.get("reply_to_first_name")
            or reply_meta.get("reply_to_chat_title")
            or reply_meta.get("reply_to_user_id")
            or (f"message_id={reply_id}" if reply_id is not None else "unknown")
        )
        target_text = reply_meta.get("reply_to_text")
        id_part = f", message_id: {reply_id}" if reply_id is not None else ""
        if target_text:
            return f"[reply_to: {target_name}{id_part}, text: {target_text}]"
        return f"[reply_to: {target_name}{id_part}]"

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
        
        Includes message_id (for reactions) and message_time in group chats.
        """
        from datetime import timezone, timedelta
        msg_id = getattr(message, "message_id", None)
        # Format message time in CST (UTC+8)
        msg_date = getattr(message, "date", None)
        time_str = ""
        if msg_date:
            cst = timezone(timedelta(hours=8))
            time_str = msg_date.astimezone(cst).strftime("%Y-%m-%d %H:%M")

        if message.chat.type == "private":
            # Still include message_id and time for private chats
            parts = []
            if msg_id is not None:
                parts.append(f"message_id: {msg_id}")
            if time_str:
                parts.append(f"current_time {time_str}")
            return f"[{', '.join(parts)}]" if parts else ""

        sender = cls._resolve_sender_display(user)
        chat_title = getattr(message.chat, "title", None)
        extra_parts = []
        if msg_id is not None:
            extra_parts.append(f"message_id: {msg_id}")
        if time_str:
            extra_parts.append(f"current_time {time_str}")
        extra = f", {', '.join(extra_parts)}" if extra_parts else ""
        if chat_title:
            return f"[from: {sender}, group: {chat_title}{extra}]"
        return f"[from: {sender}{extra}]"
