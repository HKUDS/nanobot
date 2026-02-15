"""nanobot/plugins/core.py - Core plugin with ephemeral timeline and view state preservation."""

import asyncio
import json
from typing import Any, Optional
from loguru import logger

from nanobot.system.hooks import hook_manager
from nanobot.agent.job_tracker import job_manager, ToolCallStatus

# Telegram imports
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class TelegramUIPlugin:
    """Plugin that adds ephemeral job tracking UI with view state preservation."""

    _VIEW_ACTIONS = {
        "expand": "expanded",
        "summary_page": "details",
        "back_summary": "details",
        "timeline": "timeline",
        "back": "details",
    }

    def __init__(self):
        # Track current timeline message per job: job_id -> (chat_id, message_id)
        self._job_timeline_message: dict[str, tuple[int, int]] = {}
        # Track view state per job: "timeline", "details", or "tool:<tool_id>"
        self._job_view_state: dict[str, str] = {}
        # Tool notification levels per chat: 0=off, 1=completions, 2=comp+args, 3=all
        self._tool_notification_level: dict[int, int] = {}
        # Track if timeline should be recreated after text
        self._job_should_recreate_timeline: dict[str, bool] = {}
        # Track if we're currently sending an intermediate message (to prevent race conditions)
        self._job_sending_intermediate: dict[str, bool] = {}
        # Track message IDs that have been consumed (converted from timeline to content)
        # Maps message_id -> job_id for debugging and cleanup
        self._consumed_message_ids: dict[int, str] = {}
        # Locks per job to prevent race conditions in timeline creation
        self._timeline_locks: dict[str, asyncio.Lock] = {}
        # Locks per job for callback handling (prevents race with _update_timeline)
        self._callback_locks: dict[str, asyncio.Lock] = {}
        # Track timeline creation in progress to prevent duplicate requests
        self._timeline_creation_in_progress: set[str] = set()

        # Register hooks
        hook_manager.register("gateway.start", self._on_gateway_start)
        hook_manager.register("telegram.init", self._on_telegram_init)
        hook_manager.register("agent.job.created", self._on_job_created)
        hook_manager.register("agent.tool.execute", self._on_tool_execute)
        hook_manager.register("agent.thinking", self._on_thinking)
        hook_manager.register("agent.response.text", self._on_response_text)
        hook_manager.register("agent.timeline.update", self._on_timeline_update)
        hook_manager.register("telegram.timeline.created", self._on_timeline_created)
        hook_manager.register("telegram.timeline.consumed", self._on_timeline_consumed)
        hook_manager.register("telegram.timeline.create_request", self._on_timeline_create_request)
        hook_manager.register("telegram.timeline.get_view_state", self._on_get_view_state)
        hook_manager.register("telegram.timeline.get_expanded_keyboard", self._on_get_expanded_keyboard)

        logger.info("TelegramUIPlugin registered")

    async def _on_gateway_start(self, agent, config=None, **kwargs):
        """Store agent reference and config when gateway starts."""
        self._agent = agent
        self._config = config
        
    # ========== DRY Helper Methods ==========
    
    def _get_config_timeline_emoji(self) -> Optional[str]:
        """Get timeline emoji from config, returns None if not configured."""
        if hasattr(self, '_config') and self._config and hasattr(self._config, 'ui'):
            return self._config.ui.timeline_emoji
        return None
    
    def _get_timeline_emoji(self) -> str:
        """Get the configured timeline emoji (returns empty string if disabled)."""
        emoji = self._get_config_timeline_emoji()
        # Handle null, empty string, or "none" as disabled
        if emoji is None or emoji == "" or str(emoji).lower() == "none":
            return ""
        return emoji
    
    def _is_timeline_disabled(self) -> bool:
        """Check if timeline is completely disabled."""
        return self._get_config_timeline_emoji() is None
    
    def _escape_markdown(self, text: str) -> str:
        """Escape special Markdown characters for Telegram."""
        return (str(text)
            .replace("`", "'")
            .replace("*", "")
            .replace("_", "")
            .replace("[", "")
            .replace("]", "")
            .replace("|", "∣"))
    
    def _create_timeline_keyboard(self, job_id: str, job) -> list:
        """Create standard timeline keyboard with View Details and Abort buttons."""
        keyboard_row = [
            InlineKeyboardButton("🔍 View Details", callback_data=f"job_progress:{job_id}"),
        ]
        if job.status == "running":
            keyboard_row.append(
                InlineKeyboardButton("🛑 Abort", callback_data=f"job:abort:{job_id}")
            )
        return [keyboard_row]

    def _render_view(self, job, view_state: str) -> tuple[str, list]:
        """Return (text, keyboard) for a given view state."""
        if view_state.startswith("details"):
            try:
                page = int(view_state.split(":", 1)[1])
            except (IndexError, ValueError):
                page = 0
            return self._format_summary_message(job, page=page), self._create_summary_keyboard(job, page=page)
        elif view_state.startswith("expanded"):
            try:
                page = int(view_state.split(":", 1)[1])
            except (IndexError, ValueError):
                page = 0
            return self._format_expanded_message(job, page=page), self._create_expanded_keyboard(job, page=page)
        elif view_state.startswith("tool:"):
            try:
                tool_idx = int(view_state.split(":", 1)[1])
            except (IndexError, ValueError):
                tool_idx = 0
            result = self._format_tool_detail_view(job, tool_idx)
            if result:
                return result
            # Tool index out of range (e.g. job restarted), fall back to timeline
            return job.get_timeline_emoji(20), self._create_timeline_keyboard(job.id, job)
        else:
            return job.get_timeline_emoji(20), self._create_timeline_keyboard(job.id, job)

    def _add_common_footer_buttons(self, keyboard: list, job, extra_buttons: list | None = None) -> None:
        """Add common footer buttons to a keyboard.

        View Response gets its own row (if completed).
        extra_buttons, Back to Timeline, and Abort share one row.
        """
        if job.status == "completed":
            keyboard.append([InlineKeyboardButton("📄 View Full Response", callback_data=f"job:response:{job.id}")])
        nav_row = list(extra_buttons) if extra_buttons else []
        nav_row.append(InlineKeyboardButton("⏹️ Timeline", callback_data=f"job:timeline:{job.id}"))
        if job.status == "running":
            nav_row.append(InlineKeyboardButton("🛑 Abort", callback_data=f"job:abort:{job.id}"))
        keyboard.append(nav_row)

    def _cleanup_job_state(self, job_id: str) -> None:
        """Remove all tracking state for a job."""
        self._job_view_state.pop(job_id, None)
        self._job_timeline_message.pop(job_id, None)
        self._job_should_recreate_timeline.pop(job_id, None)
        self._job_sending_intermediate.pop(job_id, None)
        self._timeline_locks.pop(job_id, None)
        self._callback_locks.pop(job_id, None)
        self._cleanup_consumed_message(job_id)
        self._timeline_creation_in_progress.discard(job_id)

    def _check_permission(self, update) -> bool:
        """Check if the user is allowed to use commands based on allowlist."""
        if not update.effective_user:
            return False
        
        user = update.effective_user
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"
        
        return self._channel.is_allowed(sender_id)
    
    async def _send_permission_denied(self, update):
        """Send permission denied message to user."""
        if update.message:
            await update.message.reply_text(
                "⛔ Access denied. You are not authorized to use this bot."
            )
    
    async def _on_telegram_init(self, app, channel, **kwargs):
        """Initialize Telegram handlers when bot starts."""
        from telegram.ext import CommandHandler, CallbackQueryHandler
        from telegram import BotCommand

        self._channel = channel

        # Dynamically register agent tools as commands
        if hasattr(self, "_agent"):
            tools = self._agent.tools.get_definitions()
            for tool_def in tools:
                name = tool_def.get("function", {}).get("name")
                description = tool_def.get("function", {}).get("description", "")[:100]
                if name:
                    # Add to channel's bot commands so they appear in the menu
                    channel.BOT_COMMANDS.append(BotCommand(name, description))
                    # Register a handler for direct tool execution
                    async def tool_command_handler(update, context, tool_name=name):
                        # Check permission first
                        if not self._check_permission(update):
                            await self._send_permission_denied(update)
                            return
                        
                        # Start typing indicator
                        str_chat_id = str(update.effective_chat.id)
                        self._channel._start_typing(str_chat_id)
                        
                        # Parse arguments (e.g. /tool arg1=val1 arg2=val2)
                        args = {}
                        if context.args:
                            for arg in context.args:
                                if "=" in arg:
                                    k, v = arg.split("=", 1)
                                    args[k] = v
                                else:
                                    # Fallback for tools that take a single string
                                    if tool_name in ["web_search", "google_search"]:
                                        args["query"] = " ".join(context.args)
                                        break
                                    elif tool_name == "ipython":
                                        args["code"] = " ".join(context.args)
                                        break
                                    elif tool_name == "exec":
                                        args["command"] = " ".join(context.args)
                                        break
                        
                        # Special handling for restart_gateway from Telegram - auto-confirm
                        # Note: chat_id and channel are passed as kwargs to execute_tool_directly, not in args
                        if tool_name == "restart_gateway":
                            args["confirmed"] = True
                            # Generate session_key so restart notification can be injected into conversation
                            session_key = f"telegram:{str_chat_id}"
                            args["session_key"] = session_key
                        
                        # Execute tool directly (no Job created)
                        result = await self._agent.execute_tool_directly(
                            tool_name=tool_name,
                            arguments=args,
                            channel="telegram",
                            chat_id=str_chat_id,
                            job_id=None
                        )
                        
                        # Send result wrapped in a code block for tool calls
                        from nanobot.bus.events import OutboundMessage
                        result_str = str(result) if result else "No output"
                        if len(result_str) > 3900:
                            result_str = result_str[:3900] + "\n... (truncated)"
                        wrapped_result = f"```\n{result_str}\n```"
                        await self._channel.send(OutboundMessage(
                            channel="telegram",
                            chat_id=str_chat_id,
                            content=wrapped_result
                        ))
                    
                    app.add_handler(CommandHandler(name, tool_command_handler))


        # Add command handlers
        app.add_handler(CommandHandler("lastjob", self._on_lastjob_command))
        app.add_handler(CommandHandler("jobs", self._on_jobs_command))
        app.add_handler(CommandHandler("abort", self._on_abort_command))
        app.add_handler(CommandHandler("toggle_tool_calls", self._on_toggle_tool_calls))
        # Add callback handler with pattern to only handle job-related callbacks
        # (restart_gateway: callbacks are handled by telegram.py)
        app.add_handler(CallbackQueryHandler(self._on_callback_query, pattern="^(job_progress|job:|lastjob:|tool_notif:)"))

        logger.info("Telegram UI handlers registered")

    def _get_timeline_lock(self, job_id: str) -> asyncio.Lock:
        """Get or create a lock for timeline operations on a specific job."""
        if job_id not in self._timeline_locks:
            self._timeline_locks[job_id] = asyncio.Lock()
        return self._timeline_locks[job_id]

    def _get_callback_lock(self, job_id: str) -> asyncio.Lock:
        """Get or create a lock for callback operations on a specific job."""
        if job_id not in self._callback_locks:
            self._callback_locks[job_id] = asyncio.Lock()
        return self._callback_locks[job_id]

    def _cleanup_consumed_message(self, job_id: str):
        """Remove consumed message tracking for a completed job."""
        # Find and remove any consumed message for this job
        to_remove = [msg_id for msg_id, jid in self._consumed_message_ids.items() if jid == job_id]
        for msg_id in to_remove:
            del self._consumed_message_ids[msg_id]
            logger.debug(f"Cleaned up consumed message {msg_id} for completed job {job_id}")

    async def _on_job_created(self, job, channel, chat_id, **kwargs):
        """Create initial timeline when job starts."""
        # Skip if timeline is completely disabled
        if self._is_timeline_disabled():
            logger.debug(f"Timeline disabled, skipping creation for job {job.id}")
            return
            
        logger.info(f"[TIMELINE-TRACE] _on_job_created START: job={job.id}, channel={channel}, chat_id={chat_id}, existing_msg={job.message_id}")
        if channel != "telegram":
            logger.debug(f"Ignoring job created for channel {channel}")
            return

        # Use lock to prevent race conditions
        lock = self._get_timeline_lock(job.id)
        async with lock:
            # Double-check after acquiring lock
            if job.id in self._job_timeline_message:
                logger.debug(f"Timeline already exists for job {job.id}, skipping creation")
                return

            try:
                chat_id_int = int(chat_id)
                logger.warning(f"[TIMELINE-CREATE] Initial timeline for job {job.id} in chat {chat_id_int} - existing={job.id in self._job_timeline_message}")
                # Create initial timeline based on current view state (defaults to timeline)
                view_state = self._job_view_state.get(job.id, "timeline")
                message_id = await self._create_timeline_message(
                    chat_id_int, job, view_state
                )
                logger.info(f"[TIMELINE-CACHE-SET] Initial: job={job.id}, message_id={message_id}, cache_size={len(self._job_timeline_message)}")
                self._job_timeline_message[job.id] = (chat_id_int, message_id)
                self._job_should_recreate_timeline[job.id] = True
                
                # Update job record with message_id so channel can find it for editing
                await job_manager.set_message_id(job.id, str(message_id))
                logger.info(f"[TIMELINE-CACHE-CONFIRM] Initial: job={job.id} in cache={job.id in self._job_timeline_message}")
                logger.info(f"Successfully created initial timeline for job {job.id} with message_id {message_id}")
                
            except Exception as e:
                logger.error(f"Error creating initial timeline for job {job.id}: {e}")
                import traceback
                logger.error(traceback.format_exc())

    async def _on_tool_execute(self, tool_name, tool_args, channel, chat_id, job_id, status, tool_id=None, result=None, **kwargs):
        """Update timeline as tools execute."""
        logger.info(f"DEBUG _on_tool_execute: {tool_name} {status} job={job_id}")
        if channel != "telegram":
            logger.debug(f"Ignoring tool execute for channel {channel}")
            return

        try:
            chat_id_int = int(chat_id)

            # Check notification level
            level = self._tool_notification_level.get(chat_id_int, 0)

            if status == "start":
                if job_id:
                    job = await job_manager.get_job(job_id)
                    if job:
                        # Check if tool call already exists (added by AgentLoop)
                        exists = any(tc.id == tool_id for tc in job.tool_calls) if tool_id else False
                        if not exists:
                            # Add tool call to job record for timeline
                            await job_manager.job_add_tool_call(job_id, tool_name, tool_args, tool_id=tool_id)
                        
                        if tool_id:
                            await job_manager.job_update_tool_call(job_id, tool_id, ToolCallStatus.RUNNING)
                    
                    await self._update_timeline(job_id, chat_id_int)
                
                if level >= 2:
                    await self._send_tool_notification(chat_id_int, tool_name, tool_args, "start")

            elif status == "end":
                if job_id:
                    job = await job_manager.get_job(job_id)
                    if job and tool_id:
                        await job_manager.job_update_tool_call(job_id, tool_id, ToolCallStatus.SUCCESS, result=str(result))

                    # Check if this is the message tool (agent sending text to user)
                    if tool_name == "message" and isinstance(tool_args, dict) and "content" in tool_args:
                        # Replace timeline with the message content
                        await self._replace_timeline_with_text(
                            job_id, chat_id_int, tool_args["content"], is_final=False
                        )
                    else:
                        await self._update_timeline(job_id, chat_id_int)
                
                if level >= 1:
                    await self._send_tool_notification(chat_id_int, tool_name, result, "end")

        except AssertionError:
            raise  # Don't catch assertions - let them crash
        except Exception as e:
            import traceback
            logger.error(f"Error in tool execute hook: {e}")
            logger.error(traceback.format_exc())

    async def _on_thinking(self, channel, chat_id, content, job_id, **kwargs):
        """Handle thinking/reasoning content from LLM."""
        if channel != "telegram":
            return
        try:
            chat_id_int = int(chat_id)
            if job_id:
                job = await job_manager.get_job(job_id)
                if job:
                    thinking_record = await job_manager.job_add_tool_call(job_id, "🧠 thinking", {})
                    if thinking_record:
                        thinking_record.status = ToolCallStatus.THINKING
                        thinking_record.result = content
                await self._update_timeline(job_id, chat_id_int)
        except AssertionError:
            raise
        except Exception as e:
            logger.error(f"Error in thinking hook: {e}")

    async def _on_timeline_created(self, job_id, chat_id, message_id, **kwargs):
        """Update cache when a new timeline is created after intermediate message."""
        logger.info(f"DEBUG _on_timeline_created: job={job_id}, message_id={message_id}")
        try:
            chat_id_int = int(chat_id)
            
            # ASSERT: New message should not be consumed
            assert message_id not in self._consumed_message_ids, \
                f"CRITICAL BUG: New timeline message {message_id} for job {job_id} " \
                f"is already consumed by job {self._consumed_message_ids.get(message_id)}!"
            
            logger.info(f"[TIMELINE-CACHE-SET] Created: job={job_id}, message_id={message_id}, existing={job_id in self._job_timeline_message}")
            self._job_timeline_message[job_id] = (chat_id_int, message_id)
            # Don't set _job_should_recreate_timeline to True - we have a valid timeline
            self._job_should_recreate_timeline[job_id] = False
            # Clear the sending intermediate flag since new timeline is now ready
            self._job_sending_intermediate[job_id] = False
            logger.info(f"[TIMELINE-CACHE-CONFIRM] Created: job={job_id}, message_id={message_id}")
        except Exception as e:
            logger.error(f"Error updating timeline cache: {e}")

    async def _on_timeline_consumed(self, job_id, message_id, **kwargs):
        """Mark a timeline message as consumed (converted to content)."""
        logger.info(f"DEBUG _on_timeline_consumed: job={job_id}, message_id={message_id}")
        try:
            # ASSERT: Message should not already be consumed
            assert message_id not in self._consumed_message_ids, \
                f"CRITICAL BUG: Message {message_id} for job {job_id} was already consumed by job {self._consumed_message_ids.get(message_id)}! " \
                f"Double-consumption detected."
            
            # ASSERT: If job is in timeline cache, message_id must match
            if job_id in self._job_timeline_message:
                cached_msg_id = self._job_timeline_message[job_id][1]
                assert cached_msg_id == message_id, \
                    f"CRITICAL BUG: Timeline cache mismatch for job {job_id}. " \
                    f"Cached: {cached_msg_id}, Consuming: {message_id}"
            
            self._consumed_message_ids[message_id] = job_id
            # Also clear from timeline tracking
            if job_id in self._job_timeline_message:
                cached_msg_id = self._job_timeline_message[job_id][1]
                logger.info(f"[TIMELINE-CACHE-DEL] Consumed: job={job_id}, message_id={cached_msg_id}, consumed_msg={message_id}, match={cached_msg_id == message_id}")
                del self._job_timeline_message[job_id]
            # Clean up locks to prevent memory leak
            if job_id in self._timeline_locks:
                del self._timeline_locks[job_id]
            if job_id in self._callback_locks:
                del self._callback_locks[job_id]
            logger.info(f"Message {message_id} marked as consumed for job {job_id}")
        except Exception as e:
            logger.error(f"Error marking timeline as consumed: {e}")

    async def _on_timeline_create_request(self, job_id, chat_id, **kwargs):
        """Handle request to create a new timeline (e.g., after intermediate message)."""
        logger.info(f"DEBUG _on_timeline_create_request: job={job_id}, chat_id={chat_id}")
        
        # Skip if timeline is completely disabled
        if self._is_timeline_disabled():
            logger.debug(f"Timeline disabled, skipping creation for job {job_id}")
            return
        
        # Check if creation is already in progress (prevent duplicate requests)
        if job_id in self._timeline_creation_in_progress:
            logger.debug(f"Timeline creation already in progress for job {job_id}, skipping duplicate request")
            return
        
        # Check if timeline already exists
        if job_id in self._job_timeline_message:
            logger.debug(f"Timeline already exists for job {job_id}, skipping creation")
            return
        
        # Mark creation as in progress
        self._timeline_creation_in_progress.add(job_id)

        try:
            # Use lock to prevent race conditions
            lock = self._get_timeline_lock(job_id)
            async with lock:
                # Double-check after acquiring lock
                if job_id in self._job_timeline_message:
                    logger.debug(f"Timeline already exists for job {job_id} (after lock), skipping creation")
                    return

                chat_id_int = int(chat_id)
                job = await job_manager.get_job(job_id)
                if not job:
                    logger.warning(f"No job found for {job_id}, cannot create timeline")
                    return
                
                # ASSERT: If job has message_id, it should NOT be in consumed set
                # (if it is, we shouldn't be creating a new timeline)
                if job.message_id:
                    job_msg_id = int(job.message_id)
                    assert job_msg_id not in self._consumed_message_ids, \
                        f"CRITICAL BUG: Creating timeline for job {job_id} but message {job_msg_id} " \
                        f"was already consumed by job {self._consumed_message_ids.get(job_msg_id)}. " \
                        f"job.message_id was not cleared after consumption!"

                # Get current view state (defaults to timeline)
                view_state = self._job_view_state.get(job_id, "timeline")

                # Create the timeline message
                logger.warning(f"[TIMELINE-CREATE] Recreation for job {job_id} in chat {chat_id_int} - existing={job_id in self._job_timeline_message}, in_progress={job_id in self._timeline_creation_in_progress}")
                message_id = await self._create_timeline_message(chat_id_int, job, view_state)
                
                # ASSERT: New message_id should not be consumed
                assert message_id not in self._consumed_message_ids, \
                    f"CRITICAL BUG: Created timeline message {message_id} for job {job_id} " \
                    f"but this message_id is already in consumed set!"
                
                logger.info(f"[TIMELINE-CACHE-SET] Recreated: job={job_id}, message_id={message_id}, existing={job_id in self._job_timeline_message}")
                self._job_timeline_message[job_id] = (chat_id_int, message_id)
                self._job_should_recreate_timeline[job_id] = False
                # Clear intermediate flag now that timeline is recreated
                self._job_sending_intermediate[job_id] = False

                # Update job record with message_id
                await job_manager.set_message_id(job_id, str(message_id))
                logger.info(f"[TIMELINE-CACHE-CONFIRM] Recreated: job={job_id}, message_id={message_id}, in_cache={job_id in self._job_timeline_message}")

        except Exception as e:
            logger.error(f"Error creating timeline for job {job_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Always clean up the in-progress flag
            self._timeline_creation_in_progress.discard(job_id)

    async def _on_get_view_state(self, job_id, **kwargs):
        """Return current view state for a job."""
        view_state = self._job_view_state.get(job_id, "timeline")
        logger.info(f"DEBUG _on_get_view_state: job={job_id}, view_state={view_state}")
        return view_state

    async def _on_get_expanded_keyboard(self, job_id, chat_id, page=0, **kwargs):
        """Return expanded keyboard for a job."""
        logger.info(f"DEBUG _on_get_expanded_keyboard: job={job_id}, chat_id={chat_id}, page={page}")
        try:
            job = await job_manager.get_job(job_id)
            if not job:
                return None
            keyboard = self._create_expanded_keyboard(job, page=page)
            return keyboard
        except Exception as e:
            logger.error(f"Error creating expanded keyboard: {e}")
            return None

    async def _on_response_text(self, channel, chat_id, content, is_final, job_id=None, **kwargs):
        """Clean up timeline when response text is received."""
        if channel != "telegram" or not job_id:
            return

        try:
            if is_final:
                # Clear tracking, let the channel handle the final message via the bus
                self._cleanup_job_state(job_id)
            else:
                # For intermediate text, just set flag to prevent race conditions
                # DON'T edit here - the channel will handle it via the bus
                
                # ASSERT: Should not already be sending intermediate
                assert not self._job_sending_intermediate.get(job_id, False), \
                    f"CRITICAL BUG: _on_response_text(is_final=False) for job {job_id} " \
                    f"but _job_sending_intermediate already True! Double intermediate message!"
                
                logger.info(f"Setting intermediate message flag for job {job_id}")
                self._job_sending_intermediate[job_id] = True
        except Exception as e:
            logger.error(f"Error in _on_response_text: {e}")

    async def _on_timeline_update(self, job_id, channel, chat_id, **kwargs):
        """Handle explicit timeline update request (e.g., when LLM request starts/ends)."""
        if channel != "telegram" or not job_id:
            return
        try:
            chat_id_int = int(chat_id)
            await self._update_timeline(job_id, chat_id_int)
            logger.debug(f"Timeline updated for job {job_id} on explicit request")
        except AssertionError:
            raise  # Don't catch assertions - let them crash
        except Exception as e:
            logger.error(f"Error in _on_timeline_update: {e}")

    async def _replace_timeline_with_text(self, job_id: str, chat_id: int, content: str, is_final: bool):
        """Replace timeline message with text, then recreate timeline if not final."""
        if not job_id:
            return
        
        logger.info(f"DEBUG _replace_timeline_with_text: job_id={job_id}, chat_id={chat_id}, is_final={is_final}")
        
        # NOTE: _job_sending_intermediate is set by _on_response_text BEFORE this is called.
        # This is intentional - the flag prevents _update_timeline from racing with us.
        # We don't assert on the flag here because it's EXPECTED to be True for intermediate messages.
        
        try:
            if job_id not in self._job_timeline_message:
                # No timeline to replace, just send message
                await self._channel._app.bot.send_message(
                    chat_id=chat_id,
                    text=content,
                    parse_mode="Markdown",
                )
                return

            stored_chat_id, message_id = self._job_timeline_message[job_id]
            
            # ASSERT: Message should not be consumed already
            assert message_id not in self._consumed_message_ids, \
                f"CRITICAL BUG: Attempting to replace timeline with text for job {job_id}, " \
                f"but message {message_id} is already consumed by job {self._consumed_message_ids.get(message_id)}!"
            
            # Replace timeline with text
            # CRITICAL: Remove reply_markup to clear inline keyboard buttons
            await self._channel._app.bot.edit_message_text(
                chat_id=stored_chat_id,
                message_id=message_id,
                text=content,
                parse_mode="Markdown",
                reply_markup=None,  # Remove inline keyboard to prevent stale button clicks
            )

            if is_final:
                # Only clean the 4 fields the original code cleaned here;
                # _cleanup_job_state would over-clean (intermediate, callback locks, etc.)
                self._job_view_state.pop(job_id, None)
                self._job_timeline_message.pop(job_id, None)
                self._job_should_recreate_timeline.pop(job_id, None)
                self._timeline_locks.pop(job_id, None)
            else:
                # Mark for timeline recreation on next tool execution
                self._job_should_recreate_timeline[job_id] = True
                # Remove from timeline tracking since we just replaced it
                if job_id in self._job_timeline_message:
                    cached_msg_id = self._job_timeline_message[job_id][1]
                    logger.info(f"[TIMELINE-CACHE-DEL] Intermediate: job={job_id}, message_id={cached_msg_id}")
                    del self._job_timeline_message[job_id]

        except Exception as e:
            logger.error(f"Error replacing timeline with text: {e}")
            # Fallback: send as new message
            try:
                await self._channel._app.bot.send_message(
                    chat_id=chat_id,
                    text=content,
                    parse_mode="Markdown",
                )
            except Exception as e2:
                logger.error(f"Fallback also failed: {e2}")

    async def _create_timeline_message(self, chat_id: int, job, view_state: str) -> int:
        """Create a timeline message respecting the current view state."""
        import asyncio

        text, keyboard = self._render_view(job, view_state)

        # Retry logic for Telegram API timeouts
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempting to create timeline for job {job.id} (attempt {attempt + 1}/{max_retries})")
                msg = await self._channel._app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown",
                )
                logger.info(f"Successfully created timeline for job {job.id} with message_id {msg.message_id}")
                return msg.message_id
            except Exception as e:
                logger.warning(f"Failed to create timeline for job {job.id} on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Failed to create timeline for job {job.id} after {max_retries} attempts")
                    raise

    async def _update_timeline(self, job_id: str, chat_id: int):
        """Update existing timeline respecting view state."""
        start_time = asyncio.get_event_loop().time()
        
        # Skip if timeline is completely disabled
        if self._is_timeline_disabled():
            logger.debug(f"Timeline disabled, skipping update for job {job_id}")
            return
        
        # Skip if channel not initialized yet
        if not hasattr(self, '_channel') or self._channel is None:
            logger.debug(f"Channel not initialized yet, skipping timeline update for job {job_id}")
            return
        
        # Log FULL state at start
        logger.info(f"[TIMELINE-EDIT-START] job={job_id}, chat_id={chat_id}")
        logger.info(f"[TIMELINE-STATE] job_in_cache={job_id in self._job_timeline_message}, "
                    f"consumed_msgs={list(self._consumed_message_ids.keys())}, "
                    f"sending_intermediate={self._job_sending_intermediate.get(job_id)}, "
                    f"should_recreate={self._job_should_recreate_timeline.get(job_id)}")
        
        # ASSERT: Never update timeline while intermediate message is being sent
        # This prevents race conditions where we overwrite a message being converted to text
        if self._job_sending_intermediate.get(job_id, False):
            logger.info(f"Timeline update for job {job_id} - intermediate message in progress, SKIPPING to prevent race condition")
            return  # MUST return - otherwise we'll overwrite the intermediate text with a timeline!
        
        # Always check if we have a valid timeline via the job
        job = await job_manager.get_job(job_id)
        if not job:
            logger.warning(f"No job found for {job_id}")
            return
        
        # CRITICAL: Don't update timeline if job is completed - final message should be shown
        if job.completed_at:
            logger.info(f"[TIMELINE-COMPLETED] Job {job_id} completed at {job.completed_at}, skipping timeline update")
            return
            
        if job.message_id:
            message_id = int(job.message_id)
            
            # ASSERT: Never edit a message that was already converted to intermediate text
            assert message_id not in self._consumed_message_ids, \
                f"CRITICAL BUG: Attempted to edit consumed message {message_id} for job {job_id}. " \
                f"This message was already consumed by job {self._consumed_message_ids.get(message_id)} and should not be edited back to timeline!"
            
            # ASSERT: Job must be in timeline cache to edit it
            if job_id not in self._job_timeline_message:
                # Job has message_id but not in cache - this can happen when:
                # 1. Job was loaded from persistence after restart (cache is in-memory only)
                # 2. Timeline was consumed but job.message_id wasn't cleared
                # 3. Race condition
                # Log the full state for debugging
                consumed_list = [f"{mid}:{jid}" for mid, jid in self._consumed_message_ids.items() if jid == job_id]
                cache_keys = list(self._job_timeline_message.keys())
                logger.error(f"[TIMELINE-CACHE-MISS] Update failed: job={job_id}, message_id={message_id}, "
                            f"consumed_for_job={consumed_list}, cache_jobs={cache_keys}, "
                            f"should_recreate={self._job_should_recreate_timeline.get(job_id)}, "
                            f"sending_intermediate={self._job_sending_intermediate.get(job_id)}")
                # RE-ADD TO CACHE: If job has valid message_id and is not consumed, 
                # re-add it to cache (happens after gateway restart)
                if message_id not in self._consumed_message_ids:
                    logger.info(f"[TIMELINE-CACHE-READD] Re-adding job {job_id} with message {message_id} to cache after restart")
                    self._job_timeline_message[job_id] = (chat_id, message_id)
                    # Continue with update instead of returning
                else:
                    # Message was consumed, clear it
                    logger.warning(f"Job {job_id} has message_id {message_id} but not in timeline cache. "
                                  f"Clearing stale message_id. This is normal after gateway restart.")
                    await job_manager.set_message_id(job_id, None)
                    return
            
            # ASSERT: Cached message_id must match job.message_id
            cached_msg_id = self._job_timeline_message[job_id][1]
            if cached_msg_id != message_id:
                logger.error(f"Timeline cache mismatch for job {job_id}. "
                            f"Cached: {cached_msg_id}, Job: {message_id}. "
                            f"Clearing stale message_id.")
                await job_manager.set_message_id(job_id, None)
                return
            
            # We have a timeline, update our cache
            self._job_timeline_message[job_id] = (chat_id, message_id)
            logger.info(f"DEBUG _update_timeline: Using message_id {message_id} from job")
        elif job_id not in self._job_timeline_message:
            # No timeline exists at all - don't recreate, just return
            logger.warning(f"No timeline exists for job {job_id}, skipping update")
            return

        try:
            view_state = self._job_view_state.get(job_id, "timeline")
            text, keyboard = self._render_view(job, view_state)

            # FINAL CHECK: Ensure message wasn't consumed during preparation
            # This prevents race conditions where message is consumed between check and edit
            if message_id in self._consumed_message_ids:
                logger.error(f"[TIMELINE-RACE-EDIT] Message {message_id} was consumed during preparation, ABORTING edit for job {job_id}")
                return
            
            logger.info(f"DEBUG _update_timeline: Editing message {message_id} for job {job_id} with view_state={view_state}")
            await self._channel._app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            logger.info(f"DEBUG _update_timeline: Successfully edited message {message_id}")
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                logger.error(f"Could not update timeline: {e}")

    def _build_details_text(self, job) -> str:
        """Build details view text."""
        # Always show timeline at top like in 88f647e
        lines = [f"{job.get_timeline_emoji(10)}", ""]
        
        safe_message = self._escape_markdown(job.user_message[:50])
        timeline_emoji = self._get_timeline_emoji()
        lines.extend([
            f"{timeline_emoji} **Job Details**",
            f"ID: `{job.id}`",
            f"Status: {'✅ Complete' if job.completed_at else '⏳ Running'}",
            f"Message: {safe_message}...",
            "",
            f"{timeline_emoji} Tools: {len(job.tool_calls)}",
            f"⏱️ Duration: {job.duration_seconds:.1f}s",
        ])

        if job.tool_calls:
            lines.append("\n**Tool Calls:**")
            for tc in job.tool_calls[:5]:
                emoji = tc.to_emoji()
                lines.append(f"{emoji} `{tc.name}` - {tc.status.value}")

        return "\n".join(lines)

    async def _send_tool_notification(self, chat_id: int, tool_name: str, content: Any, status: str):
        """Send tool execution notification."""
        try:
            if status == "start":
                text = f"🔧 **Executing:** `{tool_name}`\n```json\n{json.dumps(content, indent=2)[:100]}\n```"
            else:
                text = f"✅ **Completed:** `{tool_name}`\n```\n{str(content)[:200]}\n```"

            await self._channel._app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Error sending tool notification: {e}")

    async def _on_callback_query(self, update, context):
        """Handle button callbacks."""
        logger.info(f"[PLUGIN-CALLBACK] Handler entered")
        
        if not update.callback_query:
            logger.warning("[PLUGIN-CALLBACK] No callback_query in update")
            return

        # Check permission for callback queries
        if not self._check_permission(update):
            logger.warning("[PLUGIN-CALLBACK] Access denied")
            await update.callback_query.answer("⛔ Access denied", show_alert=True)
            return

        query = update.callback_query
        data = query.data
        message_id = query.message.message_id if query.message else None
        logger.info(f"[PLUGIN-CALLBACK] Callback received: {data} on message_id={message_id}")

        lock_acquired = False
        lock = None
        try:
            # Extract job_id from callback data for assertions
            callback_job_id = None
            if data.startswith("job_progress:"):
                callback_job_id = data.split(":", 1)[1]
            elif data.startswith("job:"):
                parts = data.split(":")
                if len(parts) >= 3:
                    callback_job_id = parts[2]
            
            # ASSERT: If we have a job_id and message_id, verify they match our expectations
            # COMMENTED OUT: These assertions crash on edge cases (stale callbacks, race conditions)
            # Instead we log warnings and handle gracefully
            if callback_job_id and message_id:
                # Check if intermediate message is being sent (race condition)
                # BUT allow job_progress (View Details) to work even during intermediate updates
                if self._job_sending_intermediate.get(callback_job_id, False) and not data.startswith("job_progress:"):
                    logger.warning(f"[CALLBACK-BLOCKED] Intermediate in progress: msg={message_id}, job={callback_job_id}")
                    await query.answer("⚠️ Message busy (intermediate update in progress)", show_alert=True)
                    return
                
                # Check if message was consumed - if so, redirect to current timeline
                if message_id in self._consumed_message_ids:
                    logger.info(f"[CALLBACK-REDIRECT] Message {message_id} consumed, checking for current timeline for job {callback_job_id}")
                    if callback_job_id in self._job_timeline_message:
                        # Redirect to current timeline message
                        current_chat_id, current_message_id = self._job_timeline_message[callback_job_id]
                        logger.info(f"[CALLBACK-REDIRECT] Redirecting from consumed msg {message_id} to current msg {current_message_id} for job {callback_job_id}")
                        # Update query to use current message
                        message_id = current_message_id
                        # Continue processing with current message
                    else:
                        # Check if job is completed
                        job = await job_manager.get_job(callback_job_id)
                        if job and job.completed_at:
                            logger.info(f"[CALLBACK-REDIRECT] Job {callback_job_id} completed, cannot redirect from consumed message {message_id}")
                            await query.answer("✅ Job completed. Start a new conversation.", show_alert=True)
                        else:
                            logger.warning(f"[CALLBACK-REDIRECT] No current timeline for job {callback_job_id}, cannot redirect from consumed message {message_id}")
                            await query.answer("⚠️ Timeline has been updated. Please use the current message.", show_alert=True)
                        return
                
                # Check if job is in timeline cache (it should be for timeline callbacks)
                if callback_job_id in self._job_timeline_message:
                    cached_chat_id, cached_message_id = self._job_timeline_message[callback_job_id]
                    if cached_message_id != message_id:
                        # For job_progress callbacks, this means stale state
                        if data.startswith("job_progress:"):
                            logger.warning(f"[CALLBACK-BLOCKED] Stale message: clicked_msg={message_id}, cached_msg={cached_message_id}, job={callback_job_id}")
                            await query.answer(f"⚠️ Timeline updated (old message #{message_id}, current is #{cached_message_id})", show_alert=True)
                            return
                        logger.warning(f"Callback message_id {message_id} doesn't match cached {cached_message_id} for job {callback_job_id}")
                elif data.startswith("job_progress:"):
                    # job_progress should only be on active timeline messages
                    cache_jobs = list(self._job_timeline_message.keys())
                    logger.warning(f"[CALLBACK-BLOCKED] Job not in cache: msg={message_id}, job={callback_job_id}, cache_jobs={cache_jobs}")
                    await query.answer(f"⚠️ Timeline not tracked (job {callback_job_id[:8]}... not in cache)", show_alert=True)
                    return
            
            # Use callback lock to prevent race with _update_timeline for this job
            lock_start = asyncio.get_event_loop().time()
            if callback_job_id:
                lock = self._get_callback_lock(callback_job_id)
                # Actually acquire the lock to prevent races
                # Use a timeout to avoid blocking indefinitely
                try:
                    await asyncio.wait_for(lock.acquire(), timeout=2.0)
                    lock_acquired = True
                    lock_wait_time = asyncio.get_event_loop().time() - lock_start
                    if lock_wait_time > 0.5:
                        logger.warning(f"[PERF] Slow lock acquisition: {lock_wait_time:.2f}s for job {callback_job_id}")
                except asyncio.TimeoutError:
                    logger.warning(f"Callback lock timeout for job {callback_job_id}, proceeding anyway")
            logger.info(f"About to answer query for {data}")
            await query.answer()
            logger.info(f"Query answered for {data}")
            
            if data.startswith("job_progress:"):
                job_id = data.split(":", 1)[1]
                logger.info(f"Handling job_progress for {job_id}")
                await self._handle_view_toggle(query, job_id)
                logger.info(f"Handled job_progress for {job_id}")

            elif data.startswith("job:"):
                # Handle all job-related callbacks
                parts = data.split(":")
                action = parts[1]
                job_id = parts[2]
                
                job = await job_manager.get_job(job_id)
                if not job:
                    await query.answer("Job not found")
                    return

                if action in self._VIEW_ACTIONS:
                    try:
                        page_num = int(parts[3]) if len(parts) > 3 else 0
                    except (IndexError, ValueError):
                        page_num = 0
                    view = self._VIEW_ACTIONS[action]
                    state = view if view == "timeline" else f"{view}:{page_num}"
                    self._job_view_state[job_id] = state
                    text, keyboard = self._render_view(job, state)
                    await query.edit_message_text(
                        text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown",
                    )

                elif action == "tool":
                    # Show individual tool details (parts[3] is index into tool_calls)
                    try:
                        tool_idx = int(parts[3]) if len(parts) > 3 else None
                    except (IndexError, ValueError):
                        tool_idx = None
                    if tool_idx is not None and tool_idx < len(job.tool_calls):
                        self._job_view_state[job_id] = f"tool:{tool_idx}"
                        await self._show_tool_details(query, job, job.tool_calls[tool_idx].id)
                        
                elif action == "response":
                    # Show the final response
                    await self._show_job_response(query, job)

                elif action == "abort":
                    # Abort the job
                    if job.status == "running":
                        await job_manager.abort_job(job.id)
                        await query.edit_message_text(
                            f"🛑 Job aborted by user.\n\nJob ID: `{job_id}`\nStatus: Aborted",
                            parse_mode="Markdown",
                        )
                    else:
                        await query.edit_message_text(
                            f"ℹ️ Job is not running or already completed.\n\n"
                            f"Status: {job.status}",
                            parse_mode="Markdown",
                        )

            elif data.startswith("lastjob:"):
                # Handle lastjob navigation
                _, offset_str = data.split(":")
                offset = int(offset_str)
                await self._on_lastjob_callback(query, offset)

            elif data.startswith("job:abort:"):
                job_id = data.split(":", 2)[2]
                await self._handle_abort(query, job_id)

            elif data.startswith("tool_notif:"):
                _, level, chat_id = data.split(":")
                self._tool_notification_level[int(chat_id)] = int(level)
                await query.answer(f"Notification level set to {level}")
                await query.edit_message_text(f"✅ Notification level set to {level}")

        except AssertionError as e:
            # Assertions should crash - send to telegram first
            logger.critical(f"ASSERTION FAILED: {e}")
            import traceback
            tb = traceback.format_exc()
            try:
                chat_id = query.message.chat_id if query.message else None
                if chat_id and self._channel:
                    await self._channel._app.bot.send_message(
                        chat_id=chat_id,
                        text=f"💥 **CRASH**\n\n```\n{e}\n\n{tb[:3000]}\n```",
                        parse_mode="Markdown"
                    )
            except:
                pass
            raise
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"Error handling callback: {e}\n{tb}")
            try:
                chat_id = query.message.chat_id if query.message else None
                if chat_id and self._channel:
                    await self._channel._app.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ **Error**\n\n```\n{e}\n\n{tb[:3000]}\n```",
                        parse_mode="Markdown"
                    )
            except:
                pass
            await query.answer("Error processing request")
        finally:
            if lock_acquired:
                lock.release()

    async def _handle_view_toggle(self, query, job_id: str):
        """Toggle between timeline and summary/details view."""
        start_time = asyncio.get_event_loop().time()
        logger.info(f"_handle_view_toggle called for job {job_id}")
        job = await job_manager.get_job(job_id)
        get_job_time = asyncio.get_event_loop().time() - start_time
        if get_job_time > 0.5:
            logger.warning(f"[PERF] Slow get_job: {get_job_time:.2f}s for job {job_id}")
        if not job:
            logger.warning(f"Job {job_id} not found")
            await query.answer("Job not found")
            return

        current_state = self._job_view_state.get(job_id, "timeline")
        logger.info(f"Current state for job {job_id}: {current_state}")

        new_state = "details" if current_state == "timeline" else "timeline"
        logger.info(f"Switching job {job_id} from {current_state} to {new_state}")
        self._job_view_state[job_id] = new_state
        text, keyboard = self._render_view(job, new_state)

        logger.info(f"About to edit message for job {job_id}")
        edit_start = asyncio.get_event_loop().time()
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        edit_time = asyncio.get_event_loop().time() - edit_start
        if edit_time > 0.5:
            logger.warning(f"[PERF] Slow edit_message_text: {edit_time:.2f}s for job {job_id}")
        logger.info(f"Message edited successfully for job {job_id}")
        total_time = asyncio.get_event_loop().time() - start_time
        if total_time > 1.0:
            logger.warning(f"[PERF] Slow _handle_view_toggle total: {total_time:.2f}s for job {job_id}")
        await query.answer()

    def _create_summary_keyboard(self, job, page: int = 0) -> list:
        """Create keyboard for summary view (10 items per page)."""
        keyboard = []
        total_tools = len(job.tool_calls)
        items_per_page = 10

        if total_tools > items_per_page:
            start_idx = page * items_per_page
            end_idx = min(start_idx + items_per_page, total_tools)
            total_pages = (total_tools + items_per_page - 1) // items_per_page

            # Page info and navigation
            page_info = f"📄 Page {page + 1}/{total_pages} ({start_idx + 1}-{end_idx} of {total_tools} tools)"
            keyboard.append(
                [InlineKeyboardButton(page_info, callback_data=f"job:summary_page:{job.id}:{page}")]
            )

            nav_buttons = []
            if page > 0:
                nav_buttons.append(
                    InlineKeyboardButton(
                        "⬅️ Prev", callback_data=f"job:summary_page:{job.id}:{page - 1}"
                    )
                )
            if end_idx < total_tools:
                nav_buttons.append(
                    InlineKeyboardButton(
                        "Next ➡️", callback_data=f"job:summary_page:{job.id}:{page + 1}"
                    )
                )
            if nav_buttons:
                keyboard.append(nav_buttons)

            # Expand button for this page
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🔍 Expand This Page", callback_data=f"job:expand:{job.id}:{page}"
                    )
                ]
            )
        else:
            # Show expand button even for small lists
            keyboard.append(
                [InlineKeyboardButton("🔍 Expand All", callback_data=f"job:expand:{job.id}:0")]
            )

        self._add_common_footer_buttons(keyboard, job)

        return keyboard

    def _create_expanded_keyboard(self, job, page: int = 0) -> list:
        """Create keyboard for expanded view (detailed tool list)."""
        keyboard = []
        total_tools = len(job.tool_calls)
        items_per_page = 10
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, total_tools)

        # Add individual tool buttons for this page only
        for i in range(start_idx, end_idx):
            tc = job.tool_calls[i]
            status_emoji = tc.to_emoji()
            # Truncate name if too long
            name = tc.name[:25] + "..." if len(tc.name) > 25 else tc.name
            label = f"{status_emoji} {name}"
            keyboard.append(
                [InlineKeyboardButton(label, callback_data=f"job:tool:{job.id}:{i}")]
            )

        # Navigation for expanded view
        total_pages = (total_tools + items_per_page - 1) // items_per_page
        if total_pages > 1:
            nav_buttons = []
            if page > 0:
                nav_buttons.append(
                    InlineKeyboardButton("⬅️ Prev", callback_data=f"job:expand:{job.id}:{page - 1}")
                )
            nav_buttons.append(
                InlineKeyboardButton(
                    f"📄 {page + 1}/{total_pages}", callback_data=f"job:expand:{job.id}:{page}"
                )
            )
            if end_idx < total_tools:
                nav_buttons.append(
                    InlineKeyboardButton("Next ➡️", callback_data=f"job:expand:{job.id}:{page + 1}")
                )
            keyboard.append(nav_buttons)

        self._add_common_footer_buttons(keyboard, job, extra_buttons=[
            InlineKeyboardButton("⬅️ Summary", callback_data=f"job:back_summary:{job.id}:{page}"),
        ])

        return keyboard

    def _format_summary_message(self, job, page: int = 0) -> str:
        """Format summary message showing tool overview."""
        lines = [f"{job.get_timeline_emoji(10)}", ""]

        total_tools = len(job.tool_calls)
        items_per_page = 10
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, total_tools)

        # Show summary of tools on this page
        for i in range(start_idx, end_idx):
            tc = job.tool_calls[i]
            status = tc.status.value
            duration = f" ({tc.duration_ms}ms)" if tc.duration_ms > 0 else ""

            preview = ""
            if tc.name == "🧠 thinking" and tc.result:
                thinking_text = self._escape_markdown(tc.result).replace("\n", " ")
                preview = f"\n  💭 `{thinking_text[:200]}{'...' if len(thinking_text) > 200 else ''}`"
            elif tc.name == "memory_consolidation":
                # Show memory consolidation details
                if tc.arguments.get("archiving"):
                    preview = f" (archiving {tc.arguments['archiving']} msgs)"
                elif tc.arguments.get("error"):
                    preview = f" ❌ {tc.arguments['error'][:50]}"
            elif tc.arguments:
                args_str = json.dumps(tc.arguments)
                preview_text = self._escape_markdown(
                    args_str.replace('"', "").replace("{", "").replace("}", "").replace("(", "").replace(")", "")
                )[:40]
                if len(args_str) > 40:
                    preview_text += "..."
                preview = f" → {preview_text}"

            safe_name = self._escape_markdown(tc.name)
            lines.append(f"{tc.to_emoji()} `{safe_name}`{duration}{preview}")

        # Add overall stats (without numbers)
        timeline_emoji = self._get_timeline_emoji()
        lines.extend(
            [
                "",
                f"{timeline_emoji} Tools: {total_tools}",
                f"⏱️ Duration: {job.duration_seconds:.1f}s",
                f"📋 Status: {job.status}",
            ]
        )

        return "\n".join(lines)

    def _format_expanded_message(self, job, page: int = 0) -> str:
        """Format expanded message with detailed tool info (400 chars per tool)."""
        lines = [f"{job.get_timeline_emoji(10)}", ""]

        total_tools = len(job.tool_calls)
        items_per_page = 10
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, total_tools)

        # Show detailed info for each tool (400 chars budget per tool)
        for i in range(start_idx, end_idx):
            tc = job.tool_calls[i]
            safe_name = self._escape_markdown(tc.name)
            duration = f" ({tc.duration_ms}ms)" if tc.duration_ms > 0 else ""

            # Format tool name nicely
            if tc.name == "memory_consolidation":
                display_name = "🗄️ Memory Consolidation"
            else:
                display_name = f"`{safe_name}`"
            lines.append(f"{tc.to_emoji()} **{display_name}**{duration}")

            # Arguments (up to 180 chars)
            if tc.arguments:
                if tc.name == "memory_consolidation":
                    # Special formatting for memory consolidation
                    archiving = tc.arguments.get("archiving", 0)
                    keeping = tc.arguments.get("keeping", 0)
                    lines.append(f"  📊 Archiving {archiving} messages, keeping {keeping}")
                else:
                    args_str = self._escape_markdown(
                        json.dumps(tc.arguments).replace('"', "").replace("{", "").replace("}", "")
                    )
                    lines.append(f"  In: `{args_str[:180]}{'...' if len(args_str) > 180 else ''}`")

            # Result/Output (up to 200 chars)
            if tc.result and tc.status.value in ("success", "thinking"):
                result_text = self._escape_markdown(tc.result)
                if tc.name == "🧠 thinking":
                    label = "💭 Thinking"
                elif tc.name == "memory_consolidation":
                    label = "✅ Done"
                else:
                    label = "Out"
                lines.append(f"  {label}: `{result_text[:200]}{'...' if len(tc.result) > 200 else ''}`")
            elif tc.error:
                error_text = self._escape_markdown(tc.error)
                lines.append(f"  ❌ `{error_text[:200]}{'...' if len(tc.error) > 200 else ''}`")

            lines.append("")  # Empty line between tools

        text = "\n".join(lines)
        if len(text) > 4096:
            text = text[:4050] + "\n\n... (message too long)"

        return text

    async def _handle_abort(self, query, job_id: str):
        """Handle abort button."""
        success = await job_manager.abort_job(job_id)
        if success:
            await query.answer("Job aborted")
            await query.edit_message_text("🛑 Job aborted")
            self._cleanup_job_state(job_id)
        else:
            await query.answer("Could not abort job")

    def _format_tool_detail_view(self, job, tool_idx: int) -> tuple[str, list] | None:
        """Return (text, keyboard) for a tool detail view, or None if index is out of range."""
        if tool_idx >= len(job.tool_calls):
            return None
        tool_call = job.tool_calls[tool_idx]

        lines = [
            f"{job.get_timeline_emoji(10)}", "",
            f"🔧 **Tool: `{tool_call.name}`**\n",
            f"Status: {tool_call.status.value}",
        ]

        if tool_call.duration_ms > 0:
            lines.append(f"Duration: {tool_call.duration_ms}ms")

        if tool_call.arguments:
            args_str = json.dumps(tool_call.arguments, indent=2)
            if len(args_str) > 1000:
                args_str = args_str[:997] + "..."
            # Escape backticks to prevent breaking code block
            args_str = args_str.replace("```", "'`'")
            lines.append(f"\n**Input:**\n```json\n{args_str}\n```")

        if tool_call.result:
            result_str = str(tool_call.result)
            if len(result_str) > 1500:
                result_str = result_str[:1497] + "..."
            # Escape backticks to prevent breaking code block
            result_str = result_str.replace("```", "'`'")
            lines.append(f"\n**Result:**\n```\n{result_str}\n```")

        if tool_call.error:
            error_str = str(tool_call.error)
            # Escape backticks to prevent breaking code block
            error_str = error_str.replace("```", "'`'")
            lines.append(f"\n**Error:**\n```\n{error_str}\n```")

        text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("⬅️ Back to Job", callback_data=f"job:back:{job.id}")]]
        return text, keyboard

    async def _show_tool_details(self, query, job, tool_id: str):
        """Show details for a specific tool call."""
        # Find index by id
        tool_idx = next((i for i, tc in enumerate(job.tool_calls) if tc.id == tool_id), None)
        if tool_idx is None:
            await query.answer("Tool not found")
            return

        result = self._format_tool_detail_view(job, tool_idx)
        if not result:
            await query.answer("Tool not found")
            return

        text, keyboard = result
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def _show_job_response(self, query, job):
        """Show the final response of a job."""
        response = job.final_response[:3000] if job.final_response else "No response"
        safe_response = self._escape_markdown(response)
        
        text = f"{job.get_timeline_emoji(10)}\n\n📄 **Job Response**\n\n{safe_response}{'...' if len(job.final_response) > 3000 else ''}"
        
        # Add back button
        keyboard = [[InlineKeyboardButton("⬅️ Back to Job", callback_data=f"job:back:{job.id}")]]
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def _build_lastjob_keyboard(self, session_key: str, job, offset: int) -> list:
        """Build keyboard for lastjob view with summary and navigation buttons."""
        keyboard = self._create_summary_keyboard(job, page=0)

        nav_buttons = []
        if offset > 0:
            nav_buttons.append(
                InlineKeyboardButton("⬅️ Newer", callback_data=f"lastjob:{offset - 1}")
            )

        older_job = await job_manager.get_last_job(session_key, offset=offset + 1)
        if older_job:
            nav_buttons.append(
                InlineKeyboardButton("Older ➡️", callback_data=f"lastjob:{offset + 1}")
            )

        if nav_buttons:
            keyboard.insert(0, nav_buttons)

        return keyboard

    # Command handlers (simplified versions)
    async def _on_lastjob_command(self, update, context):
        """Handle /lastjob command to show details of recent jobs."""
        if not update.message:
            return

        # Check permission
        if not self._check_permission(update):
            await self._send_permission_denied(update)
            return

        chat_id = update.message.chat_id
        session_key = f"telegram:{chat_id}"

        # Parse offset from command args (e.g., "/lastjob 2")
        offset = 0
        if context.args and len(context.args) > 0:
            try:
                offset = int(context.args[0])
                if offset < 0:
                    offset = 0
            except ValueError:
                pass

        # Get the job at specified offset
        job = await job_manager.get_last_job(session_key, offset=offset)
        if not job:
            if offset == 0:
                await update.message.reply_text("No recent jobs found for this chat.")
            else:
                await update.message.reply_text(
                    f"No job found at offset {offset}. Try /lastjob with a smaller number."
                )
            return

        keyboard = await self._build_lastjob_keyboard(session_key, job, offset)
        text = self._format_summary_message(job, page=0)

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def _on_lastjob_callback(self, query, offset: int):
        """Handle lastjob navigation callbacks."""
        await query.answer()

        chat_id = query.message.chat_id if query.message else None
        if not chat_id:
            return

        session_key = f"telegram:{chat_id}"

        job = await job_manager.get_last_job(session_key, offset=offset)
        if not job:
            await query.edit_message_text(f"❌ No job found at position {offset + 1}.")
            return

        keyboard = await self._build_lastjob_keyboard(session_key, job, offset)
        text = self._format_summary_message(job, page=0)

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def _on_jobs_command(self, update, context):
        if not update.message:
            return
        
        # Check permission
        if not self._check_permission(update):
            await self._send_permission_denied(update)
            return
        
        chat_id = str(update.message.chat_id)
        session_key = f"telegram:{chat_id}"

        jobs = [j for j in job_manager._jobs.values() if j.session_key == session_key]
        if not jobs:
            await update.message.reply_text("No jobs found.")
            return

        jobs.sort(key=lambda j: j.created_at, reverse=True)
        lines = ["📋 **Recent Jobs**\n"]
        for i, job in enumerate(jobs[:5], 1):
            status = "✅" if job.completed_at else "⏳"
            lines.append(f"{status} `{job.id[:8]}` - {job.user_message[:30]}...")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _on_abort_command(self, update, context):
        if not update.message:
            return
        
        # Check permission
        if not self._check_permission(update):
            await self._send_permission_denied(update)
            return
        
        chat_id = str(update.message.chat_id)
        session_key = f"telegram:{chat_id}"

        for job in job_manager._jobs.values():
            if job.session_key == session_key and not job.completed_at:
                await job_manager.abort_job(job.id)
                await update.message.reply_text(f"🛑 Aborted job `{job.id[:8]}`", parse_mode="Markdown")
                return

        await update.message.reply_text("No running jobs to abort.")

    async def _on_toggle_tool_calls(self, update, context):
        if not update.message:
            return

        # Check permission
        if not self._check_permission(update):
            await self._send_permission_denied(update)
            return

        chat_id = update.message.chat_id
        current_level = self._tool_notification_level.get(chat_id, 0)

        keyboard = [
            [InlineKeyboardButton("✅ Off" if current_level == 0 else "Off", callback_data=f"tool_notif:0:{chat_id}")],
            [InlineKeyboardButton("✅ Completions only" if current_level == 1 else "Completions only", callback_data=f"tool_notif:1:{chat_id}")],
            [InlineKeyboardButton("✅ Completions + args" if current_level == 2 else "Completions + args", callback_data=f"tool_notif:2:{chat_id}")],
            [InlineKeyboardButton("✅ Everything" if current_level == 3 else "Everything", callback_data=f"tool_notif:3:{chat_id}")],
        ]

        await update.message.reply_text(
            "🔧 **Tool Call Notifications**\n\nSelect notification level:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )


# Initialize plugin
plugin = TelegramUIPlugin()
