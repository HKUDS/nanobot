"""Agent loop: the core processing engine."""

import asyncio
from contextlib import AsyncExitStack
import json
import json_repair
from pathlib import Path
import re
from typing import Any, Awaitable, Callable
from datetime import datetime

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
from nanobot.agent.tools.camoufox_browser import CamoufoxBrowserTool
from nanobot.agent.tools.research import ResearchTool
from nanobot.agent.tools.multiedit import MultiEditTool
from nanobot.agent.tools.todo import TodoTool
from nanobot.agent.tools.workflow import (
    AwaitAgentTool,
    GetAgentResultTool,
    ParallelGroupTool,
    AwaitGroupTool,
    SpawnChainTool,
    WaitAllTool,
)
from nanobot.agent.memory import MemoryStore
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import Session, SessionManager
from nanobot.utils.language import detect_language, detect_language_from_session, get_bot_message


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
        temperature: float = 0.7,
        max_tokens: int = 4096,
        memory_window: int = 50,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        system_prompt: str | None = None,
        config: "Config | None" = None,
        profile_name: str | None = None,
        profile_config: "AgentProfile | None" = None,
    ):
        from nanobot.config.schema import ExecToolConfig, Config, AgentProfile
        from nanobot.cron.service import CronService
        self.bus = bus
        self.provider = provider
        # Ensure workspace is expanded from ~ to absolute path
        if isinstance(workspace, Path):
            self.workspace = workspace
        else:
            self.workspace = Path(workspace).expanduser()
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self._custom_system_prompt = system_prompt
        self.config = config

        # Get bot_name from config or use default
        bot_name = "nanobot"
        if config:
            bot_name = config.agents.defaults.bot_name

        # Profile support
        self.profile_name = profile_name
        self.profile_config = profile_config
        # Get settings from profile or defaults
        if profile_config:
            self.memory_isolation = profile_config.memory_isolation
            self.profile_inherit_base = profile_config.inherit_base_prompt
            self.inherit_global_skills = profile_config.inherit_global_skills
        else:
            self.memory_isolation = "shared"
            self.profile_inherit_base = True
            self.inherit_global_skills = True

        self.context = ContextBuilder(workspace, bot_name=bot_name)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
            config=config,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress

        # Setup monitor logging
        self._setup_monitor()

        self._register_default_tools()

    def _setup_monitor(self) -> None:
        """Setup monitor logging directory and file."""
        from nanobot.config.loader import get_data_dir
        monitor_dir = get_data_dir() / "monitor"
        monitor_dir.mkdir(parents=True, exist_ok=True)
        self._monitor_file = monitor_dir / "messages.log"

    def _log_monitor(self, msg_type: str, content: str, session: str | None = None, channel: str | None = None) -> None:
        """Log a message to the monitor file."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session_part = f" session:{session}" if session else ""
            channel_part = f" channel:{channel}" if channel else ""
            log_entry = f"[{timestamp}] [{msg_type}{session_part}{channel_part}] {content}\n"

            with open(self._monitor_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception:
            # Don't let monitor logging break the agent
            pass
    
    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools (workspace for relative paths, restrict if configured)
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))

        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))

        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())

        # Research tool (Perplexica-style deep research)
        self.tools.register(ResearchTool(
            api_key=self.brave_api_key,
            max_results=10
        ))

        # Camoufox anti-detect browser tool
        self.tools.register(CamoufoxBrowserTool(workspace=self.workspace))

        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)

        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)

        # List subagents tool
        from nanobot.agent.tools.list_subagents import ListSubagentsTool
        self.tools.register(ListSubagentsTool(manager=self.subagents))

        # Cancel subagents tool
        from nanobot.agent.tools.cancel_subagents import CancelSubagentsTool
        self.tools.register(CancelSubagentsTool(manager=self.subagents))

        # Cron tool (for scheduling)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

        # List profiles tool
        from nanobot.agent.tools.profiles import ListProfilesTool
        self.tools.register(ListProfilesTool(config=self.config))

        # Workflow tools for advanced agent patterns
        self.tools.register(AwaitAgentTool(manager=self.subagents))
        self.tools.register(GetAgentResultTool(manager=self.subagents))
        self.tools.register(ParallelGroupTool(manager=self.subagents))
        self.tools.register(AwaitGroupTool(manager=self.subagents))
        self.tools.register(SpawnChainTool(manager=self.subagents))
        self.tools.register(WaitAllTool(manager=self.subagents))

        # Multi-file edit tool
        self.tools.register(MultiEditTool(allowed_dir=allowed_dir))

        # Todo list tool
        self.tools.register(TodoTool(self.workspace, profile=self.profile_name))

        # List skills tool
        from nanobot.agent.tools.list_skills import ListSkillsTool
        self.tools.register(ListSkillsTool(workspace=self.workspace))

        # List tools tool (must be registered last so it can see all other tools)
        from nanobot.agent.tools.list_tools import ListToolsTool
        self.tools.register(ListToolsTool(registry=self.tools))
    
    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or not self._mcp_servers:
            return
        self._mcp_connected = True
        from nanobot.agent.tools.mcp import connect_mcp_servers
        self._mcp_stack = AsyncExitStack()
        await self._mcp_stack.__aenter__()
        await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.set_context(channel, chat_id, message_id)

        if spawn_tool := self.tools.get("spawn"):
            if isinstance(spawn_tool, SpawnTool):
                spawn_tool.set_context(channel, chat_id)

        if cron_tool := self.tools.get("cron"):
            if isinstance(cron_tool, CronTool):
                cron_tool.set_context(channel, chat_id)

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list | None) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        if not tool_calls:
            return ""
        def _fmt(tc):
            val = next(iter(tc.arguments.values()), None) if tc.arguments else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[[str, str | None], Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str]]:
        """
        Run the agent iteration loop.

        Args:
            initial_messages: Starting messages for the LLM conversation.
            on_progress: Optional callback(content, message_type) to push intermediate content.
                        message_type can be "thinking", "action", or None for regular messages.

        Returns:
            Tuple of (final_content, list_of_tools_used).
        """
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        tool_results: list[tuple[str, dict, str]] = []  # (tool_name, args, result)
        text_only_retried = False

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            if response.has_tool_calls:
                if on_progress:
                    clean = self._strip_think(response.content)
                    if clean:
                        await on_progress(clean, message_type="thinking")
                    await on_progress(self._tool_hint(response.tool_calls), message_type="action")

                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    tool_results.append((tool_call.name, tool_call.arguments, result))
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = self._strip_think(response.content)
                # Some models send an interim text response before tool calls.
                # Give them one retry; don't forward the text to avoid duplicates.
                if not tools_used and not text_only_retried and final_content:
                    text_only_retried = True
                    # Safe logging: handle None and encoding issues
                    safe_preview = (final_content[:80] if final_content else '<empty>')
                    logger.debug("Interim text response (no tools used yet), retrying: {}", safe_preview)
                    messages = self.context.add_assistant_message(
                        messages, response.content,
                        reasoning_content=response.reasoning_content,
                    )
                    final_content = None
                    continue
                break

        # Generate summary if tools were used but no final content
        if final_content is None and tool_results:
            final_content = self._generate_tool_summary(tool_results)

        # If still no content after all iterations, provide a helpful fallback
        if final_content is None:
            final_content = self._get_fallback_response(initial_messages)

        return final_content, tools_used

    def _generate_tool_summary(self, tool_results: list[tuple[str, dict, str]]) -> str:
        """
        Generate a summary of executed tools and their results.

        Args:
            tool_results: List of (tool_name, args, result) tuples.

        Returns:
            A formatted summary string.
        """
        lines = ["✅ Actions completed:\n"]

        for tool_name, args, result in tool_results:
            # Format tool name with emoji based on type
            emoji = self._get_tool_emoji(tool_name)

            # Format the action description
            action_desc = self._format_tool_action(tool_name, args)
            lines.append(f"{emoji} {action_desc}")

            # Add success/failure indication
            if result and isinstance(result, str):
                if "error" in result.lower() or "failed" in result.lower():
                    lines.append(f"   ❌ Failed: {result[:100]}{'...' if len(result) > 100 else ''}")
                elif tool_name in ("edit_file", "write_file"):
                    # File operations - show what was done
                    if "edited" in result.lower() or "written" in result.lower() or "success" in result.lower():
                        lines.append(f"   ✅ Success")
                elif tool_name == "exec":
                    # Command execution - show output snippet
                    if result.strip():
                        preview = result.strip().split('\n')[0][:80]
                        lines.append(f"   📤 {preview}{'...' if len(result) > 80 else ''}")

        return "\n".join(lines)

    def _get_tool_emoji(self, tool_name: str) -> str:
        """Get an emoji for a tool name."""
        emoji_map = {
            "read_file": "📖",
            "write_file": "✍️",
            "edit_file": "📝",
            "list_dir": "📁",
            "exec": "⚡",
            "web_search": "🔍",
            "web_fetch": "🌐",
            "message": "💬",
            "spawn": "🤖",
            "cron": "⏰",
            "research": "🔬",
        }
        return emoji_map.get(tool_name, "🔧")

    def _format_tool_action(self, tool_name: str, args: dict) -> str:
        """Format a tool action into a human-readable description."""
        if tool_name == "read_file":
            path = args.get("path", args.get("file_path", "unknown"))
            return f"Read file: `{path}`"
        elif tool_name == "write_file":
            path = args.get("path", args.get("file_path", "unknown"))
            return f"Wrote file: `{path}`"
        elif tool_name == "edit_file":
            path = args.get("path", args.get("file_path", "unknown"))
            return f"Edited file: `{path}`"
        elif tool_name == "list_dir":
            path = args.get("path", ".")
            return f"Listed directory: `{path}`"
        elif tool_name == "exec":
            cmd = args.get("command", "")
            return f"Executed: `{cmd[:60]}{'...' if len(cmd) > 60 else ''}`"
        elif tool_name == "web_search":
            query = args.get("query", "")
            return f"Searched: \"{query[:40]}{'...' if len(query) > 40 else ''}\""
        elif tool_name == "web_fetch":
            url = args.get("url", "")
            return f"Fetched: `{url[:50]}{'...' if len(url) > 50 else ''}`"
        elif tool_name == "spawn":
            agent_type = args.get("agent_type", "subagent")
            prompt = args.get("prompt", "")[:40]
            return f"Spawned {agent_type}: \"{prompt}...\""
        elif tool_name == "cron":
            schedule = args.get("schedule", args.get("cron_expression", ""))
            return f"Scheduled cron: `{schedule}`"
        elif tool_name == "research":
            query = args.get("query", "")
            return f"Researched: \"{query[:40]}{'...' if len(query) > 40 else ''}\""
        else:
            # Generic format
            arg_str = ", ".join(f"{k}={v}" for k, v in list(args.items())[:2])
            return f"{tool_name}({arg_str})"

    def _get_fallback_response(self, messages: list[dict]) -> str:
        """
        Generate a fallback response when the agent couldn't produce a proper response.
        Detects language from conversation history to provide appropriate message.
        """
        from nanobot.utils.language import detect_language_from_session

        # Detect language from conversation history
        language = detect_language_from_session(messages)

        # Fallback messages in different languages
        fallback_messages = {
            'vi': 'Xin lỗi, mình không chắc cách trả lời câu hỏi này. Bạn có thể thử đặt câu hỏi khác hoặc rõ hơn không?',
            'zh': '抱歉，我不确定如何回答这个问题。您可以尝试用不同的方式提问吗？',
            'ja': '申し訳ありませんが、この質問にどう答えるかよく分かりません。別の聞き方を試していただけますか？',
            'ko': '죄송합니다만, 이 질문에 어떻게 대답해야 할지 잘 모르겠습니다. 다른 방식으로 질문해 주시겠어요?',
            'es': 'Lo siento, no estoy seguro de cómo responder a esta pregunta. ¿Podrías intentarlo de otra manera?',
            'fr': 'Désolé, je ne suis pas sûr de savoir comment répondre à cette question. Pouvez-vous essayer autrement?',
            'de': 'Entschuldigung, ich bin mir nicht sicher, wie ich auf diese Frage antworten soll. Können Sie es anders versuchen?',
            'en': 'Sorry, I\'m not sure how to help with that. Could you try rephrasing your question?',
        }

        return fallback_messages.get(language, fallback_messages['en'])

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error("Error processing message: {}", e)
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue
    
    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")
    
    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str, str | None], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """
        Process a single inbound message.

        Args:
            msg: The inbound message to process.
            session_key: Override session key (used by process_direct).
            on_progress: Optional callback(content, message_type) for intermediate output.
                        Defaults to bus publish. message_type can be "thinking", "action",
                        or None for regular messages.

        Returns:
            The response message, or None if no response needed (e.g., tools executed
            but no text response generated).
        """
        # System messages route back via chat_id ("channel:chat_id")
        if msg.channel == "system":
            return await self._process_system_message(msg)

        # Safe preview that handles None content
        content = msg.content or ""
        preview = content[:80] + "..." if len(content) > 80 else content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)
        
        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)
        
        # Handle slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            # Detect language from conversation history
            language = detect_language_from_session(session.messages)

            # Capture messages before clearing (avoid race condition with background task)
            messages_to_archive = session.messages.copy()
            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)

            async def _consolidate_and_cleanup():
                temp_session = Session(key=session.key)
                temp_session.messages = messages_to_archive
                await self._consolidate_memory(temp_session, archive_all=True)

            asyncio.create_task(_consolidate_and_cleanup())
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=get_bot_message('new_session', language))
        if cmd == "/help":
            # Detect language from conversation history
            language = detect_language_from_session(session.messages)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=get_bot_message('help', language))
        
        if len(session.messages) > self.memory_window and session.key not in self._consolidating:
            self._consolidating.add(session.key)

            async def _consolidate_and_unlock():
                try:
                    await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)

            asyncio.create_task(_consolidate_and_unlock())

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        initial_messages = self.context.build_messages(
            history=session.get_history(max_messages=self.memory_window),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            system_prompt=self._custom_system_prompt,
            profile=self.profile_name,
            memory_isolation=self.memory_isolation,
            profile_inherit_base=self.profile_inherit_base,
            inherit_global_skills=self.inherit_global_skills,
        )

        async def _bus_progress(content: str, message_type: str | None = None) -> None:
            metadata = msg.metadata.copy() if msg.metadata else {}
            if message_type:
                metadata["message_type"] = message_type
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content,
                metadata=metadata,
            ))

        final_content, tools_used = await self._run_agent_loop(
            initial_messages, on_progress=on_progress or _bus_progress,
        )

        # final_content will be None only if no tools were used AND no text was generated
        # This can happen for empty/no-op messages

        # Safe preview that handles None
        safe_final = final_content or ""
        preview = safe_final[:120] + "..." if len(safe_final) > 120 else safe_final
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)

        # Log to monitor with None safety
        safe_inbound = msg.content or ""
        safe_outbound = final_content or ""
        self._log_monitor("inbound", safe_inbound[:200], session.key, msg.channel)
        self._log_monitor("outbound", safe_outbound[:200], session.key, msg.channel)

        session.add_message("user", msg.content)
        session.add_message("assistant", final_content,
                            tools_used=tools_used if tools_used else None)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata or {},  # Pass through for channel-specific needs (e.g. Slack thread_ts)
        )
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).
        
        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info("Processing system message from {}", msg.sender_id)
        
        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        self._set_tool_context(origin_channel, origin_chat_id, msg.metadata.get("message_id"))
        initial_messages = self.context.build_messages(
            history=session.get_history(max_messages=self.memory_window),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
            system_prompt=self._custom_system_prompt,
            profile=self.profile_name,
            memory_isolation=self.memory_isolation,
            profile_inherit_base=self.profile_inherit_base,
            inherit_global_skills=self.inherit_global_skills,
        )
        final_content, _ = await self._run_agent_loop(initial_messages)

        # No response needed if final_content is None
        if final_content is None:
            return None

        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def _consolidate_memory(self, session, archive_all: bool = False) -> None:
        """Consolidate old messages into MEMORY.md + HISTORY.md.

        Args:
            archive_all: If True, clear all messages and reset session (for /new command).
                       If False, only write to files without modifying session.
        """
        if not session.messages:
            return

        # Use profile-specific memory if profile is set
        profile = self.profile_name if self.memory_isolation != "shared" else None
        memory = MemoryStore(self.workspace, profile=profile)

        # Also get global memory for share_to_global logic
        global_memory = MemoryStore(self.workspace) if profile and self.profile_config and self.profile_config.share_to_global else None

        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info("Memory consolidation (archive_all): {} total messages archived", len(session.messages))
        else:
            keep_count = self.memory_window // 2
            if len(session.messages) <= keep_count:
                logger.debug("Session {}: No consolidation needed (messages={}, keep={})", session.key, len(session.messages), keep_count)
                return

            messages_to_process = len(session.messages) - session.last_consolidated
            if messages_to_process <= 0:
                logger.debug("Session {}: No new messages to consolidate (last_consolidated={}, total={})", session.key, session.last_consolidated, len(session.messages))
                return

            old_messages = session.messages[session.last_consolidated:-keep_count]
            if not old_messages:
                return
            logger.info("Memory consolidation started: {} total, {} new to consolidate, {} keep", len(session.messages), len(old_messages), keep_count)

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")
        conversation = "\n".join(lines)
        current_memory = memory.read_long_term(include_global=False)

        # Build consolidation prompt with profile context
        profile_hint = f"\nNOTE: This is for profile '{self.profile_name}'. Focus on facts relevant to this profile's context." if profile else ""
        prompt = f"""You are a memory consolidation agent. Process this conversation and return a JSON object with exactly two keys:

