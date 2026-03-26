"""Agent loop: the core processing engine.

Orchestrates the Plan-Act-Observe-Reflect cycle, bus consumption, message
routing via the coordinator, and MCP lifecycle.  Turn execution is delegated
to ``TurnOrchestrator``; per-message processing to ``MessageProcessor``.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.callbacks import ProgressCallback
from nanobot.agent.reaction import classify_reaction
from nanobot.bus.events import DeliveryResult, InboundMessage, OutboundMessage, ReactionEvent
from nanobot.observability.langfuse import (
    flush as flush_langfuse,
)
from nanobot.observability.langfuse import (
    reset_trace_context,
    trace_request,
    update_current_span,
)
from nanobot.observability.tracing import TraceContext

if TYPE_CHECKING:
    from nanobot.agent.agent_components import _AgentComponents
    from nanobot.agent.message_processor import MessageProcessor
    from nanobot.coordination.coordinator import Coordinator


def _user_friendly_error(exc: Exception) -> str:
    """Map exceptions to actionable user-facing messages."""
    msg = str(exc).lower()
    if "context_length" in msg or "context window" in msg or "maximum context" in msg:
        return "Your conversation is too long. Use /new to start a fresh session."
    if "rate_limit" in msg or "429" in msg or "quota" in msg:
        return "I'm rate-limited right now. Please try again in a moment."
    if "auth" in msg and ("invalid" in msg or "denied" in msg or "missing" in msg):
        return "There's a configuration issue with the AI provider. Please contact the admin."
    return "Sorry, I couldn't process that. Please try again."


class AgentLoop:
    """Core processing engine for the nanobot agent.

    Receives ``_AgentComponents`` from ``build_agent()`` and orchestrates bus
    consumption, coordinator routing, MCP lifecycle, and message processing.
    """

    def __init__(self, *, components: _AgentComponents) -> None:
        # Config and identity
        self.bus = components.bus
        self.provider = components.provider
        self.config = components.config
        self.workspace = components.core.workspace
        self.model = components.core.model
        self.temperature = components.core.temperature
        self.max_iterations = components.core.max_iterations
        self.role_config = components.core.role_config
        self.role_name = components.core.role_name
        self.channels_config = components.infra.channels_config
        self.brave_api_key = components.infra.brave_api_key
        self.exec_config = components.infra.exec_config
        self.cron_service = components.infra.cron_service

        # Subsystems
        self.memory = components.subsystems.memory
        self.context = components.subsystems.context
        self.sessions = components.subsystems.sessions
        self.tools = components.subsystems.tools
        self._capabilities = components.subsystems.capabilities
        self.result_cache = components.subsystems.result_cache
        self.missions = components.subsystems.missions
        self._consolidator = components.subsystems.consolidator
        self._dispatcher = components.subsystems.dispatcher
        self._delegation_advisor = components.subsystems.delegation_advisor
        self._llm_caller = components.subsystems.llm_caller
        self._verifier = components.subsystems.verifier
        self._orchestrator = components.subsystems.orchestrator
        self._processor: MessageProcessor = components.subsystems.processor  # type: ignore[assignment]
        self._role_manager = components.role_manager

        # Routing
        self._routing_config = components.infra.routing_config
        self._mcp_servers = components.infra.mcp_servers
        self._mcp_connector = components.infra.mcp_connector

        # Runtime state (not constructed)
        self._running = False
        self._stop_event: asyncio.Event | None = None
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._coordinator: Coordinator | None = components.coordinator
        self._coordinator_wired = False
        self._delegation_stack: list[str] = []
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        if self._mcp_connector is None:
            return
        self._mcp_connecting = True
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await self._mcp_connector(
                self._mcp_servers,
                self._capabilities.tool_registry,
                self._mcp_stack,
            )
            self._mcp_connected = True
            # Share MCP tools with missions and delegation
            mcp_tools = [
                t
                for name in self._capabilities.tool_registry.tool_names
                if name.startswith("mcp_") and (t := self._capabilities.tool_registry.get(name))
            ]
            if mcp_tools:
                self.missions.mcp_tools = mcp_tools
                self._dispatcher.mcp_tools = mcp_tools
        except (RuntimeError, ConnectionError, OSError, TimeoutError, ImportError) as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except (RuntimeError, OSError):
                    pass  # best-effort cleanup; MCP stack may already be torn down
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def set_deliver_callback(
        self,
        callback: Callable[[OutboundMessage], Awaitable[DeliveryResult | None]],
    ) -> None:
        """Replace the MessageTool send callback with an honest delivery path."""
        if message_tool := self.tools.get("message"):
            if hasattr(message_tool, "set_send_callback"):
                message_tool.set_send_callback(callback)

    def set_contacts_provider(
        self,
        provider: Callable[[], list[str]],
    ) -> None:
        """Set a callback that returns known email contacts (refreshed per-turn)."""
        self._processor._turn_context.set_contacts_provider(provider)

    def set_email_fetch(
        self,
        fetch_callback: Callable[..., list[dict[str, Any]]],
        fetch_unread_callback: Callable[..., list[dict[str, Any]]],
    ) -> None:
        """Wire email fetch callbacks into the CheckEmailTool."""
        if tool := self.tools.get("check_email"):
            if hasattr(tool, "set_fetch_callbacks"):
                tool.set_fetch_callbacks(fetch_callback, fetch_unread_callback)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict[str, Any]],
        on_progress: ProgressCallback | None = None,
    ) -> tuple[str | None, list[str], list[dict[str, Any]]]:
        """Legacy shim: delegates to ``MessageProcessor._run_orchestrator``.

        Kept for backward compatibility with test callers.
        Returns ``(final_content, tools_used, messages)``.
        """
        result = await self._processor._run_orchestrator(initial_messages, on_progress)
        self._processor._sync_token_counters()
        self._turn_tokens_prompt = self._processor._turn_tokens_prompt
        self._turn_tokens_completion = self._processor._turn_tokens_completion
        self._turn_llm_calls = self._processor._turn_llm_calls
        return result

    async def handle_reaction(self, reaction: ReactionEvent) -> None:
        """Map an emoji reaction to a feedback event and persist it."""
        rating = classify_reaction(reaction.emoji)
        if rating is None:
            logger.debug("Ignoring unmapped reaction emoji: {}", reaction.emoji)
            return

        feedback_tool = self.tools.get("feedback")
        if feedback_tool is None:
            return

        feedback_tool.set_context(
            channel=reaction.channel,
            chat_id=reaction.chat_id,
            session_key=f"{reaction.channel}:{reaction.chat_id}",
        )
        result = await feedback_tool.execute(
            rating=rating,
            comment=f"emoji reaction: {reaction.emoji}",
            topic="",
        )
        if isinstance(result, str):
            outcome = result
        else:
            outcome = "ok" if result.success else (result.error or "error")
        logger.info(
            "Reaction {} from {}:{} → {}",
            reaction.emoji,
            reaction.channel,
            reaction.sender_id,
            outcome,
        )

    async def run(self) -> None:
        """Run the agent loop, consuming messages from the bus."""
        assert self._role_manager is not None, "build_agent() must wire _role_manager"
        self._running = True
        self._stop_event = asyncio.Event()
        await self._connect_mcp()
        self._wire_coordinator()
        if self.context.memory is not None:
            await (
                self.context.memory.maintenance.ensure_health()
            )  # LAN-101: non-blocking vector health

        logger.info("Agent loop started")

        # The consolidation orchestrator context enables submit() to schedule
        # background tasks.  __aexit__ drains all pending tasks on shutdown.
        async with self._consolidator:
            while self._running:
                try:
                    # Race consume_inbound against the stop event so that stop()
                    # wakes the loop immediately instead of waiting up to 5 s.
                    _consume = asyncio.create_task(self.bus.consume_inbound())
                    _stop_wait = asyncio.create_task(self._stop_event.wait())  # type: ignore[union-attr]
                    done, pending = await asyncio.wait(
                        {_consume, _stop_wait},
                        timeout=5.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
                    if not self._running or _stop_wait in done:
                        break
                    if _consume not in done:
                        # True timeout — no message, no stop signal
                        continue
                    msg = _consume.result()
                    # Set correlation IDs for this request
                    TraceContext.new_request(
                        session_id=msg.session_key,
                        agent_id=self.role_name,
                    )

                    # Detach any stale OTEL span context from a previous iteration
                    # to prevent context leaks that silently orphan all subsequent
                    # traces (see ADR-005 / Langfuse v4 hardening).
                    reset_trace_context()

                    try:
                        # Wrap entire request in a single trace
                        async with trace_request(
                            name="request",
                            input=msg.content[:200],
                            session_id=msg.session_key,
                            user_id=msg.sender_id,
                            tags=[msg.channel],
                            metadata={
                                "channel": msg.channel,
                                "sender": msg.sender_id,
                                "session_key": msg.session_key,
                                "model": self.model,
                                "role": self.role_name,
                            },
                        ):
                            # Wrap with timeout to prevent infinite processing
                            timeout = (
                                self.config.message_timeout
                                if self.config.message_timeout > 0
                                else None
                            )
                            try:
                                if timeout:
                                    response = await asyncio.wait_for(
                                        self._process_message(msg),
                                        timeout=timeout,
                                    )
                                else:
                                    response = await self._process_message(msg)
                            except asyncio.TimeoutError:
                                logger.error(
                                    "Message processing timed out after {}s for {}:{}",
                                    self.config.message_timeout,
                                    msg.channel,
                                    msg.chat_id,
                                )
                                update_current_span(
                                    output="TIMEOUT",
                                    metadata={"timeout_s": str(self.config.message_timeout)},
                                    level="ERROR",
                                )
                                response = OutboundMessage(
                                    channel=msg.channel,
                                    chat_id=msg.chat_id,
                                    content=(
                                        "Sorry, I ran out of time processing"
                                        " your request. "
                                        "Try breaking it into smaller steps."
                                    ),
                                )

                        if response is not None:
                            await self.bus.publish_outbound(response)
                        elif msg.channel in {"cli", "telegram"}:
                            await self.bus.publish_outbound(
                                OutboundMessage(
                                    channel=msg.channel,
                                    chat_id=msg.chat_id,
                                    content="",
                                    metadata=msg.metadata or {},
                                )
                            )

                        # Explicit flush: the gateway run() loop never calls
                        # shutdown_langfuse() during normal operation, so
                        # without this, traces rely on the OTEL
                        # BatchSpanProcessor timer.
                        # Flushing per-request guarantees delivery.
                        flush_langfuse()

                    except Exception as e:  # crash-barrier: message processing
                        logger.exception("Error processing message")
                        await self.bus.publish_outbound(
                            OutboundMessage(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                content=_user_friendly_error(e),
                            )
                        )
                except asyncio.TimeoutError:
                    continue

    def _wire_coordinator(self) -> None:
        """Wire delegate tools into the coordinator (after MCP tools are available)."""
        if self._coordinator is None:
            return
        if self._coordinator_wired:
            return
        self._coordinator_wired = True
        self._dispatcher.wire_delegate_tools(
            available_roles_fn=self._capabilities.role_names,
        )
        _registry = self._capabilities.agent_registry
        logger.info(
            "Multi-agent routing wired with {} roles",
            len(_registry) if _registry else 0,
        )

    async def close_mcp(self) -> None:
        """Close MCP connections and other async resources."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except RuntimeError:
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None
        try:
            await self.provider.aclose()
        except (RuntimeError, OSError, AttributeError) as e:
            logger.debug("Provider cleanup failed: {}", e)
        if hasattr(self, "memory") and self.memory.graph:
            try:
                await self.memory.graph.close()
            except (RuntimeError, OSError) as e:
                logger.debug("Graph driver cleanup failed: {}", e)

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> OutboundMessage | None:
        """Delegate to MessageProcessor."""
        return await self._processor._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: ProgressCallback | None = None,
        forced_role: str | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        assert self._role_manager is not None, "build_agent() must wire _role_manager"
        await self._connect_mcp()
        self._wire_coordinator()

        async with trace_request(
            name="request",
            input=content[:200],
            session_id=session_key,
            user_id="cli",
            tags=[channel],
            metadata={
                "channel": channel,
                "sender": "user",
                "session_key": session_key,
                "model": self.model,
                "role": self.role_name,
            },
        ):
            return await self._processor.process_direct(
                content, session_key, channel, chat_id, on_progress, forced_role
            )
