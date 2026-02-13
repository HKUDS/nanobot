"""Agent loop: the core processing engine."""

import asyncio
import json
from pathlib import Path

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import MemoryStore
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import (
    AgentMemoryConfig,
    AgentSelfImprovementConfig,
    AgentSessionConfig,
    ExecToolConfig,
    WebToolsConfig,
)
from nanobot.cron.service import CronService
from nanobot.providers.base import LLMProvider
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
        agent_name: str = "nanobot",
        model: str | None = None,
        max_iterations: int = 20,
        reflect_after_tool_calls: bool = True,
        web_config: WebToolsConfig | None = None,
        exec_config: ExecToolConfig | None = None,
        memory_config: AgentMemoryConfig | None = None,
        self_improvement_config: AgentSelfImprovementConfig | None = None,
        session_config: AgentSessionConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
    ):
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.agent_name = agent_name.strip() or "nanobot"
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.reflect_after_tool_calls = reflect_after_tool_calls
        self.web_config = web_config or WebToolsConfig()
        self.exec_config = exec_config or ExecToolConfig()
        self.memory_config = memory_config or AgentMemoryConfig()
        self.self_improvement_config = self_improvement_config or AgentSelfImprovementConfig()
        self.session_config = session_config or AgentSessionConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.memory = MemoryStore(
            workspace=workspace,
            flush_every_updates=self.memory_config.flush_every_updates,
            flush_interval_seconds=self.memory_config.flush_interval_seconds,
            short_term_turns=self.memory_config.short_term_turns,
            pending_limit=self.memory_config.pending_limit,
            self_improvement_enabled=self.self_improvement_config.enabled,
            max_lessons_in_prompt=self.self_improvement_config.max_lessons_in_prompt,
            min_lesson_confidence=self.self_improvement_config.min_lesson_confidence,
            max_lessons=self.self_improvement_config.max_lessons,
            lesson_confidence_decay_hours=self.self_improvement_config.lesson_confidence_decay_hours,
            feedback_max_message_chars=self.self_improvement_config.feedback_max_message_chars,
            feedback_require_prefix=self.self_improvement_config.feedback_require_prefix,
            promotion_enabled=self.self_improvement_config.promotion_enabled,
            promotion_min_users=self.self_improvement_config.promotion_min_users,
            promotion_triggers=self.self_improvement_config.promotion_triggers,
        )
        self.context = ContextBuilder(
            workspace,
            memory_store=self.memory,
            agent_name=self.agent_name,
        )
        self.sessions = session_manager or SessionManager(
            workspace,
            compact_threshold_messages=self.session_config.compact_threshold_messages,
            compact_threshold_bytes=self.session_config.compact_threshold_bytes,
            compact_keep_messages=self.session_config.compact_keep_messages,
        )
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            web_config=self.web_config,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools (restrict to workspace if configured)
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(ReadFileTool(allowed_dir=allowed_dir))
        self.tools.register(WriteFileTool(allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(allowed_dir=allowed_dir))
        self.tools.register(ListDirTool(allowed_dir=allowed_dir))

        # Shell tool
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            )
        )

        # Web tools
        self.tools.register(
            WebSearchTool(
                provider=self.web_config.search.provider,
                api_key=self.web_config.search.api_key or None,
                max_results=self.web_config.search.max_results,
                ollama_api_key=self.web_config.search.ollama_api_key or None,
                ollama_api_base=self.web_config.search.ollama_api_base,
            )
        )
        self.tools.register(
            WebFetchTool(
                provider=self.web_config.fetch.provider,
                ollama_api_key=self.web_config.fetch.ollama_api_key or None,
                ollama_api_base=self.web_config.fetch.ollama_api_base,
            )
        )

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
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)

                # Process it
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Send error response
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=f"Sorry, I encountered an error: {str(e)}",
                        )
                    )
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        """Stop the agent loop."""
        self.memory.flush(force=True)
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

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}: {preview}")

        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)
        previous_assistant = self._get_last_assistant_message(session)

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
                messages=messages, tools=self.tools.get_definitions(), model=self.model
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
                            "arguments": json.dumps(tc.arguments),  # Must be JSON string
                        },
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )

                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    tool_impl = self.tools.get(tool_call.name)
                    provider = getattr(tool_impl, "provider", None)
                    provider_tag = f" [provider={provider}]" if provider else ""
                    logger.info(f"Tool call: {tool_call.name}{provider_tag}({args_str[:200]})")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    self.memory.record_tool_feedback(msg.session_key, tool_call.name, result)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
                if self.reflect_after_tool_calls:
                    # Optional reflection prompt between tool rounds.
                    messages.append(
                        {"role": "user", "content": "Reflect on the results and decide next steps."}
                    )
            else:
                # No tool calls, we're done
                final_content = response.content
                break

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        # Log response preview
        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info(f"Response to {msg.channel}:{msg.sender_id}: {preview}")

        # Update memory state
        self.memory.record_turn(
            session_key=msg.session_key,
            user_message=msg.content,
            assistant_message=final_content,
        )
        self.memory.record_user_feedback(
            session_key=msg.session_key,
            user_message=msg.content,
            previous_assistant=previous_assistant,
            actor_key=msg.sender_id,
        )
        self.memory.flush_if_needed()

        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata
            or {},  # Pass through for channel-specific needs (e.g. Slack thread_ts)
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
                messages=messages, tools=self.tools.get_definitions(), model=self.model
            )

            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )

                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    tool_impl = self.tools.get(tool_call.name)
                    provider = getattr(tool_impl, "provider", None)
                    provider_tag = f" [provider={provider}]" if provider else ""
                    logger.info(f"Tool call: {tool_call.name}{provider_tag}({args_str[:200]})")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    self.memory.record_tool_feedback(session_key, tool_call.name, result)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
                if self.reflect_after_tool_calls:
                    # Optional reflection prompt between tool rounds.
                    messages.append(
                        {"role": "user", "content": "Reflect on the results and decide next steps."}
                    )
            else:
                final_content = response.content
                break

        if final_content is None:
            final_content = "Background task completed."

        self.memory.record_turn(
            session_key=session_key,
            user_message=msg.content,
            assistant_message=final_content,
        )
        self.memory.flush_if_needed()

        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        return OutboundMessage(
            channel=origin_channel, chat_id=origin_chat_id, content=final_content
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
            content=content,
            session_key_override=session_key,
        )

        response = await self._process_message(msg)
        return response.content if response else ""

    @staticmethod
    def _get_last_assistant_message(session) -> str:
        """Get the last assistant message from a session, if available."""
        for item in reversed(session.messages):
            if item.get("role") == "assistant":
                return str(item.get("content", ""))
        return ""
