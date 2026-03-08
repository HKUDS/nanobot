from pathlib import Path
from typing import Awaitable, Callable

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ChannelsConfig, Config
from nanobot.cron.service import CronService
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import SessionManager


class NativeDispatcher:
    def __init__(
        self,
        *,
        bus: MessageBus,
        provider: LLMProvider,
        config: Config,
        cron_service: CronService | None = None,
        session_manager: SessionManager | None = None,
    ):
        self._loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=config.workspace_path,
            model=config.agents.defaults.model,
            temperature=config.agents.defaults.temperature,
            max_tokens=config.agents.defaults.max_tokens,
            max_iterations=config.agents.defaults.max_tool_iterations,
            memory_window=config.agents.defaults.memory_window,
            brave_api_key=config.tools.web.search.api_key or None,
            exec_config=config.tools.exec,
            cron_service=cron_service,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            session_manager=session_manager,
            mcp_servers=config.tools.mcp_servers,
            channels_config=config.channels,
        )

    @property
    def workspace(self) -> Path:
        return self._loop.workspace

    @property
    def channels_config(self) -> ChannelsConfig | None:
        return self._loop.channels_config

    async def run(self) -> None:
        await self._loop.run()

    def stop(self) -> None:
        self._loop.stop()

    async def close(self) -> None:
        await self._loop.close_mcp()

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        return await self._loop.process_direct(
            content,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            on_progress=on_progress,
        )
