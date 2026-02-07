"""AgentActor: Pulsing actor wrapping the core agent processing engine."""

from collections.abc import AsyncIterator
from typing import Any

import pulsing as pul
from loguru import logger

from nanobot.actor.tool_loop import AgentChunk, run_tool_loop, run_tool_loop_stream
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.base import ToolContext
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import (
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    ListDirTool,
)
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.session import SessionManager


@pul.remote
class AgentActor:
    """
    The core agent processing engine as a Pulsing actor.

    Accepts a ``Config`` object — the actor knows how to extract what it
    needs.  All cross-actor communication uses Pulsing name resolution.
    """

    def __init__(
        self,
        config: Any,
        provider_name: str = "provider",
        scheduler_name: str = "scheduler",
    ):
        self.config = config
        self.workspace = config.workspace_path
        self.model = config.agents.defaults.model
        self.max_iterations = config.agents.defaults.max_tool_iterations
        self.brave_api_key = config.tools.web.search.api_key or None
        self.exec_config = config.tools.exec
        self.restrict_to_workspace = config.tools.restrict_to_workspace
        self.provider_name = provider_name
        self.scheduler_name = scheduler_name

        self._provider = None  # resolved lazily via Pulsing

        self.context = ContextBuilder(self.workspace)
        self.sessions = SessionManager(self.workspace)
        self.tools = ToolRegistry()

        self._register_default_tools()

    # ================================================================
    # Internal helpers
    # ================================================================

    async def _get_provider(self):
        """Resolve the ProviderActor via Pulsing (lazy, cached)."""
        if self._provider is None:
            from nanobot.actor.provider import ProviderActor

            self._provider = await ProviderActor.resolve(self.provider_name)
            if not self.model:
                self.model = self._provider.get_default_model()
        return self._provider

    async def _prepare(
        self, channel: str, chat_id: str, content: str, media: list[str] | None = None
    ):
        """Common preamble: session + provider + context + messages."""
        session_key = f"{channel}:{chat_id}"
        session = self.sessions.get_or_create(session_key)
        provider = await self._get_provider()
        ctx = ToolContext(channel=channel, chat_id=chat_id, agent_name="agent")
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=content,
            media=media,
            channel=channel,
            chat_id=chat_id,
        )
        return session, provider, ctx, messages

    def _save_turn(self, session, user_content: str, assistant_content: str):
        """Common epilogue: persist the turn to session."""
        session.add_message("user", user_content)
        session.add_message("assistant", assistant_content)
        self.sessions.save(session)

    def _register_default_tools(self) -> None:
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(ReadFileTool(allowed_dir=allowed_dir))
        self.tools.register(WriteFileTool(allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(allowed_dir=allowed_dir))
        self.tools.register(ListDirTool(allowed_dir=allowed_dir))
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            )
        )
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        self.tools.register(MessageTool())
        self.tools.register(
            SpawnTool(
                config=self.config,
                provider_name=self.provider_name,
            )
        )
        self.tools.register(CronTool(scheduler_name=self.scheduler_name))

    # ================================================================
    # Non-streaming entry point
    # ================================================================

    async def process(
        self,
        channel: str,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
    ) -> str:
        """Process a message and return the response text."""
        if channel == "system":
            return await self._process_system_message(sender_id, chat_id, content)

        logger.info(f"Processing from {channel}:{sender_id}: {content[:80]}")
        session, provider, ctx, messages = await self._prepare(
            channel, chat_id, content, media
        )

        result = await run_tool_loop(
            provider=provider,
            tools=self.tools,
            messages=messages,
            ctx=ctx,
            model=self.model,
            max_iterations=self.max_iterations,
        )

        logger.info(f"Response to {channel}:{sender_id}: {result[:120]}")
        self._save_turn(session, content, result)
        return result

    # ================================================================
    # Streaming entry point
    # ================================================================

    async def process_stream(
        self,
        channel: str,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
    ) -> AsyncIterator[AgentChunk]:
        """Process a message and yield streaming chunks."""
        logger.info(f"Processing (stream) from {channel}:{sender_id}: {content[:80]}")
        session, provider, ctx, messages = await self._prepare(
            channel, chat_id, content, media
        )

        full_text = ""
        async for chunk in run_tool_loop_stream(
            provider=provider,
            tools=self.tools,
            messages=messages,
            ctx=ctx,
            model=self.model,
            max_iterations=self.max_iterations,
        ):
            if chunk.kind == "token":
                full_text += chunk.text
            yield chunk

        self._save_turn(
            session,
            content,
            full_text or "I've completed processing but have no response to give.",
        )

    # ================================================================
    # Announce (subagent results)
    # ================================================================

    async def announce(
        self,
        origin_channel: str,
        origin_chat_id: str,
        content: str,
    ) -> str:
        """Process a subagent result announcement."""
        return await self._process_system_message(
            "subagent", f"{origin_channel}:{origin_chat_id}", content
        )

    async def _process_system_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
    ) -> str:
        logger.info(f"Processing system message from {sender_id}")

        if ":" in chat_id:
            origin_channel, origin_chat_id = chat_id.split(":", 1)
        else:
            origin_channel, origin_chat_id = "cli", chat_id

        session, provider, ctx, messages = await self._prepare(
            origin_channel,
            origin_chat_id,
            content,
        )

        result = await run_tool_loop(
            provider=provider,
            tools=self.tools,
            messages=messages,
            ctx=ctx,
            model=self.model,
            max_iterations=self.max_iterations,
        )

        self._save_turn(session, f"[System: {sender_id}] {content}", result)

        # Point-to-point delivery
        if origin_channel != "cli":
            try:
                import pulsing as pul

                ch = (await pul.resolve(f"channel.{origin_channel}")).as_any()
                await ch.send_text(origin_chat_id, result)
            except Exception as e:
                logger.error(f"Error sending announce to {origin_channel}: {e}")

        return result
