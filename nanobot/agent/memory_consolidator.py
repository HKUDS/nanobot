"""Memory consolidation for processing conversation history."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, List

from loguru import logger

from nanobot.providers.base import LLMProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool


class MemoryConsolidator:
    """
    Handles memory consolidation by directly executing the consolidation task.
    """
    
    def __init__(self, provider: LLMProvider, workspace: Path, model: str):
        """
        Initialize the memory consolidator.
        """
        self.provider = provider
        self.workspace = workspace
        self.model = model
        self.memory_dir = workspace / "memory"
    
    async def consolidate(
        self,
        old_messages: List[dict[str, Any]],
    ) -> str:
        """
        Execute memory consolidation for a batch of old messages.
        """
        if not old_messages:
            return "No messages to consolidate"
        
        logger.info("Starting memory consolidation...")
        
        # Build task description
        task = self._build_task_description(old_messages)
        
        # Setup tools for consolidation
        tools = ToolRegistry()
        tools.register(ReadFileTool(allowed_dir=self.workspace))
        tools.register(WriteFileTool(allowed_dir=self.workspace))
        tools.register(EditFileTool(allowed_dir=self.workspace))
        
        # Build messages
        system_prompt = """You are a memory consolidation agent. Your task is to process conversation history and update memory files efficiently. You have access to read_file, write_file, and edit_file tools to manage memory files."""
        messages: List[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]
        
        # Execute consolidation with tool calls
        max_iterations = 10
        iteration = 0
        
        try:
            while iteration < max_iterations:
                iteration += 1
                
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                )
                
                if response.has_tool_calls:
                    # Add assistant message with tool calls
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })
                    
                    # Execute tools
                    for tool_call in response.tool_calls:
                        logger.debug(f"Memory consolidation executing: {tool_call.name}")
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    # Done
                    logger.info("Memory consolidation completed successfully")
                    return "Memory consolidation completed"
            logger.warning("Memory consolidation reached max iterations")
            return "Memory consolidation completed (max iterations reached)"
        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")
            return f"Memory consolidation failed: {e}"
    
    def _build_task_description(self, messages: List[dict[str, Any]]) -> str:
        """
        Build the task description for the memory consolidation subagent.
        """
        # Get today's date for the daily memory file
        today = datetime.now().strftime("%Y-%m-%d")
        memory_file = self.memory_dir / "MEMORY.md"
        daily_file = self.memory_dir / f"{today}.md"
        
        # Format messages for the subagent
        conversation_text = self._format_messages(messages)
        
        # Extract time range from messages
        time_range = self._get_time_range(messages)
        
        task = f"""You are a memory consolidation agent. Your task is to process a batch of conversation messages and update memory files.

## Task Overview

Process the conversation batch below and:
1. Extract long-term information (user preferences, facts, project context, relationships) and update MEMORY.md under appropriate sections if needed
2. Summarize the conversation into event entries and append to today's daily memory file ({today}.md)

## Files to Update

- Long-term memory: {memory_file}
- Daily memory: {daily_file}

## Conversation Batch to Process

Time Range: {time_range}

{conversation_text}

## Instructions

1. **Read current memory files**:
   - Use read_file to read {memory_file}
   - Try to read {daily_file} (it may not exist yet)

2. **Extract long-term information**:
   - Identify any new user preferences, facts, project context, or relationships
   - If found, use edit_file to update {memory_file} under the appropriate section headers
   - Only modify MEMORY.md if there is genuinely new long-term information

3. **Summarize conversation events**:
   - Break down the conversation into distinct events or discussion topics
   - Keep summaries concise but information-complete for future retrieval
   - Format each event as: `- [HH:MM-HH:MM] Event description`
   - For {daily_file}:
     * If it doesn't exist: use write_file to create it with header `# {today}` followed by your event entries
     * If it exists: use edit_file to append new event entries at the end

4. **Guidelines**:
   - Maintain chronological order in daily files
   - Be thorough but concise

Execute these steps now."""
        
        return task
    
    def _format_messages(self, messages: List[dict[str, Any]]) -> str:
        """
        Format messages into a readable conversation text.
        """
        lines = []
        for i, msg in enumerate(messages, 1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")
            
            # Format timestamp if available
            time_str = ""
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    time_str = dt.strftime("%H:%M")
                except Exception:
                    pass
            
            # Format message
            if time_str:
                lines.append(f"[{time_str}] {role.upper()}: {content}")
            else:
                lines.append(f"{i}. {role.upper()}: {content}")
        
        return "\n".join(lines)
    
    def _get_time_range(self, messages: List[dict[str, Any]]) -> str:
        """
        Extract time range from messages.   
        """
        timestamps = []
        for msg in messages:
            ts = msg.get("timestamp")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    timestamps.append(dt)
                except Exception:
                    continue
        
        if not timestamps:
            return "Unknown time"
        
        start_time = min(timestamps).strftime("%H:%M")
        end_time = max(timestamps).strftime("%H:%M")
        
        return f"{start_time}-{end_time}"
