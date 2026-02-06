"""Agent loop: the core processing engine."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.providers.base import LLMProvider
from nanobot.session.compaction import CompactionConfig as SessionCompactionConfig
from nanobot.session.compaction import SessionCompactor
from nanobot.session.manager import SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import (
        CompactionConfig,
        ContextConfig,
        ExecToolConfig,
        MCPConfig,
        MemoryConfig,
        MemoryExtractionConfig,
    )
    from nanobot.cron.service import CronService
    from nanobot.mcp import MCPManager
    from nanobot.memory.vectors import VectorStore
    from nanobot.providers.resolver import ProviderResolver
    from nanobot.session.manager import Session


def _truncate_at_sentence(text: str, max_chars: int = 300) -> str:
    """Truncate text at the nearest sentence boundary within max_chars.

    Looks for sentence-ending punctuation (.!?) followed by a space or end
    of string. If no sentence boundary is found, falls back to a hard cut.
    """
    if len(text) <= max_chars:
        return text

    # Search for the last sentence boundary within max_chars
    truncated = text[:max_chars]
    for i in range(len(truncated) - 1, -1, -1):
        if truncated[i] in ".!?" and (i + 1 >= len(truncated) or truncated[i + 1] == " "):
            return truncated[: i + 1]

    # No sentence boundary found, hard truncate with ellipsis
    return truncated[:max_chars] + "..."


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
        channel_manager: ChannelManager | None = None,
        cron_service: "CronService | None" = None,
        mcp_config: "MCPConfig | None" = None,
        context_config: "ContextConfig | None" = None,
        compaction_config: "CompactionConfig | None" = None,
        memory_config: "MemoryConfig | None" = None,
        provider_resolver: "ProviderResolver | None" = None,
        memory_extraction: "MemoryExtractionConfig | None" = None,
    ):
        from nanobot.config.schema import (
            CompactionConfig,
            ContextConfig,
            ExecToolConfig,
            MCPConfig,
            MemoryConfig,
        )

        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.channel_manager = channel_manager
        self.cron_service = cron_service
        self.mcp_config = mcp_config or MCPConfig()
        self.context_config = context_config or ContextConfig()
        self.compaction_config = compaction_config or CompactionConfig()
        self.memory_config = memory_config or MemoryConfig()
        self.provider_resolver = provider_resolver

        # Memory extraction config
        from nanobot.config.schema import MemoryExtractionConfig

        self._extraction_config = memory_extraction or MemoryExtractionConfig()

        # Vector store for semantic memory (initialized in run())
        self.vector_store: "VectorStore | None" = None
        # Core memory (initialized in _init_memory())
        self.core_memory = None
        # Entity store (initialized in _init_memory())
        self.entity_store = None
        # Proactive memory (initialized in _init_memory())
        self.proactive_memory = None

        self.context = ContextBuilder(
            workspace,
            memory_enabled=self.memory_config.enabled,
        )
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()

        # Memory extraction and consolidation (lightweight vector store)
        self._extractor = None
        self._consolidator = None
        self._session_compactor = SessionCompactor(
            config=SessionCompactionConfig(),
        )
        self._extraction_interval = self._extraction_config.extraction_interval
        self._enable_pre_compaction_flush = self._extraction_config.enable_pre_compaction_flush
        self._enable_tool_lessons = self._extraction_config.enable_tool_lessons

        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
        )

        # MCP manager (initialized in run())
        self.mcp_manager: "MCPManager | None" = None

        # Cache for subsystem-specific LLM providers
        self._provider_cache: dict[str, LLMProvider] = {}

        # Serializes daemon execution with user message processing
        self._processing_lock = asyncio.Lock()

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
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.exec_config.restrict_to_workspace,
            )
        )

        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())

        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)

        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)

        # Tmux tool (persistent shell sessions)
        from nanobot.agent.tools.tmux import TmuxTool

        self.tools.register(TmuxTool())

        # Cron tool (for self-scheduling)
        if self.cron_service:
            from nanobot.agent.tools.cron import CronTool

            self.tools.register(CronTool(cron_service=self.cron_service))

        # Discord config tool (if Discord channel is enabled)
        if self.channel_manager and "discord" in self.channel_manager.channels:
            from nanobot.agent.tools.discord_config import DiscordSetNotificationChannelTool
            from nanobot.channels.discord import DiscordChannel

            discord_channel = self.channel_manager.channels["discord"]
            if isinstance(discord_channel, DiscordChannel):
                self.tools.register(DiscordSetNotificationChannelTool(discord_channel))

        # MCP install tool (always available for self-installation)
        from nanobot.agent.tools.mcp_install import InstallMCPServerTool

        self.tools.register(InstallMCPServerTool(workspace=self.workspace))

    def _resolve_subsystem_provider(self, provider_name: str | None) -> LLMProvider:
        """Resolve an LLM provider for a subsystem (compaction, extraction, etc.).

        If ``provider_name`` is set and differs from the main provider, creates
        and caches a separate LiteLLMProvider with the appropriate credentials.
        Otherwise returns the main provider.

        Args:
            provider_name: Named provider from config, or None for main.

        Returns:
            An LLMProvider instance.
        """
        if not provider_name or not self.provider_resolver:
            return self.provider

        api_key, api_base = self.provider_resolver.resolve(provider_name)

        # If resolution yielded the same credentials as main, reuse it
        if api_key == self.provider.api_key and api_base == self.provider.api_base:
            return self.provider

        # Check cache
        cache_key = f"{provider_name}:{api_key}:{api_base}"
        if cache_key in self._provider_cache:
            return self._provider_cache[cache_key]

        # Create new provider
        from nanobot.providers.litellm_provider import LiteLLMProvider

        new_provider = LiteLLMProvider(
            api_key=api_key,
            api_base=api_base,
            default_model=self.model,
        )
        self._provider_cache[cache_key] = new_provider
        logger.debug(f"Created subsystem provider for '{provider_name}'")
        return new_provider

    def _truncate_tool_result(self, result: str) -> str:
        """Truncate tool result to fit within budget."""
        from nanobot.utils.tokens import count_tokens, truncate_to_token_limit

        max_tokens = self.context_config.tool_result_budget
        current_tokens = count_tokens(result)

        if current_tokens <= max_tokens:
            return result

        logger.debug(f"Truncating tool result from {current_tokens} to {max_tokens} tokens")
        return truncate_to_token_limit(result, max_tokens)

    def _check_context_budget(self, messages: list[dict]) -> None:
        """Log warnings if approaching context limits."""
        from nanobot.utils.tokens import count_messages_tokens

        total_tokens = count_messages_tokens(messages)
        max_tokens = self.context_config.max_context_tokens
        threshold = max_tokens * 0.9  # 90% warning threshold

        if total_tokens > threshold:
            logger.warning(
                f"Context approaching limit: {total_tokens}/{max_tokens} tokens "
                f"({total_tokens / max_tokens * 100:.1f}%)"
            )
        elif total_tokens > max_tokens * 0.8:
            logger.debug(f"Context at {total_tokens / max_tokens * 100:.1f}% capacity")

    async def _maybe_compact(
        self,
        messages: list[dict],
        session: "Session",
    ) -> list[dict]:
        """Run compaction if context is near capacity and compaction is enabled."""
        from nanobot.agent.compaction import MessageCompactor, should_compact

        if not self.compaction_config.enabled:
            return messages

        max_tokens = self.context_config.max_context_tokens
        threshold = self.compaction_config.threshold

        if not await should_compact(messages, max_tokens, threshold):
            return messages

        # Resolve compaction provider (may differ from main)
        compaction_provider = self._resolve_subsystem_provider(self.compaction_config.provider)

        # Create compactor
        compactor = MessageCompactor(
            provider=compaction_provider,
            model=self.compaction_config.model or self.model,
            keep_recent=self.compaction_config.keep_recent,
        )

        # Get previous rolling summary
        previous_summary = session.get_rolling_summary()

        # Run compaction
        target_tokens = int(max_tokens * 0.6)  # Compact to 60% capacity
        compacted, new_summary = await compactor.compact_messages(
            messages, target_tokens, previous_summary
        )

        # Store new rolling summary
        if new_summary != previous_summary:
            session.set_rolling_summary(new_summary)

        return compacted

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True

        # Initialize MCP if enabled
        await self._init_mcp()

        # Initialize memory if enabled
        self._init_memory()

        # Initialize memory extraction pipeline
        self._init_extraction()

        # Check for restart signal (e.g., after MCP server installation)
        await self._check_restart_signal()

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
                    # Send error response (include metadata for reaction/typing cleanup)
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=f"Sorry, I encountered an error: {str(e)}",
                            metadata=msg.metadata,
                        )
                    )
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False

        # Stop MCP servers
        if self.mcp_manager:
            await self.mcp_manager.stop()

        # Close extraction vector store
        if self._consolidator and hasattr(self._consolidator, "store"):
            try:
                self._consolidator.store.close()
            except Exception:
                pass

        logger.info("Agent loop stopping")

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a single inbound message.

        Acquires processing lock to serialize with daemon execution.

        Args:
            msg: The inbound message to process.

        Returns:
            The response message, or None if no response needed.
        """
        async with self._processing_lock:
            return await self._process_message_unlocked(msg)

    async def _process_message_unlocked(self, msg: InboundMessage) -> OutboundMessage | None:
        """Inner message processing (called under lock)."""
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)

        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")

        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)

        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)

        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)

        # Update cron tool context
        from nanobot.agent.tools.cron import CronTool

        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(msg.channel, msg.chat_id)

        # Update MCP install tool context
        from nanobot.agent.tools.mcp_install import InstallMCPServerTool

        mcp_install_tool = self.tools.get("install_mcp_server")
        if isinstance(mcp_install_tool, InstallMCPServerTool):
            mcp_install_tool.set_context(msg.channel, msg.chat_id)

        # Extract channel context from metadata (e.g., Discord channel history)
        channel_context = msg.metadata.get("channel_context", "") if msg.metadata else ""

        # Auto-recall relevant memories
        memory_context = await self._auto_recall(msg.content)
        if memory_context:
            # Prepend memory context to channel context
            if channel_context:
                channel_context = f"{memory_context}\n\n{channel_context}"
            else:
                channel_context = memory_context

        # Build initial messages (use token-aware history)
        messages = self.context.build_messages(
            history=session.get_history(max_tokens=self.context_config.history_budget),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel_context=channel_context,
        )

        # Run compaction if needed
        messages = await self._maybe_compact(messages, session)

        # Agent loop
        iteration = 0
        final_content = None

        while iteration < self.max_iterations:
            iteration += 1

            # Check context budget before LLM call
            self._check_context_budget(messages)

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
                    messages, response.content, tool_call_dicts
                )

                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    # Truncate large tool results to fit within budget
                    result = self._truncate_tool_result(result)
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

        # Index conversation to memory (async, don't block response)
        await self._index_conversation(msg.session_key, msg.content, final_content)

        # Periodic extraction and consolidation of facts and lessons
        await self._maybe_extract_and_consolidate(session, msg.session_key)

        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content, metadata=msg.metadata
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

        # Update cron tool context
        from nanobot.agent.tools.cron import CronTool

        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(origin_channel, origin_chat_id)

        # Update MCP install tool context
        from nanobot.agent.tools.mcp_install import InstallMCPServerTool

        mcp_install_tool = self.tools.get("install_mcp_server")
        if isinstance(mcp_install_tool, InstallMCPServerTool):
            mcp_install_tool.set_context(origin_channel, origin_chat_id)

        # Build messages with the announce content (token-aware history)
        messages = self.context.build_messages(
            history=session.get_history(max_tokens=self.context_config.history_budget),
            current_message=msg.content,
        )

        # Run compaction if needed
        messages = await self._maybe_compact(messages, session)

        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None

        while iteration < self.max_iterations:
            iteration += 1

            # Check context budget before LLM call
            self._check_context_budget(messages)

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
                    messages, response.content, tool_call_dicts
                )

                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    # Truncate large tool results to fit within budget
                    result = self._truncate_tool_result(result)
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

        await self._maybe_extract_and_consolidate(session, session_key)

        return OutboundMessage(
            channel=origin_channel, chat_id=origin_chat_id, content=final_content
        )

    async def process_direct(self, content: str, session_key: str = "cli:direct") -> str:
        """
        Process a message directly (for CLI usage).

        Args:
            content: The message content.
            session_key: Session identifier.

        Returns:
            The agent's response.
        """
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=content)

        response = await self._process_message(msg)
        return response.content if response else ""

    async def _auto_recall(self, user_message: str) -> str | None:
        """
        Automatically search memory for context relevant to the user's message.

        Args:
            user_message: The user's incoming message.

        Returns:
            Relevant memory context, or None if disabled or no results.
        """
        if not self.memory_config.enabled or not self.memory_config.auto_recall:
            return None

        if not self.vector_store:
            return None

        try:
            memory_context: list[str] = []

            results = await self.vector_store.search(
                query=user_message,
                top_k=self.memory_config.search_top_k,
                min_similarity=self.memory_config.min_similarity,
                recency_weight=self.memory_config.recency_weight,
                type_weights={"fact": 1.2, "conversation": 1.0},
            )

            if results:
                memory_context.append("[Relevant memories from past conversations]")
                for r in results:
                    text = r.get("text", "")
                    text = _truncate_at_sentence(text, 300)
                    memory_context.append(f"- {text}")

            # Proactive reminders
            if self.proactive_memory:
                try:
                    reminders = await self.proactive_memory.get_reminders()
                    if reminders:
                        memory_context.append("\n[Upcoming reminders]")
                        for r in reminders:
                            memory_context.append(f"- {r}")
                except Exception as e:
                    logger.warning(f"Proactive reminders failed: {e}")

            return "\n".join(memory_context) if memory_context else None

        except Exception as e:
            logger.warning(f"Auto-recall failed: {e}")
            return None

    async def _index_conversation(
        self,
        session_key: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """
        Index a conversation turn to the vector store.

        Args:
            session_key: Session identifier.
            user_message: The user's message.
            assistant_message: The assistant's response.
        """
        if not self.memory_config.enabled or not self.memory_config.index_conversations:
            return

        if not self.vector_store:
            return

        try:
            # Create conversation turn text
            turn_text = f"User: {user_message}\nAssistant: {assistant_message}"

            # Sanitize before indexing
            from nanobot.memory.filters import sanitize_for_memory

            sanitized = sanitize_for_memory(turn_text)
            if sanitized is None:
                logger.debug("Conversation turn filtered by sanitization")
                return

            metadata = {
                "session_key": session_key,
                "type": "conversation",
            }

            await self.vector_store.add(sanitized, metadata)

            # Extract and index facts if enabled
            if self.memory_config.extract_facts:
                await self._extract_and_index_facts(
                    session_key,
                    user_message,
                    assistant_message,
                )

            # Extract entities if enabled
            if self.memory_config.enable_entities and self.entity_store:
                await self._extract_and_index_entities(
                    user_message,
                    assistant_message,
                )

            # Record interaction pattern for proactive learning
            if self.proactive_memory:
                try:
                    from datetime import datetime

                    self.proactive_memory.record_interaction_pattern(
                        session_key=session_key,
                        topic=user_message[:100],
                        timestamp=datetime.now().isoformat(),
                    )
                except Exception as e:
                    logger.debug(f"Pattern recording failed: {e}")

        except Exception as e:
            logger.warning(f"Failed to index conversation: {e}")

    async def _extract_and_index_facts(
        self,
        session_key: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Extract and index key facts from a conversation turn."""
        try:
            from nanobot.memory.extractor import FactExtractor

            # Use extraction model or fall back to compaction model or main model
            extraction_model = (
                self.memory_config.extraction_model or self.compaction_config.model or self.model
            )

            # Resolve extraction provider: extraction -> compaction -> main
            extraction_provider = self._resolve_subsystem_provider(
                self.memory_config.extraction_provider or self.compaction_config.provider
            )

            extractor = FactExtractor(
                provider=extraction_provider,
                model=extraction_model,
            )

            facts = await extractor.extract_from_turn(user_message, assistant_message)

            for fact in facts:
                metadata = {
                    "session_key": session_key,
                    "type": "fact",
                }
                await self.vector_store.add(fact, metadata)

            if facts:
                logger.debug(f"Indexed {len(facts)} facts from conversation")

        except Exception as e:
            logger.warning(f"Fact extraction failed: {e}")

    async def _extract_and_index_entities(
        self,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Extract entities and relations from a conversation turn."""
        if not self.entity_store:
            return

        try:
            extraction_model = (
                self.memory_config.extraction_model or self.compaction_config.model or self.model
            )

            # Resolve extraction provider: extraction -> compaction -> main
            extraction_provider = self._resolve_subsystem_provider(
                self.memory_config.extraction_provider or self.compaction_config.provider
            )

            prompt = (
                "Extract named entities and their relationships "
                "from this conversation.\n\n"
                f"User: {user_message}\nAssistant: {assistant_message}\n\n"
                "Output as JSON array of objects, each with:\n"
                '- "name": entity name\n'
                '- "type": one of person/project/organization/'
                "technology/location/other\n"
                '- "relations": array of '
                '{"relation": "verb", "target": "other entity name"}'
                " (optional)\n\n"
                "Only include clearly identified entities. "
                "If none, output [].\nJSON:"
            )

            response = await extraction_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                model=extraction_model,
                max_tokens=512,
                temperature=0.2,
            )

            content = (response.content or "").strip()

            # Handle markdown code blocks
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            entities = json.loads(content)
            if not isinstance(entities, list):
                return

            for entity in entities:
                name = entity.get("name", "").strip()
                etype = entity.get("type", "other").strip()
                if not name:
                    continue

                self.entity_store.upsert_entity(name, etype)

                for rel in entity.get("relations", []):
                    relation = rel.get("relation", "").strip()
                    target = rel.get("target", "").strip()
                    if relation and target:
                        self.entity_store.add_relation(name, relation, target)

            if entities:
                logger.debug(f"Extracted {len(entities)} entities from conversation")

        except (json.JSONDecodeError, Exception) as e:
            logger.debug(f"Entity extraction failed: {e}")

    def _init_memory(self) -> None:
        """Initialize semantic memory system."""
        if not self.memory_config.enabled:
            return

        try:
            from nanobot.agent.tools.memory_search import MemorySearchTool
            from nanobot.llm.embeddings import EmbeddingService
            from nanobot.memory.vectors import VectorStore

            # Resolve embedding provider credentials
            embed_key, embed_base = None, None
            if self.provider_resolver:
                embed_key, embed_base = self.provider_resolver.resolve(
                    self.memory_config.embedding_provider
                )
            else:
                embed_key = self.provider.api_key

            # Create embedding service
            embedding_service = EmbeddingService(
                model=self.memory_config.embedding_model,
                api_key=embed_key,
                api_base=embed_base,
            )

            # Create vector store
            self.vector_store = VectorStore(
                db_path=self.memory_config.db_path,
                embedding_service=embedding_service,
            )

            # Register memory search tool
            self.tools.register(MemorySearchTool(self.vector_store))

            # Initialize core memory if enabled
            if self.memory_config.enable_core_memory:
                try:
                    from nanobot.agent.tools.core_memory import (
                        CoreMemoryReadTool,
                        CoreMemoryUpdateTool,
                    )
                    from nanobot.memory.core import CoreMemory

                    self.core_memory = CoreMemory(self.workspace)
                    self.tools.register(CoreMemoryReadTool(self.core_memory))
                    self.tools.register(CoreMemoryUpdateTool(self.core_memory))
                    # Pass core memory to context builder
                    self.context.core_memory = self.core_memory
                    logger.debug("Core memory initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize core memory: {e}")

            # Initialize entity store if enabled
            if self.memory_config.enable_entities:
                try:
                    from nanobot.memory.entities import EntityStore

                    self.entity_store = EntityStore(
                        self.memory_config.entities_db_path,
                    )
                    logger.debug("Entity store initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize entity store: {e}")

            # Initialize proactive memory if enabled
            if self.memory_config.enable_proactive:
                try:
                    from nanobot.memory.proactive import ProactiveMemory

                    self.proactive_memory = ProactiveMemory(
                        vector_store=self.vector_store,
                        entity_store=self.entity_store,
                        data_dir=self.workspace / "memory",
                    )
                    logger.debug("Proactive memory initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize proactive memory: {e}")

            # Register memory forget tool
            try:
                from nanobot.agent.tools.memory_forget import (
                    MemoryForgetTool,
                )

                self.tools.register(MemoryForgetTool(self.vector_store))
            except Exception as e:
                logger.warning(f"Failed to register memory forget tool: {e}")

            logger.info(
                f"Memory initialized: {self.vector_store.count()} entries, "
                f"model={self.memory_config.embedding_model}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize memory: {e}")
            self.vector_store = None

    def _init_extraction(self) -> None:
        """Initialize the memory extraction/consolidation pipeline."""
        if not self._extraction_config.enabled:
            return

        try:
            from nanobot.agent.memory.consolidator import MemoryConsolidator
            from nanobot.agent.memory.extractor import MemoryExtractor
            from nanobot.agent.memory.store import (
                EmbeddingService,
                VectorMemoryStore,
            )

            cfg = self._extraction_config
            self._extractor = MemoryExtractor(
                model=cfg.extraction_model,
                max_facts=cfg.max_facts_per_extraction,
            )

            # Create a dedicated vector store for extracted facts
            from pathlib import Path

            vector_db_path = Path("memory") / "extraction_vectors.db"
            embedding_service = EmbeddingService(model=cfg.embedding_model)
            extraction_store = VectorMemoryStore(
                db_path=vector_db_path,
                base_dir=self.workspace,
                embedding_service=embedding_service,
                max_memories=cfg.max_memories,
            )

            # Resolve extraction provider if available
            extraction_provider = self._resolve_subsystem_provider(
                self.memory_config.extraction_provider
                if hasattr(self.memory_config, "extraction_provider")
                else None
            )

            self._consolidator = MemoryConsolidator(
                store=extraction_store,
                model=cfg.extraction_model,
                candidate_threshold=cfg.candidate_threshold,
                provider=(extraction_provider if extraction_provider != self.provider else None),
            )

            # Pass extractor to session compactor
            self._session_compactor = SessionCompactor(
                config=SessionCompactionConfig(),
                extractor=self._extractor,
            )

            logger.info(
                "Memory extraction initialized: model=%s, interval=%d",
                cfg.extraction_model,
                cfg.extraction_interval,
            )
        except Exception as e:
            logger.warning("Failed to initialize memory extraction: %s", e)
            self._extractor = None
            self._consolidator = None

    async def _pre_compaction_flush(
        self,
        history: list[dict[str, Any]],
        namespace: str,
    ) -> None:
        """Run silent memory extraction before compaction."""
        if not self._consolidator or not self._extractor or len(history) < 10:
            return
        try:
            extracted = await self._extractor.extract_for_pre_compaction(history)
            if extracted:
                await self._consolidator.consolidate(extracted, namespace)
                logger.debug(
                    "Pre-compaction flush: consolidated %d facts",
                    len(extracted),
                )
        except Exception as e:
            logger.warning("Pre-compaction memory flush failed: %s", e)

    async def _maybe_extract_and_consolidate(
        self,
        session: "Session",
        namespace: str,
    ) -> None:
        """Trigger extraction/consolidation when conditions are met."""
        if not self._consolidator or not self._extractor:
            return

        user_count = sum(1 for m in session.messages if m.get("role") == "user")
        if user_count <= 0 or user_count % self._extraction_interval != 0:
            return

        history = session.get_history()[-20:]
        await self._extract_and_consolidate(history, namespace)

    async def _extract_and_consolidate(
        self,
        messages: list[dict[str, Any]],
        namespace: str,
    ) -> None:
        """Extract facts and lessons from conversation and consolidate."""
        if not self._consolidator or not self._extractor:
            return

        try:
            # Facts
            extracted = await self._extractor.extract(messages)
            if extracted:
                await self._consolidator.consolidate(extracted, namespace)
                logger.debug("Extracted and consolidated %d facts", len(extracted))

            # Lessons (stored in dedicated namespace)
            lessons = await self._extractor.extract_lessons(messages)
            if lessons:
                await self._consolidator.consolidate(lessons, namespace)
                logger.debug("Extracted and consolidated %d lessons", len(lessons))

            # Tool-specific lessons
            if self._enable_tool_lessons:
                tool_lessons = self._extractor.extract_tool_lessons(messages)
                if tool_lessons:
                    await self._consolidator.consolidate(tool_lessons, namespace)
                    logger.debug(
                        "Extracted and consolidated %d tool lessons",
                        len(tool_lessons),
                    )
        except Exception as e:
            logger.warning("Memory extraction/consolidation failed: %s", e)

    async def _init_mcp(self) -> None:
        """Initialize MCP manager and register MCP tools."""
        if not self.mcp_config.enabled:
            return

        from nanobot.mcp import MCPManager, create_mcp_tool_proxies

        self.mcp_manager = MCPManager(self.mcp_config)
        await self.mcp_manager.start()

        # Register MCP tool proxies
        mcp_tools = create_mcp_tool_proxies(self.mcp_manager)
        for tool in mcp_tools:
            self.tools.register(tool)
            logger.debug(f"Registered MCP tool: {tool.name}")

        # Log any server errors for diagnosis
        for server_name, error in self.mcp_manager.server_errors.items():
            logger.warning(f"MCP server {server_name} failed: {error}")

        logger.info(f"MCP initialized: {len(mcp_tools)} tools available")

    async def _check_restart_signal(self) -> None:
        """Check for restart signal and schedule verification job if needed."""
        from nanobot.restart import check_and_clear_restart_signal

        signal = check_and_clear_restart_signal(self.workspace)
        if not signal:
            return

        logger.info(f"Restart signal detected: {signal.get('reason', 'unknown')}")

        # Schedule verification job if present
        verify_job = signal.get("verify_job")
        if verify_job and self.cron_service:
            from datetime import datetime

            from nanobot.cron.types import CronSchedule

            at_time = verify_job.get("at_time")
            if at_time:
                try:
                    dt = datetime.fromisoformat(at_time.replace("Z", "+00:00"))
                    at_ms = int(dt.timestamp() * 1000)

                    self.cron_service.add_job(
                        name=verify_job.get("name", "verify_mcp"),
                        schedule=CronSchedule(kind="at", at_ms=at_ms),
                        message=verify_job.get("message", "Verify MCP installation"),
                        deliver=verify_job.get("deliver", True),
                        channel=verify_job.get("channel"),
                        to=verify_job.get("to"),
                        delete_after_run=True,
                    )
                    logger.info(f"Scheduled verification job: {verify_job.get('name')}")
                except Exception as e:
                    logger.error(f"Failed to schedule verification job: {e}")
