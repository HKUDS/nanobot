"""QOL (Quality of Life) features for the agent loop.

This module provides Telegram QOL features via a hook-based architecture
to minimize conflicts with upstream code.
"""

import asyncio
import json
from typing import Any

from loguru import logger

from nanobot.agent.job_tracker import job_manager, ToolCallStatus
from nanobot.system.hooks import hook_manager


class QOLManager:
    """Manages QOL features for agent processing."""
    
    def __init__(self, agent):
        """Initialize QOL manager with reference to agent loop."""
        self.agent = agent
        self._pending_messages: dict[str, list[str]] = {}
        self._processing_sessions: set[str] = set()
    
    def is_processing(self, session_key: str) -> bool:
        """Check if a session is currently being processed."""
        return session_key in self._processing_sessions
    
    def queue_message(self, session_key: str, message: str) -> None:
        """Queue a message for a session that's currently being processed."""
        if session_key not in self._pending_messages:
            self._pending_messages[session_key] = []
        self._pending_messages[session_key].append(message)
        logger.info(f"Queued message for session {session_key}: {message[:50]}...")
    
    def get_and_clear_pending_messages(self, session_key: str) -> list[str]:
        """Get and clear pending messages for a session."""
        messages = self._pending_messages.get(session_key, [])
        if session_key in self._pending_messages:
            del self._pending_messages[session_key]
        return messages
    
    def start_processing(self, session_key: str) -> None:
        """Mark a session as being processed."""
        self._processing_sessions.add(session_key)
    
    def finish_processing(self, session_key: str) -> None:
        """Mark a session as finished processing."""
        self._processing_sessions.discard(session_key)
    
    async def check_job_abort(self, job_id: str | None) -> bool:
        """Check if a job has been aborted."""
        if not job_id:
            return False
        job = await job_manager.get_job(job_id)
        return bool(job and job.is_aborted)
    
    async def track_llm_call_start(self, job_id: str, iteration: int, model: str, 
                                   channel: str, chat_id: str) -> Any:
        """Track the start of an LLM call."""
        if not job_id:
            return None
        
        job = await job_manager.get_job(job_id)
        if not job:
            return None
        
        llm_call_record = await job_manager.job_add_tool_call(
            job_id, "llm_call", {"model": model, "iteration": iteration}
        )
        
        if llm_call_record:
            await hook_manager.emit("agent.tool.execute",
                tool_name="llm_call",
                tool_args=llm_call_record.arguments,
                tool_id=llm_call_record.id,
                channel=channel,
                chat_id=chat_id,
                status="start",
                agent=self.agent,
                job_id=job_id
            )
            # Update timeline immediately
            await hook_manager.emit("agent.timeline.update", 
                job_id=job_id, channel=channel, chat_id=chat_id)
        
        return llm_call_record
    
    async def track_llm_call_retry(self, llm_call_record: Any, iteration: int) -> None:
        """Update LLM call record for retry."""
        if llm_call_record:
            llm_call_record.arguments["iteration"] = iteration
            llm_call_record.arguments["retry"] = True
    
    async def track_llm_call_end(self, job_id: str, llm_call_record: Any, 
                                 channel: str, chat_id: str) -> None:
        """Track the end of an LLM call."""
        if job_id and llm_call_record:
            await job_manager.job_update_tool_call(
                job_id, llm_call_record.id, ToolCallStatus.SUCCESS
            )
            await hook_manager.emit("agent.tool.execute",
                tool_name="llm_call",
                tool_args=llm_call_record.arguments,
                tool_id=llm_call_record.id,
                channel=channel,
                chat_id=chat_id,
                status="end",
                agent=self.agent,
                job_id=job_id
            )
    
    async def emit_thinking(self, thinking: str, channel: str, chat_id: str, 
                           job_id: str | None) -> None:
        """Emit thinking/reasoning content."""
        if thinking:
            logger.info(f"LLM thinking captured ({len(thinking)} chars)")
            await hook_manager.emit("agent.thinking",
                channel=channel,
                chat_id=chat_id,
                content=thinking,
                job_id=job_id
            )
    
    async def emit_intermediate_message(self, content: str, channel: str, 
                                       chat_id: str, job_id: str | None) -> None:
        """Emit an intermediate message from the LLM."""
        if not content or not content.strip():
            return
        
        logger.info(f"LLM provided intermediate message: {content[:100]}...")
        
        await hook_manager.emit("agent.response.text",
            channel=channel,
            chat_id=chat_id,
            content=content,
            is_final=False,
            job_id=job_id
        )
    
    async def execute_tool_with_hooks(self, tool_call, channel: str, chat_id: str, 
                                     job_id: str | None) -> str:
        """Execute a tool with start/end hooks."""
        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
        logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
        
        # Emit start hook
        await hook_manager.emit("agent.tool.execute",
            tool_name=tool_call.name,
            tool_args=tool_call.arguments,
            tool_id=tool_call.id,
            channel=channel,
            chat_id=chat_id,
            status="start",
            agent=self.agent,
            job_id=job_id
        )
        
        # Execute tool
        result = await self.agent.tools.execute(
            tool_call.name, tool_call.arguments,
            channel=channel, chat_id=chat_id, job_id=job_id,
            bus=self.agent.bus, session_manager=self.agent.sessions,
        )
        
        # Emit end hook
        await hook_manager.emit("agent.tool.execute",
            tool_name=tool_call.name,
            tool_args=tool_call.arguments,
            tool_id=tool_call.id,
            channel=channel,
            chat_id=chat_id,
            status="end",
            result=result,
            agent=self.agent,
            job_id=job_id
        )
        
        return result
    
    async def poll_for_messages(self, session_key: str) -> list[str]:
        """Poll for new messages from the bus during tool execution."""
        queue_size = self.agent.bus.inbound.qsize()
        logger.debug(f"DEBUG: Checking bus queue, size={queue_size}")
        polled_count = 0
        
        while queue_size > 0:
            try:
                pending_msg = await asyncio.wait_for(
                    self.agent.bus.inbound.get(), timeout=0.1
                )
                polled_count += 1
                logger.debug(f"DEBUG: Polled message from bus for session {pending_msg.session_key}")
                
                if pending_msg.session_key == session_key:
                    self.queue_message(pending_msg.session_key, pending_msg.content)
                    logger.info(f"DEBUG: Queued message for session {pending_msg.session_key}")
                else:
                    # Put it back for later processing
                    await self.agent.bus.inbound.put(pending_msg)
                    logger.debug("DEBUG: Message for different session, put back in queue")
                    break
                queue_size = self.agent.bus.inbound.qsize()
            except asyncio.TimeoutError:
                logger.debug("DEBUG: Timeout polling bus queue")
                break
        
        if polled_count > 0:
            logger.info(f"DEBUG: Polled {polled_count} messages from bus")
        
        return self.get_and_clear_pending_messages(session_key)
    
    async def handle_job_completion(self, job_id: str, final_content: str) -> None:
        """Handle job completion tracking."""
        if job_id:
            await job_manager.complete_job(job_id, final_content)
    
    async def emit_final_response(self, content: str, channel: str, chat_id: str) -> None:
        """Emit final response hook."""
        await hook_manager.emit("agent.response.text",
            channel=channel,
            chat_id=chat_id,
            content=content,
            is_final=True
        )
    
    async def handle_error(self, error: Exception, job_id: str | None) -> str:
        """Handle error with job tracking."""
        import traceback
        logger.error(f"Error: {error}")
        logger.error(traceback.format_exc())
        
        if job_id:
            try:
                await job_manager.fail_job(job_id, str(error))
            except Exception as fail_error:
                logger.warning(f"Failed to mark job {job_id} as failed: {fail_error}")
        
        return f"Sorry, I encountered an error: {str(error)}"
    
    async def execute_tool_directly(self, tool_name: str, arguments: dict[str, Any], 
                                   channel: str, chat_id: str, 
                                   job_id: str | None = None) -> str:
        """Execute a tool directly and return the result formatted for the user."""
        # Emit hook for tool execution
        await hook_manager.emit("agent.tool.execute",
            tool_name=tool_name,
            tool_args=arguments,
            channel=channel,
            chat_id=chat_id,
            status="start",
            agent=self.agent,
            job_id=job_id
        )
        
        result = await self.agent.tools.execute(
            tool_name, arguments,
            channel=channel, chat_id=chat_id, job_id=job_id,
        )
        
        # Emit hook for tool completion
        await hook_manager.emit("agent.tool.execute",
            tool_name=tool_name,
            tool_args=arguments,
            channel=channel,
            chat_id=chat_id,
            status="end",
            result=result,
            agent=self.agent,
            job_id=job_id
        )
        
        return result
