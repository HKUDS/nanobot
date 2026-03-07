"""Telegram channel implementation using python-telegram-bot."""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from typing import Any, TYPE_CHECKING

from loguru import logger
from telegram import BotCommand, ReplyParameters, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import TelegramConfig
from nanobot.utils.helpers import split_message

TELEGRAM_MAX_MESSAGE_LEN = 4000  # Telegram message character limit
TELEGRAM_REPLY_CONTEXT_MAX_LEN = TELEGRAM_MAX_MESSAGE_LEN  # Max length for reply context in user message


def _strip_md(s: str) -> str:
    """Strip markdown inline formatting from text."""
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'~~(.+?)~~', r'\1', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)
    return s.strip()


def _render_table_box(table_lines: list[str]) -> str:
    """Convert markdown pipe-table to compact aligned text for <pre> display."""

    def dw(s: str) -> int:
        return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)

    rows: list[list[str]] = []
    has_sep = False
    for line in table_lines:
        cells = [_strip_md(c) for c in line.strip().strip('|').split('|')]
        if all(re.match(r'^:?-+:?$', c) for c in cells if c):
            has_sep = True
            continue
        rows.append(cells)
    if not rows or not has_sep:
        return '\n'.join(table_lines)

    ncols = max(len(r) for r in rows)
    for r in rows:
        r.extend([''] * (ncols - len(r)))
    widths = [max(dw(r[c]) for r in rows) for c in range(ncols)]

    def dr(cells: list[str]) -> str:
        return '  '.join(f'{c}{" " * (w - dw(c))}' for c, w in zip(cells, widths))

    out = [dr(rows[0])]
    out.append('  '.join('─' * w for w in widths))
    for row in rows[1:]:
        out.append(dr(row))
    return '\n'.join(out)


