from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.self import MyTool
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import GenerationSettings
from nanobot.session.manager import SessionManager


@pytest.mark.asyncio
async def test_agent_loop_registers_persistent_focus_provider(tmp_path):
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("test:chat")
    session.metadata["_focus"] = "Continue the migration review."
    sessions.save(session)

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        session_manager=sessions,
        tools_config=ToolsConfig(),
    )
    try:
        tool = loop.tools.get("my")
        assert isinstance(tool, MyTool)
        assert tool.runtime_context_provider() is not None

        blocks = await loop._resolve_runtime_context_for_request(
            RequestContext(
                channel="test",
                chat_id="chat",
                session_key="test:chat",
            ),
            loop.tools,
        )

        focus_blocks = [block for block in blocks if block.source == "focus"]
        assert len(focus_blocks) == 1
        assert "Continue the migration review." in focus_blocks[0].content
    finally:
        await loop.aclose()
