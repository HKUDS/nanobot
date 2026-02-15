"""Telegram channel implementation using python-telegram-bot."""

from __future__ import annotations

import asyncio
import re
from typing import Any, TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager
from telegram import BotCommand, Update, InlineKeyboardButton, InlineKeyboardMarkup
from nanobot.agent.job_tracker import job_manager
from nanobot.system.hooks import hook_manager
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TelegramConfig
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
    Supports forum topics (threads) for organized conversations.
    """
    
    name = "telegram"
    
    # Commands registered with Telegram's command menu
    BOT_COMMANDS = [
        BotCommand("start", "Start the bot"),
        BotCommand("new", "Start a new conversation"),
        BotCommand("help", "Show available commands"),
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
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        self._typing_tasks: dict[str, asyncio.Task] = {}  # chat_id -> typing loop task
        # Forum topic (thread) tracking: session_key -> thread_id
        self._session_threads: dict[str, int] = {}
        # Thread metadata: thread_id -> {name, icon_emoji_id, created_at}
        self._thread_info: dict[int, dict[str, Any]] = {}
    
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
        self._app.add_handler(CommandHandler("help", self._forward_command))
        self._app.add_handler(CommandHandler("thread", self._on_thread_command))
        self._app.add_handler(CommandHandler("topic", self._on_topic_command))
        
        # Add message handler for text, photos, voice, documents
        self._app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL)
                & ~filters.COMMAND,
                self._on_message
            )
        )
        
        # Add callback query handler for inline buttons - only handle restart_gateway callbacks
        # Other callbacks (job_progress, job:expand, etc.) are handled by plugins via telegram.init hook
        self._app.add_handler(CallbackQueryHandler(self._on_callback, pattern="^restart_gateway:"))
        
        # Note: Additional callback handlers should be registered via the telegram.init hook
        # to avoid conflicts with the plugin system's callback handling
        
        logger.info("Starting Telegram bot (polling mode)...")
        
        # Initialize and start polling
        await self._app.initialize()
        await self._app.start()
        
        # Get bot info and register command menu
        bot_info = await self._app.bot.get_me()
        logger.info(f"Telegram bot @{bot_info.username} connected")
        
        # NEW: Allow plugins to register handlers and modify BOT_COMMANDS
        from nanobot.system.hooks import hook_manager
        await hook_manager.emit("telegram.init", app=self._app, channel=self)

        try:
            # Deduplicate commands by name
            unique_commands = {}
            for cmd in self.BOT_COMMANDS:
                unique_commands[cmd.command] = cmd
            
            await self._app.bot.set_my_commands(list(unique_commands.values()))
            logger.debug(f"Telegram bot commands registered ({len(unique_commands)} commands)")
        except Exception as e:
            logger.warning(f"Failed to register bot commands: {e}")
        
        # Start polling (this runs until stopped)
        try:
            await self._app.updater.start_polling(
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True,  # Ignore old messages on startup
                poll_interval=1.0,  # Add delay between polls to reduce connection issues
                timeout=30  # Increase timeout for get_updates
            )
        except Exception as e:
            logger.error(f"Error starting Telegram polling: {e}")
            raise
        
        # Keep running until stopped with error recovery
        while self._running:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Telegram polling loop: {e}")
                # Brief pause before continuing to avoid rapid error loops
                await asyncio.sleep(2)
    
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
        
        # Extract thread_id from metadata for routing
        thread_id = msg.metadata.get("thread_id") if msg.metadata else None
        
        # Build session_key for typing indicator (matches how inbound messages are keyed)
        if thread_id:
            session_key = f"telegram:{msg.chat_id}:{thread_id}"
        else:
            session_key = f"telegram:{msg.chat_id}"
        
        # Stop typing indicator for this session
        self._stop_typing(session_key)
        
        try:
            # chat_id should be the Telegram chat ID (integer)
            chat_id = int(msg.chat_id)
            
            # Convert markdown to Telegram HTML
            html_content = _markdown_to_telegram_html(msg.content)
            
            # Validate HTML content
            if not html_content or len(html_content.strip()) == 0:
                logger.warning(f"HTML conversion produced empty content, using escaped original")
                html_content = msg.content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            
            # Check if we should edit an existing job message
            job_id = msg.metadata.get("job_id")
            is_intermediate = msg.metadata.get("intermediate", False)
            
            if job_id:
                job = await job_manager.get_job(job_id)
                if job and job.message_id:
                    try:
                        # ASSERT: We should only be editing timeline messages, not already-consumed text messages
                        # If job.message_id exists but was already consumed, that's a bug
                        message_id_int = int(job.message_id)
                        
                        # CRITICAL FIX: Clear job.message_id IMMEDIATELY to prevent race condition
                        # where _update_timeline finds job.message_id still set after message is consumed
                        consumed_msg_id = int(job.message_id)
                        await job_manager.set_message_id(job_id, None)
                        logger.info(f"[RACE-FIX] Cleared job.message_id for job {job_id} before consuming message {consumed_msg_id}")
                        
                        # CRITICAL: Remove from timeline cache BEFORE editing to prevent race condition
                        # where _update_timeline edits it back to timeline while we're converting to text
                        await hook_manager.emit("telegram.timeline.consumed",
                            job_id=job_id,
                            message_id=consumed_msg_id
                        )
                        logger.info(f"Pre-emptively removed job {job_id} from timeline cache before editing message {consumed_msg_id}")
                        
                        # Edit the current timeline message to show the content
                        # CRITICAL: Remove reply_markup to clear inline keyboard buttons
                        from telegram import InlineKeyboardMarkup
                        logger.info(f"[RACE-FIX] Editing consumed message {consumed_msg_id} for job {job_id} (job.message_id is now None)")
                        await self._app.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=consumed_msg_id,
                            text=html_content,
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup([])  # Force remove inline keyboard
                        )
                        logger.info(f"[RACE-FIX] Successfully edited message {consumed_msg_id} for job {job_id}")
                        
                        # Handle post-consumption logic (request new timeline if intermediate)
                        await self._consume_timeline(job_id, consumed_msg_id, is_intermediate, chat_id)
                        
                        return
                    except Exception as e:
                        if "message is not modified" in str(e).lower():
                            logger.info(f"Message {job.message_id} not modified (same content)")
                            return
                        logger.error(f"Failed to edit job message {job.message_id} with HTML: {e}")
                        # Try editing with plain text instead
                        try:
                            # Remove from cache before editing (race condition prevention)
                            await hook_manager.emit("telegram.timeline.consumed",
                                job_id=job_id,
                                message_id=int(job.message_id)
                            )
                            
                            logger.info(f"Retrying edit with plain text for job {job_id}")
                            await self._app.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=int(job.message_id),
                                text=msg.content,
                                parse_mode=None,  # No parsing
                                reply_markup=None  # Remove inline keyboard
                            )
                            logger.info(f"Successfully edited message {job.message_id} with plain text")
                            
                            # Handle post-consumption logic (clear message_id, request new timeline if intermediate)
                            await self._consume_timeline(job_id, int(job.message_id), is_intermediate, chat_id, source="plain text")
                            
                            return
                        except Exception as e2:
                            logger.error(f"Failed to edit with plain text too: {e2}")
                            # Editing failed - we must still send the content
                            # The old timeline will remain, which is unfortunate but we can't delete it
                            logger.warning(f"Timeline editing failed for job {job_id}, sending content as new message")

            # Check for reply_markup (inline keyboard) in metadata
            reply_markup = None
            if msg.metadata and "reply_markup" in msg.metadata:
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard_data = msg.metadata["reply_markup"]
                keyboard = []
                for row in keyboard_data.get("inline_keyboard", []):
                    keyboard_row = []
                    for button in row:
                        keyboard_row.append(InlineKeyboardButton(
                            text=button["text"],
                            callback_data=button["callback_data"]
                        ))
                    keyboard.append(keyboard_row)
                reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=html_content,
                parse_mode="HTML",
                reply_markup=reply_markup,
                message_thread_id=thread_id,  # Send to specific thread if set
            )
        except ValueError:
            logger.error(f"Invalid chat_id: {msg.chat_id}")
        except Exception as e:
            # Fallback to plain text if HTML parsing fails
            logger.warning(f"HTML parse failed, falling back to plain text: {e}")
            try:
                await self._app.bot.send_message(
                    chat_id=int(msg.chat_id),
                    text=msg.content,
                    message_thread_id=thread_id,  # Send to specific thread if set
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
            "Send me a message and I'll respond!\n"
            "Type /help to see available commands.\n"
            "Type /thread <name> to start a new discussion thread."
        )
    
    async def _on_thread_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /thread command - create a new forum topic (thread)."""
        if not update.message or not update.effective_user:
            return
        
        chat_id = update.message.chat_id
        user = update.effective_user
        
        # Parse thread name from command arguments
        args = context.args if context.args else []
        thread_name = " ".join(args) if args else None
        
        if not thread_name:
            # Generate a default name with timestamp
            from datetime import datetime
            thread_name = f"Thread {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        # Create the forum topic
        result = await self.create_forum_topic(chat_id, thread_name)
        
        if result:
            thread_id = result["message_thread_id"]
            await update.message.reply_text(
                f"🧵 Created new thread: *{thread_name}*\n"
                f"Thread ID: `{thread_id}`\n\n"
                f"Messages sent in this thread will have their own conversation context.",
                parse_mode="Markdown"
            )
            logger.info(f"Created forum topic '{thread_name}' (ID: {thread_id}) in chat {chat_id}")
        else:
            await update.message.reply_text(
                "❌ Failed to create thread. Make sure the bot has permission to manage topics."
            )
    
    async def _on_topic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /topic command - manage named conversation topics."""
        if not update.message or not update.effective_user:
            return
        
        chat_id = str(update.message.chat_id)
        
        # Parse command arguments
        args = context.args if context.args else []
        
        if not args:
            # No arguments - show usage
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
        
        action = args[0].lower()
        name = " ".join(args[1:]) if len(args) > 1 else None
        
        # Use the TopicTool directly
        from nanobot.agent.tools.topics import TopicTool
        tool = TopicTool()
        
        session_key = f"telegram:{chat_id}"
        
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
        
        # Send result
        if "error" in result:
            await update.message.reply_text(f"❌ {result['error']}")
        else:
            await update.message.reply_text(result.get("message", "Done"))
    
    async def _forward_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Forward slash commands to the bus for unified handling in AgentLoop."""
        if not update.message or not update.effective_user:
            return
        await self._handle_message(
            sender_id=str(update.effective_user.id),
            chat_id=str(update.message.chat_id),
            content=update.message.text,
        )
    
    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return
        
        message = update.message
        user = update.effective_user
        chat_id = message.chat_id
        
        # Detect if message is in a forum topic (thread)
        # message_thread_id is set when message is sent to a specific topic
        thread_id = message.message_thread_id
        is_topic_message = getattr(message, 'is_topic_message', False) or thread_id is not None
        
        # Use stable numeric ID, but keep username for allowlist compatibility
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"
        
        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id
        
        # Build session key with thread isolation
        # Each thread gets its own independent agent context
        str_chat_id = str(chat_id)
        if thread_id:
            # Thread-specific session: telegram:chat_id:thread_id
            session_key = f"telegram:{str_chat_id}:{thread_id}"
            logger.debug(f"Message in thread {thread_id}, using isolated session: {session_key}")
        else:
            # Main chat session: telegram:chat_id
            session_key = f"telegram:{str_chat_id}"
        
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
        
        # session_key already set above (includes thread_id if in a topic)
        str_chat_id = str(chat_id)
        
        # Start typing indicator before processing
        # Use session_key (includes thread_id) for typing indicator tracking
        self._start_typing(session_key)
        
        # Check if session is busy - if so, use existing job instead of creating new one
        # The message will be queued in the agent loop and injected mid-operation
        job_id_for_metadata = None
        if self.is_session_busy and self.is_session_busy(session_key):
            # Get the last active job for this session
            from nanobot.agent.job_tracker import job_manager
            last_job = await job_manager.get_last_job(session_key)
            if last_job:
                job_id_for_metadata = last_job.id
                logger.info(f"Session {session_key} is busy, using existing job {last_job.id}")
            else:
                logger.info(f"Session {session_key} is busy but no active job found")
        else:
            # Create job for tracking and emit hook for timeline creation
            from nanobot.agent.job_tracker import job_manager
            
            job = await job_manager.create_job(
                session_key=session_key,
                channel="telegram",
                chat_id=str_chat_id,
                user_message=content,
            )
            job_id_for_metadata = job.id
            
            # Emit hook to create initial timeline
            logger.info(f"DEBUG: About to emit agent.job.created hook for job {job.id}")
            await hook_manager.emit("agent.job.created",
                job=job,
                channel="telegram",
                chat_id=str_chat_id,
            )
            logger.info(f"DEBUG: Emitted agent.job.created hook for job {job.id}")
        
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
                "is_group": message.chat.type != "private",
                "is_topic_message": is_topic_message,
                "thread_id": thread_id,  # For routing responses to the correct thread
                "job_id": job_id_for_metadata,
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
    
    async def _typing_loop(self, chat_id: str, thread_id: int | None = None) -> None:
        """Repeatedly send 'typing' action until cancelled.
        
        Args:
            chat_id: The chat ID to send typing indicator to
            thread_id: Optional thread ID for forum topics
        """
        try:
            while self._app:
                # Note: Telegram doesn't support message_thread_id for send_chat_action yet
                # but the typing indicator will appear in the thread context
                await self._app.bot.send_chat_action(
                    chat_id=int(chat_id),
                    action=ChatAction.TYPING,
                )
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Typing indicator stopped for {chat_id}: {e}")
    
    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log polling / handler errors instead of silently swallowing them."""
        logger.error(f"Telegram error: {context.error}")

    async def _consume_timeline(self, job_id: str, message_id: int, is_intermediate: bool, chat_id: int, source: str = "") -> None:
        """Common logic after consuming a timeline message (converting to text).
        
        Removes from cache, clears job.message_id, and requests new timeline if intermediate.
        """
        # Clear job.message_id so subsequent messages create NEW messages
        await job_manager.set_message_id(job_id, None)
        logger.info(f"Cleared message_id for job {job_id} after consuming message {message_id}")
        
        # If this is an intermediate message, request a new timeline from plugin
        if is_intermediate:
            await self._request_timeline_creation(job_id, chat_id, source)
    
    async def _request_timeline_creation(self, job_id: str, chat_id: int, source: str = "") -> None:
        """Request the plugin to create a new timeline after intermediate message.
        
        This centralizes timeline creation requests to avoid race conditions.
        All timeline creation should go through the plugin via hooks.
        """
        source_str = f" ({source})" if source else ""
        logger.info(f"Requesting new timeline for job {job_id}{source_str}")
        await asyncio.sleep(0.1)
        
        # Emit the hook - the plugin (core.py) will handle timeline creation with proper locking
        try:
            await hook_manager.emit("telegram.timeline.create_request",
                job_id=job_id,
                chat_id=chat_id
            )
        except Exception as e:
            logger.error(f"Error requesting timeline creation for job {job_id}: {e}")

    async def _on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle callback queries from inline buttons."""
        if not update.callback_query:
            logger.debug("[TELEGRAM-CALLBACK] No callback_query in update")
            return
        
        query = update.callback_query
        data = query.data or ""
        
        logger.info(f"[TELEGRAM-CALLBACK] Received callback: {data[:50]}...")
        
        # Acknowledge the callback immediately to prevent timeout
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"[TELEGRAM-CALLBACK] Failed to answer callback: {e}")
        
        # Handle restart gateway confirmation
        if data.startswith("restart_gateway:"):
            parts = data.split(":")
            action = parts[1] if len(parts) > 1 else ""
            force = parts[2] == "force" if len(parts) > 2 else False
            
            if action == "confirm":
                # User confirmed restart - execute directly without agent
                await query.answer("Restarting gateway...")
                await query.edit_message_text("🔄 Restarting gateway...")
                
                try:
                    # Import here to avoid circular dependencies
                    from nanobot.agent.tools.gateway import write_restart_marker
                    import asyncio
                    
                    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
                    
                    # Write restart marker for confirmation message
                    if chat_id:
                        write_restart_marker(chat_id, "telegram", f"telegram:{chat_id}")
                    
                    # Spawn new gateway process
                    import sys
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
                await query.answer("Restart cancelled")
                await query.edit_message_text("❌ Gateway restart cancelled.")
    
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
    
    # ==================== Forum Topic (Thread) Methods ====================
    
    async def create_forum_topic(
        self,
        chat_id: int,
        name: str,
        icon_color: int | None = None,
        icon_custom_emoji_id: str | None = None,
    ) -> dict | None:
        """
        Create a new forum topic (thread) in a chat.
        
        Args:
            chat_id: The chat identifier (can be private chat with topics enabled, or supergroup)
            name: Topic title (1-128 characters)
            icon_color: Color of the topic icon (1-6 for Telegram colors)
            icon_custom_emoji_id: Custom emoji ID for the icon (requires Telegram Premium)
        
        Returns:
            dict with message_thread_id and name, or None on failure
        """
        if not self._app:
            logger.warning("Telegram bot not running")
            return None
        
        try:
            params = {
                "chat_id": chat_id,
                "name": name[:128],  # Truncate to max length
            }
            if icon_color is not None:
                params["icon_color"] = icon_color
            if icon_custom_emoji_id:
                params["icon_custom_emoji_id"] = icon_custom_emoji_id
            
            result = await self._app.bot._post(
                "createForumTopic",
                params,
                api_kwargs=params,
            )
            
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
    
    async def edit_forum_topic(
        self,
        chat_id: int,
        message_thread_id: int,
        name: str | None = None,
        icon_custom_emoji_id: str | None = None,
    ) -> bool:
        """
        Edit a forum topic's name or icon.
        
        Args:
            chat_id: The chat identifier
            message_thread_id: The thread ID to edit
            name: New topic title (optional)
            icon_custom_emoji_id: New custom emoji ID (optional)
        
        Returns:
            True on success, False on failure
        """
        if not self._app:
            return False
        
        try:
            params = {
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
            }
            if name is not None:
                params["name"] = name[:128]
            if icon_custom_emoji_id is not None:
                params["icon_custom_emoji_id"] = icon_custom_emoji_id
            
            await self._app.bot._post("editForumTopic", params, api_kwargs=params)
            
            # Update local tracking
            if message_thread_id in self._thread_info:
                if name:
                    self._thread_info[message_thread_id]["name"] = name
                if icon_custom_emoji_id is not None:
                    self._thread_info[message_thread_id]["icon_emoji_id"] = icon_custom_emoji_id
            
            return True
        except Exception as e:
            logger.error(f"Failed to edit forum topic: {e}")
            return False
    
    async def close_forum_topic(self, chat_id: int, message_thread_id: int) -> bool:
        """
        Close a forum topic (prevent new messages).
        
        Args:
            chat_id: The chat identifier
            message_thread_id: The thread ID to close
        
        Returns:
            True on success, False on failure
        """
        if not self._app:
            return False
        
        try:
            await self._app.bot._post(
                "closeForumTopic",
                {"chat_id": chat_id, "message_thread_id": message_thread_id},
            )
            return True
        except Exception as e:
            logger.error(f"Failed to close forum topic: {e}")
            return False
    
    async def reopen_forum_topic(self, chat_id: int, message_thread_id: int) -> bool:
        """
        Reopen a closed forum topic.
        
        Args:
            chat_id: The chat identifier
            message_thread_id: The thread ID to reopen
        
        Returns:
            True on success, False on failure
        """
        if not self._app:
            return False
        
        try:
            await self._app.bot._post(
                "reopenForumTopic",
                {"chat_id": chat_id, "message_thread_id": message_thread_id},
            )
            return True
        except Exception as e:
            logger.error(f"Failed to reopen forum topic: {e}")
            return False
    
    async def delete_forum_topic(self, chat_id: int, message_thread_id: int) -> bool:
        """
        Delete a forum topic and all its messages.
        
        Args:
            chat_id: The chat identifier
            message_thread_id: The thread ID to delete
        
        Returns:
            True on success, False on failure
        """
        if not self._app:
            return False
        
        try:
            await self._app.bot._post(
                "deleteForumTopic",
                {"chat_id": chat_id, "message_thread_id": message_thread_id},
            )
            # Remove from local tracking
            self._thread_info.pop(message_thread_id, None)
            # Remove session thread mapping
            for key, tid in list(self._session_threads.items()):
                if tid == message_thread_id:
                    del self._session_threads[key]
            return True
        except Exception as e:
            logger.error(f"Failed to delete forum topic: {e}")
            return False
    
    async def get_forum_topic(self, chat_id: int, message_thread_id: int) -> dict | None:
        """
        Get information about a forum topic.
        
        Uses the bot API's getForumTopicIconStickers for available icons,
        or tracks topics locally.
        
        Returns:
            Topic info dict or None
        """
        return self._thread_info.get(message_thread_id)
    
    async def get_or_create_thread_for_session(
        self,
        chat_id: int,
        session_name: str,
        session_key: str,
    ) -> int | None:
        """
        Get existing thread for a session, or create a new one.
        
        This allows automatic thread creation for different conversation contexts.
        
        Args:
            chat_id: The Telegram chat ID
            session_name: Human-readable name for the thread
            session_key: Unique session identifier (used for tracking)
        
        Returns:
            Thread ID if successful, None on failure
        """
        # Check if we already have a thread for this session
        if session_key in self._session_threads:
            return self._session_threads[session_key]
        
        # Create a new thread
        result = await self.create_forum_topic(chat_id, session_name)
        if result:
            thread_id = result["message_thread_id"]
            self._session_threads[session_key] = thread_id
            return thread_id
        
        return None
    
    def get_thread_for_session(self, session_key: str) -> int | None:
        """Get the thread ID associated with a session key, if any."""
        return self._session_threads.get(session_key)
