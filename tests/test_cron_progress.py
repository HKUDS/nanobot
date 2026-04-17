"""Test that cron jobs suppress progress messages when on_progress is provided."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus


@pytest.fixture
def agent_with_bus(tmp_path):
    """Create an AgentLoop with a mock bus to track outbound messages."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("test")
    (workspace / "USER.md").write_text("test")
    (workspace / "AGENTS.md").write_text("test")

    bus = MagicMock(spec=MessageBus)
    bus.publish_outbound = AsyncMock()

    provider = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "done"
    mock_response.has_tool_calls = False
    mock_response.tool_calls = []
    mock_response.reasoning_content = None
    provider.chat_with_retry = AsyncMock(return_value=mock_response)

    agent = AgentLoop(
        provider=provider,
        model="test/model",
        workspace=workspace,
        bus=bus,
    )
    return agent, bus


@pytest.mark.asyncio
async def test_process_direct_with_on_progress_does_not_publish_to_bus(agent_with_bus):
    """When on_progress is provided, the bus should NOT receive progress messages.

    This is the scenario for cron jobs: passing a no-op callback prevents
    intermediate agent thoughts from being sent to the user's channel.
    """
    agent, bus = agent_with_bus

    progress_calls = []

    async def capture_progress(content: str, **kwargs) -> None:
        progress_calls.append(content)

    # Patch session save to avoid JSON serialization of mock objects
    with patch.object(agent.sessions, "save"):
        await agent.process_direct(
            "test message",
            session_key="cron:test",
            channel="telegram",
            chat_id="12345",
            on_progress=capture_progress,
        )

    # The bus should NOT have received any progress messages
    for call in bus.publish_outbound.call_args_list:
        msg = call.args[0]
        assert not msg.metadata.get("_progress", False), (
            "Bus received a progress message despite on_progress callback being provided"
        )