def _markdown_to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram-safe HTML."""
    if not text:
        return ""

    # 1. Extract and protect code blocks
    code_blocks: list[str] = []
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"
    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)

    # 1.5. Convert markdown tables to box-drawing
    lines = text.split('\n')
    rebuilt: list[str] = []
    li = 0
    while li < len(lines):
        if re.match(r'^\s*\|.+\|', lines[li]):
            tbl: list[str] = []
            while li < len(lines) and re.match(r'^\s*\|.+\|', lines[li]):
                tbl.append(lines[li])
                li += 1
            box = _render_table_box(tbl)
            if box != '\n'.join(tbl):
                code_blocks.append(box)
                rebuilt.append(f"\x00CB{len(code_blocks) - 1}\x00")
            else:
                rebuilt.extend(tbl)
        else:
            rebuilt.append(lines[li])
            li += 1
    text = '\n'.join(rebuilt)

    # 2. Extract and protect inline code
    inline_codes: list[str] = []
    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"
    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # 3. Headers
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # 4. Blockquotes
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)

    # 5. Escape HTML
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Links
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # 7. Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # 8. Italic
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)

    # 9. Strikethrough
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # 10. Bullet lists
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 11. Restore inline code
    for i, code in enumerate(inline_codes):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 12. Restore code blocks
    for i, code in enumerate(code_blocks):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text


class TelegramChannel(BaseChannel):
    """Telegram channel using long polling with hook-based architecture."""

    name = "telegram"

    BOT_COMMANDS = [
        BotCommand("start", "Start the bot"),
        BotCommand("new", "Start a new conversation"),
        BotCommand("stop", "Stop the current task"),
        BotCommand("help", "Show available commands"),
        BotCommand("restart", "Restart the bot"),
        BotCommand("jobs", "Show running jobs"),
        BotCommand("thread", "Create a new discussion thread"),
        BotCommand("topic", "Manage named conversation topics"),
    ]

    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        groq_api_key: str = "",
        session_manager: SessionManager | None = None,
        tool_executor: Any = None,
        tool_definitions: list[dict[str, Any]] | None = None,
        on_tool_call: Any = None,
        is_session_busy: Any = None,
    ):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self.session_manager = session_manager
        self.tool_executor = tool_executor
        self.tool_definitions = tool_definitions or []
        self.on_tool_call = on_tool_call
        self.is_session_busy = is_session_busy
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._media_group_buffers: dict[str, dict] = {}
        self._media_group_tasks: dict[str, asyncio.Task] = {}
        self._message_threads: dict[tuple[str, int], int] = {}
        self._bot_user_id: int | None = None
        self._bot_username: str | None = None
        self._session_threads: dict[str, int] = {}
        self._thread_info: dict[int, dict[str, Any]] = {}

    def is_allowed(self, sender_id: str) -> bool:
        """Preserve Telegram's legacy id|username allowlist matching."""
        if super().is_allowed(sender_id):
            return True

        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list or "*" in allow_list:
            return False

        sender_str = str(sender_id)
        if sender_str.count("|") != 1:
            return False

        sid, username = sender_str.split("|", 1)
        if not sid.isdigit() or not username:
            return False

        return sid in allow_list or username in allow_list

    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return

        self._running = True

        # Build application with proxy support
        req = HTTPXRequest(
            connection_pool_size=16,
            pool_timeout=5.0,
            connect_timeout=30.0,
            read_timeout=30.0,
            proxy=self.config.proxy if self.config.proxy else None,
        )
        builder = Application.builder().token(self.config.token).request(req).get_updates_request(req)
        self._app = builder.build()
        self._app.add_error_handler(self._on_error)

        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("new", self._forward_command))
        self._app.add_handler(CommandHandler("stop", self._forward_command))
        self._app.add_handler(CommandHandler("restart", self._forward_command))
        self._app.add_handler(CommandHandler("help", self._on_help))
        self._app.add_handler(CommandHandler("jobs", self._on_jobs_command))
        self._app.add_handler(CommandHandler("thread", self._on_thread_command))
        self._app.add_handler(CommandHandler("topic", self._on_topic_command))

        # Add message handler
        self._app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL)
                & ~filters.COMMAND,
                self._on_message
            )
        )

        # Add callback query handler
        self._app.add_handler(CallbackQueryHandler(self._on_callback, pattern="^restart_gateway:"))

        logger.info("Starting Telegram bot (polling mode)...")

        await self._app.initialize()
        await self._app.start()

        bot_info = await self._app.bot.get_me()
        logger.info("Telegram bot @{} connected", bot_info.username)

        # Allow plugins to register handlers
        from nanobot.system.hooks import hook_manager
        await hook_manager.emit("telegram.init", app=self._app, channel=self)

        try:
            unique_commands = {}
            for cmd in self.BOT_COMMANDS:
                unique_commands[cmd.command] = cmd
            await self._app.bot.set_my_commands(list(unique_commands.values()))
        except Exception as e:
            logger.warning("Failed to register bot commands: {}", e)

        try:
            await self._app.updater.start_polling(
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True,
                poll_interval=1.0,
                timeout=30
            )
        except Exception as e:
            logger.error(f"Error starting Telegram polling: {e}")
            raise

        while self._running:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Telegram polling loop: {e}")
                await asyncio.sleep(2)

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False

        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)

        for task in self._media_group_tasks.values():
            task.cancel()
        self._media_group_tasks.clear()
        self._media_group_buffers.clear()

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

        # Stop typing indicator
        session_key = msg.metadata.get("session_key", f"telegram:{msg.chat_id}") if msg.metadata else f"telegram:{msg.chat_id}"
        self._stop_typing(session_key)

        try:
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error("Invalid chat_id: {}", msg.chat_id)
            return

        thread_id = msg.metadata.get("thread_id") if msg.metadata else None
        reply_to_message_id = msg.metadata.get("message_id") if msg.metadata else None

        reply_params = None
        if self.config.reply_to_message and reply_to_message_id:
            reply_params = ReplyParameters(
                message_id=reply_to_message_id,
                allow_sending_without_reply=True
            )

        thread_kwargs = {}
        if thread_id is not None:
            thread_kwargs["message_thread_id"] = thread_id

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
                        reply_parameters=reply_params,
                        **thread_kwargs,
                    )
            except Exception as e:
                filename = media_path.rsplit("/", 1)[-1]
                logger.error("Failed to send media {}: {}", media_path, e)
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=f"[Failed to send: {filename}]",
                    reply_parameters=reply_params,
                    **thread_kwargs,
                )

        # Send text content
        if msg.content and msg.content != "[empty message]":
            for chunk in split_message(msg.content, TELEGRAM_MAX_MESSAGE_LEN):
                await self._send_text(chat_id, chunk, reply_params, thread_kwargs, msg.metadata)

    async def _send_text(
        self,
        chat_id: int,
        text: str,
        reply_params=None,
        thread_kwargs: dict | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Send a plain text message with HTML fallback and optional inline keyboard."""
        metadata = metadata or {}
        reply_markup = None
        
        # Handle inline keyboard from metadata
        if "reply_markup" in metadata:
            keyboard_data = metadata["reply_markup"]
            if isinstance(keyboard_data, dict) and "inline_keyboard" in keyboard_data:
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = []
                for row in keyboard_data["inline_keyboard"]:
                    button_row = []
                    for btn in row:
                        button_row.append(InlineKeyboardButton(
                            text=btn.get("text", ""),
                            callback_data=btn.get("callback_data"),
                            url=btn.get("url"),
                        ))
                    keyboard.append(button_row)
                reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            html = _markdown_to_telegram_html(text)
            await self._app.bot.send_message(
                chat_id=chat_id, text=html, parse_mode="HTML",
                reply_parameters=reply_params,
                reply_markup=reply_markup,
                **(thread_kwargs or {}),
            )
        except Exception as e:
            logger.warning("HTML parse failed, falling back to plain text: {}", e)
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_parameters=reply_params,
                    reply_markup=reply_markup,
                    **(thread_kwargs or {}),
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
            "Type /help to see available commands.\n"
            "Type /thread <name> to start a new discussion thread."
        )

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not update.message:
            return
        await update.message.reply_text(
            "🐈 nanobot commands:\n"
            "/new — Start a new conversation\n"
            "/stop — Stop the current task\n"
            "/jobs — Show running jobs\n"
            "/help — Show available commands\n"
            "/thread <name> — Create a forum topic\n"
            "/topic — Manage named topics"
        )

    @staticmethod
    def _sender_id(user) -> str:
        """Build sender_id with username for allowlist matching."""
        sid = str(user.id)
        return f"{sid}|{user.username}" if user.username else sid

    @staticmethod
    def _derive_topic_session_key(message) -> str | None:
        """Derive topic-scoped session key for non-private Telegram chats."""
        message_thread_id = getattr(message, "message_thread_id", None)
        if message.chat.type == "private" or message_thread_id is None:
            return None
        return f"telegram:{message.chat_id}:topic:{message_thread_id}"

    @staticmethod
    def _build_message_metadata(message, user) -> dict:
        """Build common Telegram inbound metadata payload."""
        reply_to = getattr(message, "reply_to_message", None)
        return {
            "message_id": message.message_id,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_group": message.chat.type != "private",
            "message_thread_id": getattr(message, "message_thread_id", None),
            "is_forum": bool(getattr(message.chat, "is_forum", False)),
            "reply_to_message_id": getattr(reply_to, "message_id", None) if reply_to else None,
        }

    @staticmethod
    def _extract_reply_context(message) -> str | None:
        """Extract text from the message being replied to, if any."""
        reply = getattr(message, "reply_to_message", None)
        if not reply:
            return None
        text = getattr(reply, "text", None) or getattr(reply, "caption", None) or ""
        if len(text) > TELEGRAM_REPLY_CONTEXT_MAX_LEN:
            text = text[:TELEGRAM_REPLY_CONTEXT_MAX_LEN] + "..."
        return f"[Reply to: {text}]" if text else None

    async def _download_message_media(
        self, msg, *, add_failure_content: bool = False
    ) -> tuple[list[str], list[str]]:
        """Download media from a message (current or reply). Returns (media_paths, content_parts)."""
        media_file = None
        media_type = None
        if getattr(msg, "photo", None):
            media_file = msg.photo[-1]
            media_type = "image"
        elif getattr(msg, "voice", None):
            media_file = msg.voice
            media_type = "voice"
        elif getattr(msg, "audio", None):
            media_file = msg.audio
            media_type = "audio"
        elif getattr(msg, "document", None):
            media_file = msg.document
            media_type = "file"
        elif getattr(msg, "video", None):
            media_file = msg.video
            media_type = "video"
        elif getattr(msg, "video_note", None):
            media_file = msg.video_note
            media_type = "video"
        elif getattr(msg, "animation", None):
            media_file = msg.animation
            media_type = "animation"
        if not media_file or not self._app:
            return [], []
        try:
            file = await self._app.bot.get_file(media_file.file_id)
            ext = self._get_extension(
                media_type,
                getattr(media_file, "mime_type", None),
                getattr(media_file, "file_name", None),
            )
            media_dir = get_media_dir("telegram")
            file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
            await file.download_to_drive(str(file_path))
            path_str = str(file_path)
            if media_type in ("voice", "audio"):
                transcription = await self.transcribe_audio(file_path)
                if transcription:
                    logger.info("Transcribed {}: {}...", media_type, transcription[:50])
                    return [path_str], [f"[transcription: {transcription}]"]
                return [path_str], [f"[{media_type}: {path_str}]"]
            return [path_str], [f"[{media_type}: {path_str}]"]
        except Exception as e:
            logger.warning("Failed to download message media: {}", e)
            if add_failure_content:
                return [], [f"[{media_type}: download failed]"]
            return [], []

    async def _ensure_bot_identity(self) -> tuple[int | None, str | None]:
        """Load bot identity once and reuse it for mention/reply checks."""
        if self._bot_user_id is not None or self._bot_username is not None:
            return self._bot_user_id, self._bot_username
        if not self._app:
            return None, None
        bot_info = await self._app.bot.get_me()
        self._bot_user_id = getattr(bot_info, "id", None)
        self._bot_username = getattr(bot_info, "username", None)
        return self._bot_user_id, self._bot_username

    @staticmethod
    def _has_mention_entity(
        text: str,
        entities,
        bot_username: str,
        bot_id: int | None,
    ) -> bool:
        """Check Telegram mention entities against the bot username."""
        handle = f"@{bot_username}".lower()
        for entity in entities or []:
            entity_type = getattr(entity, "type", None)
            if entity_type == "text_mention":
                user = getattr(entity, "user", None)
                if user is not None and bot_id is not None and getattr(user, "id", None) == bot_id:
                    return True
                continue
            if entity_type != "mention":
                continue
            offset = getattr(entity, "offset", None)
            length = getattr(entity, "length", None)
            if offset is None or length is None:
                continue
            if text[offset : offset + length].lower() == handle:
                return True
        return handle in text.lower()

    async def _is_group_message_for_bot(self, message) -> bool:
        """Allow group messages when policy is open, @mentioned, or replying to the bot."""
        if message.chat.type == "private" or self.config.group_policy == "open":
            return True

        bot_id, bot_username = await self._ensure_bot_identity()
        if bot_username:
            text = message.text or ""
            caption = message.caption or ""
            if self._has_mention_entity(
                text,
                getattr(message, "entities", None),
                bot_username,
                bot_id,
            ):
                return True
            if self._has_mention_entity(
                caption,
                getattr(message, "caption_entities", None),
                bot_username,
                bot_id,
            ):
                return True

        reply_user = getattr(getattr(message, "reply_to_message", None), "from_user", None)
        return bool(bot_id and reply_user and reply_user.id == bot_id)

    def _remember_thread_context(self, message) -> None:
        """Cache topic thread id by chat/message id for follow-up replies."""
        message_thread_id = getattr(message, "message_thread_id", None)
        if message_thread_id is None:
            return
        key = (str(message.chat_id), message.message_id)
        self._message_threads[key] = message_thread_id
        if len(self._message_threads) > 1000:
            self._message_threads.pop(next(iter(self._message_threads)))

    async def _on_jobs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /jobs command."""
        if not update.message:
            return
        
        from nanobot.agent.job_tracker import job_manager
        running_jobs = []
        completed_jobs = []
        for session_key, jobs in job_manager._jobs.items():
            for job in jobs:
                if job.status == "running":
                    running_jobs.append(job)
                elif job.status == "completed":
                    completed_jobs.append(job)
        
        # Sort completed by created_at descending
        completed_jobs.sort(key=lambda j: j.created_at, reverse=True)
        recent_completed = completed_jobs[:5]  # Show last 5 completed
        
        lines = []
        
        if running_jobs:
            lines.append(f"🔄 *{len(running_jobs)} job(s) running:*\n")
            for job in running_jobs:
                duration = job.duration_seconds
                thread_info = f" (thread {job.thread_id})" if job.thread_id else ""
                lines.append(
                    f"• `{job.id[:8]}`{thread_info}\n"
                    f"  {job.user_message[:50]}{'...' if len(job.user_message) > 50 else ''}\n"
                    f"  ⏱️ {duration:.1f}s | {len(job.tool_calls)} tools\n"
                )
        
        if recent_completed:
            lines.append(f"\n✅ *Recent completed:*\n")
            for job in recent_completed:
                duration = job.duration_seconds
                thread_info = f" (thread {job.thread_id})" if job.thread_id else ""
                lines.append(
                    f"• `{job.id[:8]}`{thread_info}\n"
                    f"  {job.user_message[:50]}{'...' if len(job.user_message) > 50 else ''}\n"
                    f"  ⏱️ {duration:.1f}s | {len(job.tool_calls)} tools\n"
                )
        
        if not running_jobs and not recent_completed:
            await update.message.reply_text("✅ No jobs found.")
            return
        
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _on_thread_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /thread command - create a forum topic."""
        if not update.message or not update.effective_user:
            return
        
        chat_id = update.message.chat_id
        args = context.args if context.args else []
        thread_name = " ".join(args) if args else None
        
        if not thread_name:
            from datetime import datetime
            thread_name = f"Thread {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        result = await self.create_forum_topic(chat_id, thread_name)
        
        if result:
            thread_id = result["message_thread_id"]
            await update.message.reply_text(
                f"🧵 Created new thread: *{thread_name}*\n"
                f"Thread ID: `{thread_id}`\n\n"
                f"Messages sent in this thread will have their own conversation context.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "❌ Failed to create thread. Make sure the bot has permission to manage topics."
            )

    async def _on_topic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /topic command - manage named conversation topics."""
        if not update.message or not update.effective_user:
            return
        
        chat_id = str(update.message.chat_id)
        args = context.args if context.args else []
        
        if not args:
            await update.message.reply_text(
                "📁 *Named Topics*\n\n"
                "Commands:\n"
                "/topic list - List all topics\n"
                "/topic current - Show current topic\n"
                "/topic create <name> - Create a new topic\n"
                "/topic switch <name> - Switch to a topic\n"
                "/topic delete <name> - Delete a topic",
                parse_mode="Markdown"
            )
            return
        
        from nanobot.agent.tools.topics import TopicTool
        tool = TopicTool()
        session_key = f"telegram:{chat_id}"
        action = args[0].lower()
        name = " ".join(args[1:]) if len(args) > 1 else None
        
        if action == "list":
            result = tool.execute(action="list", session_key=session_key)
        elif action == "current":
            result = tool.execute(action="current", session_key=session_key)
        elif action == "create":
            if not name:
                await update.message.reply_text("❌ Usage: /topic create <name>")
                return
            result = tool.execute(action="create", name=name, session_key=session_key)
        elif action == "switch":
            if not name:
                await update.message.reply_text("❌ Usage: /topic switch <name>")
                return
            result = tool.execute(action="switch", name=name, session_key=session_key)
        elif action == "delete":
            if not name:
                await update.message.reply_text("❌ Usage: /topic delete <name>")
                return
            result = tool.execute(action="delete", name=name, session_key=session_key)
        else:
            await update.message.reply_text(f"❌ Unknown action: {action}")
            return
        
        if "error" in result:
            await update.message.reply_text(f"❌ {result['error']}")
        else:
            await update.message.reply_text(result.get("message", "Done"))

    async def _forward_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Forward slash commands to the bus."""
        if not update.message or not update.effective_user:
            return
        message = update.message
        user = update.effective_user
        self._remember_thread_context(message)
        await self._handle_message(
            sender_id=self._sender_id(user),
            chat_id=str(message.chat_id),
            content=message.text or "",
            metadata=self._build_message_metadata(message, user),
            session_key=self._derive_topic_session_key(message),
        )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id
        
        thread_id = message.message_thread_id
        is_topic_message = getattr(message, 'is_topic_message', False) or thread_id is not None
        
        sender_id = self._sender_id(user)
        self._remember_thread_context(message)

        self._chat_ids[sender_id] = chat_id
        
        str_chat_id = str(chat_id)
        if thread_id:
            session_key = f"telegram:{str_chat_id}:{thread_id}"
        else:
            session_key = f"telegram:{str_chat_id}"

        # Build content
        content_parts = []
        media_paths = []

        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        # Download current message media
        current_media_paths, current_media_parts = await self._download_message_media(
            message, add_failure_content=True
        )
        media_paths.extend(current_media_paths)
        content_parts.extend(current_media_parts)
        if current_media_paths:
            logger.debug("Downloaded message media to {}", current_media_paths[0])

        # Reply context: text and/or media from the replied-to message
        reply = getattr(message, "reply_to_message", None)
        if reply is not None:
            reply_ctx = self._extract_reply_context(message)
            reply_media, reply_media_parts = await self._download_message_media(reply)
            if reply_media:
                media_paths = reply_media + media_paths
                logger.debug("Attached replied-to media: {}", reply_media[0])
            tag = reply_ctx or (f"[Reply to: {reply_media_parts[0]}]" if reply_media_parts else None)
            if tag:
                content_parts.insert(0, tag)
        content = "\n".join(content_parts) if content_parts else "[empty message]"

        metadata = self._build_message_metadata(message, user)
        metadata["thread_id"] = thread_id
        session_key = self._derive_topic_session_key(message)

        # Handle media groups
        if media_group_id := getattr(message, "media_group_id", None):
            key = f"{str_chat_id}:{media_group_id}"
            if key not in self._media_group_buffers:
                self._media_group_buffers[key] = {
                    "sender_id": sender_id, "chat_id": str_chat_id,
                    "contents": [], "media": [],
                    "metadata": metadata,
                    "session_key": session_key,
                }
                self._start_typing(str_chat_id)
            buf = self._media_group_buffers[key]
            if content and content != "[empty message]":
                buf["contents"].append(content)
            buf["media"].extend(media_paths)
            if key not in self._media_group_tasks:
                self._media_group_tasks[key] = asyncio.create_task(self._flush_media_group(key))
            return

        self._start_typing(session_key)
        
        # Create job for tracking
        from nanobot.agent.job_tracker import job_manager
        from nanobot.system.hooks import hook_manager
        
        # Skip job creation if there's already a running job for this session
        # but still process the message (it will be queued by the agent loop)
        if not job_manager.has_running_job(session_key):
            logger.info(f"[TELEGRAM] Creating job for session_key={session_key}")
            job = await job_manager.create_job(
                session_key=session_key,
                channel="telegram",
                chat_id=str_chat_id,
                user_message=content,
            )
            logger.info(f"[TELEGRAM] Created job {job.id}")
            
            if thread_id:
                await job_manager.set_thread_id(job.id, thread_id)
            
            metadata["job_id"] = job.id
            
            logger.info(f"[TELEGRAM] Emitting agent.job.created for job {job.id}")
            await hook_manager.emit("agent.job.created",
                job=job,
                channel="telegram",
                chat_id=str_chat_id,
                thread_id=thread_id,
            )
            logger.info(f"[TELEGRAM] Emitted agent.job.created for job {job.id}")
        else:
            logger.info(f"[TELEGRAM] Skipping job creation - running job exists for {session_key}")

        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
            media=media_paths,
            metadata=metadata,
            session_key=session_key,
        )

    async def _flush_media_group(self, key: str) -> None:
        """Wait briefly, then forward buffered media-group as one turn."""
        try:
            await asyncio.sleep(0.6)
            if not (buf := self._media_group_buffers.pop(key, None)):
                return
            content = "\n".join(buf["contents"]) or "[empty message]"
            await self._handle_message(
                sender_id=buf["sender_id"], chat_id=buf["chat_id"],
                content=content, media=list(dict.fromkeys(buf["media"])),
                metadata=buf["metadata"],
                session_key=buf.get("session_key"),
            )
        finally:
            self._media_group_tasks.pop(key, None)

    def _start_typing(self, chat_id: str) -> None:
        """Start sending 'typing...' indicator for a chat."""
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
                await self._app.bot.send_chat_action(
                    chat_id=int(chat_id),
                    action=ChatAction.TYPING,
                )
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Typing indicator stopped for {}: {}", chat_id, e)

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log polling / handler errors."""
        logger.error("Telegram error: {}", context.error)

    async def _on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle callback queries from inline buttons."""
        if not update.callback_query:
            return
        
        query = update.callback_query
        data = query.data or ""
        
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"Failed to answer callback: {e}")
        
        if data.startswith("restart_gateway:"):
            parts = data.split(":")
            action = parts[1] if len(parts) > 1 else ""
            force = parts[2] == "force" if len(parts) > 2 else False
            
            if action == "confirm":
                await query.edit_message_text("🔄 Restarting gateway...")
                
                try:
                    from nanobot.agent.tools.gateway import write_restart_marker
                    import sys
                    
                    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
                    
                    if chat_id:
                        write_restart_marker(chat_id, "telegram", f"telegram:{chat_id}")
                    
                    cmd = [sys.executable, "-m", "nanobot", "gateway", "--force"]
                    if force:
                        cmd.append("--force")
                    
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=None,
                        stderr=None,
                        start_new_session=True,
                    )
                    
                    logger.info(f"Gateway restart triggered by user button click: PID {process.pid}")
                    
                except Exception as e:
                    logger.error(f"Failed to restart gateway from callback: {e}")
                    await query.edit_message_text(f"❌ Failed to restart: {e}")
            
            elif action == "cancel":
                await query.edit_message_text("❌ Gateway restart cancelled.")

    def _get_extension(
        self,
        media_type: str,
        mime_type: str | None,
        filename: str | None = None,
    ) -> str:
        """Get file extension based on media type or original filename."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]

        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        if ext := type_map.get(media_type, ""):
            return ext

        if filename:
            from pathlib import Path

            return "".join(Path(filename).suffixes)

        return ""

    # Forum Topic Methods
    
    async def create_forum_topic(
        self,
        chat_id: int,
        name: str,
        icon_color: int | None = None,
        icon_custom_emoji_id: str | None = None,
    ) -> dict | None:
        """Create a new forum topic (thread) in a chat."""
        if not self._app:
            return None
        
        try:
            params = {
                "chat_id": chat_id,
                "name": name[:128],
            }
            if icon_color is not None:
                params["icon_color"] = icon_color
            if icon_custom_emoji_id:
                params["icon_custom_emoji_id"] = icon_custom_emoji_id
            
            result = await self._app.bot._post("createForumTopic", params, api_kwargs=params)
            
            if result:
                thread_id = result.get("message_thread_id")
                self._thread_info[thread_id] = {
                    "name": name,
                    "icon_emoji_id": icon_custom_emoji_id,
                    "chat_id": chat_id,
                }
                return result
            return None
        except Exception as e:
            logger.error(f"Failed to create forum topic: {e}")
            return None

    async def get_or_create_thread_for_session(
        self,
        chat_id: int,
        session_name: str,
        session_key: str,
    ) -> int | None:
        """Get existing thread for a session, or create a new one."""
        if session_key in self._session_threads:
            return self._session_threads[session_key]
        
        result = await self.create_forum_topic(chat_id, session_name)
        if result:
            thread_id = result["message_thread_id"]
            self._session_threads[session_key] = thread_id
            return thread_id
        
        return None
