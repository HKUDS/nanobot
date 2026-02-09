"""Agent loop: the core processing engine."""

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import SessionManager


class AgentLoop:
    """
    The agent loop is the core processing engine.
    
    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """
    
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        from nanobot.cron.service import CronService
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        
        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
        )
        
        self._running = False
        self._register_default_tools()
    
    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(EditFileTool())
        self.tools.register(ListDirTool())
        
        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.exec_config.restrict_to_workspace,
        ))
        
        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        
        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)
        
        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)
        
        # Cron tool (for scheduling)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))
    
    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")
        
        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
                # Process it
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Send error response
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue
    
    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a single inbound message.

        Args:
            msg: The inbound message to process.

        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)

        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")

        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)

        # === Claude Code Mode Handling ===
        if session.claude_mode:
            return await self._handle_claude_mode(msg, session)

        # Check if user wants to enter Claude Code mode
        enter_result = self._check_enter_claude_mode(msg.content, session)
        if enter_result:
            self.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=enter_result
            )
        # === End Claude Code Mode Handling ===

        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(msg.channel, msg.chat_id)
        
        # Build initial messages (use get_history for LLM-formatted messages)
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )
        
        # Agent loop
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            # Handle tool calls
            if response.has_tool_calls:
                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)  # Must be JSON string
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # No tool calls, we're done
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "I've completed processing but have no response to give."
        
        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content
        )
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).
        
        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info(f"Processing system message from {msg.sender_id}")
        
        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(origin_channel, origin_chat_id)
        
        # Build messages with the announce content
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
        )
        
        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).
        
        Args:
            content: The message content.
            session_key: Session identifier.
            channel: Source channel (for context).
            chat_id: Source chat ID (for context).
        
        Returns:
            The agent's response.
        """
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )
        
        response = await self._process_message(msg)
        return response.content if response else ""

    # === Claude Code Mode Methods ===

    def _check_enter_claude_mode(self, content: str, session) -> str | None:
        """
        Check if user wants to enter Claude Code mode.

        Returns a welcome message if entering, None otherwise.
        """
        content_lower = content.lower().strip()

        # Match patterns like:
        # "进入 G:\projects\myapp 写代码"
        # "enter G:\projects\myapp code mode"
        # "claude code G:\projects\myapp"
        # "在 /home/user/project 写代码"
        patterns = [
            r"(?:进入|enter|打开|open)\s+['\"]?([A-Za-z]:[\\\/][^\s'\"]+|\/[^\s'\"]+)['\"]?\s*(?:写代码|编程|code|coding)?",
            r"(?:claude\s*code|cc)\s+['\"]?([A-Za-z]:[\\\/][^\s'\"]+|\/[^\s'\"]+)['\"]?",
            r"(?:在|at|in)\s+['\"]?([A-Za-z]:[\\\/][^\s'\"]+|\/[^\s'\"]+)['\"]?\s*(?:写代码|编程|code|coding)",
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                working_dir = match.group(1).strip().strip("'\"")
                path = Path(working_dir)

                if not path.exists():
                    return f"❌ 目录不存在: {working_dir}"
                if not path.is_dir():
                    return f"❌ 不是目录: {working_dir}"

                session.claude_mode = True
                session.claude_working_dir = str(path.resolve())
                session.claude_session_id = None

                return (
                    f"✅ 已进入 Claude Code 模式\n"
                    f"📁 工作目录: {session.claude_working_dir}\n\n"
                    f"现在你发送的消息会直接传给 Claude Code 处理。\n"
                    f"发送「退出」或「exit」退出此模式。"
                )

        return None

    async def _handle_claude_mode(self, msg: InboundMessage, session) -> OutboundMessage:
        """
        Handle messages when in Claude Code mode.

        Directly forwards messages to Claude Code CLI.
        """
        content = msg.content.strip()
        content_lower = content.lower()

        # Check for exit commands
        exit_commands = ["退出", "exit", "quit", "退出claude", "exit claude", "q"]
        if content_lower in exit_commands:
            session.claude_mode = False
            session.claude_working_dir = None
            session.claude_session_id = None
            self.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="✅ 已退出 Claude Code 模式，回到正常对话。"
            )

        # Build command - use shell mode for Windows PATH compatibility
        # Use --output-format json to get session_id for continuity
        cmd_parts = ["claude", "--print", "--dangerously-skip-permissions", "--output-format", "json"]

        # Use --resume if we have a session_id (for conversation continuity)
        if session.claude_session_id:
            cmd_parts.extend(["--resume", session.claude_session_id])

        cmd_str = " ".join(cmd_parts)

        logger.info(f"Claude Code mode: executing in {session.claude_working_dir}")
        logger.debug(f"Command: {cmd_str}")

        try:
            # Run Claude Code with shell=True for Windows PATH compatibility
            process = await asyncio.create_subprocess_shell(
                cmd_str,
                cwd=session.claude_working_dir,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Pass content via stdin
            stdout, stderr = await process.communicate(input=content.encode("utf-8"))

            output = stdout.decode("utf-8", errors="replace")
            error_output = stderr.decode("utf-8", errors="replace")

            # Parse JSON output to extract session_id and result
            display_text = output
            try:
                if output.strip():
                    json_output = json.loads(output)
                    # Extract session_id for conversation continuity
                    if "session_id" in json_output:
                        session.claude_session_id = json_output["session_id"]
                        logger.debug(f"Captured Claude session_id: {session.claude_session_id}")
                    # Extract the actual response text
                    if "result" in json_output:
                        display_text = json_output["result"]
                    elif "content" in json_output:
                        display_text = json_output["content"]
            except json.JSONDecodeError:
                # Not JSON, use raw output (fallback for older claude versions)
                logger.debug("Claude output is not JSON, using raw output")

            # Save session state
            session.add_message("user", f"[Claude Code] {content}")
            session.add_message("assistant", display_text[:500] if display_text else "(无输出)")
            self.sessions.save(session)

            # Prepare response
            if process.returncode != 0 and error_output:
                result = f"⚠️ Claude Code 返回错误:\n```\n{error_output[:2000]}\n```"
                if display_text:
                    result += f"\n\n输出:\n{display_text[:3000]}"
            elif display_text:
                # Truncate very long output
                if len(display_text) > 4000:
                    result = display_text[:4000] + f"\n\n... (输出过长，已截断，共 {len(display_text)} 字符)"
                else:
                    result = display_text
            else:
                result = "(Claude Code 无输出)"

            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=result
            )

        except FileNotFoundError:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="❌ 错误: 未找到 `claude` 命令。请确保已安装 Claude Code:\n`npm install -g @anthropic-ai/claude-code`"
            )
        except Exception as e:
            logger.error(f"Claude Code execution error: {e}")
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"❌ 执行 Claude Code 时出错: {str(e)}"
            )