1. "history_entry": A paragraph (2-5 sentences) summarizing the key events/decisions/topics. Start with a timestamp like [YYYY-MM-DD HH:MM]. Include enough detail to be useful when found by grep search later.

2. "memory_update": The updated long-term memory content. Add any new facts: user location, preferences, personal info, habits, project context, technical decisions, tools/services used. If nothing new, return the existing content unchanged.

3. "global_memory_update" (optional): Only include if there are facts that should be shared across all profiles (e.g., critical user preferences, global settings). Otherwise omit this key.{profile_hint}

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{conversation}

**IMPORTANT**: Both values MUST be strings, not objects or arrays.

Example:
{{
  "history_entry": "[2026-02-14 22:50] User asked about...",
  "memory_update": "- Host: HARRYBOOK-T14P\n- Name: Nado"
}}

Respond with ONLY valid JSON, no markdown fences."""

        try:
            response = await self.provider.chat(
                messages=[
                    {"role": "system", "content": "You are a memory consolidation agent. Respond only with valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
            )
            text = (response.content or "").strip()
            if not text:
                logger.warning("Memory consolidation: LLM returned empty response, skipping")
                return
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json_repair.loads(text)
            if not isinstance(result, dict):
                logger.warning("Memory consolidation: unexpected response type, skipping. Response: {}", text[:200])
                return

            if entry := result.get("history_entry"):
                # Defensive: ensure entry is a string (LLM may return dict)
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                memory.append_history(entry)
            if update := result.get("memory_update"):
                # Defensive: ensure update is a string
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    memory.write_long_term(update)

            # Handle global memory update if share_to_global is enabled
            if global_memory:
                global_update = result.get("global_memory_update")
                if global_update:
                    current_global = global_memory.read_global_memory()
                    if global_update != current_global:
                        global_memory.write_global_memory(global_update)
                        logger.info("Shared key facts to global memory from profile '{}'", self.profile_name)

            if archive_all:
                session.last_consolidated = 0
            else:
                session.last_consolidated = len(session.messages) - keep_count
            logger.info("Memory consolidation done: {} messages, last_consolidated={}", len(session.messages), session.last_consolidated)
        except Exception as e:
            logger.error("Memory consolidation failed: {}", e)

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str, str | None], Awaitable[None]] | None = None,
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).

        Args:
            content: The message content.
            session_key: Session identifier (overrides channel:chat_id for session lookup).
            channel: Source channel (for tool context routing).
            chat_id: Source chat ID (for tool context routing).
            on_progress: Optional callback(content, message_type) for intermediate output.
                        message_type can be "thinking", "action", or None for regular messages.

        Returns:
            The agent's response.
        """
        await self._connect_mcp()
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )
        
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""
