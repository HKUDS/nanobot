"""Test AgentLoop with multi-directory whitelist."""

import tempfile
from pathlib import Path

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse


class MockProvider(LLMProvider):
    """Mock provider for testing."""
    def get_default_model(self) -> str:
        return "test/model"

    async def chat(self, *args, **kwargs):
        return LLMResponse(content="test", has_tool_calls=False)


def test_agent_loop_init_with_allowed_dirs() -> None:
    """Test that AgentLoop can be initialized with allowed_dirs."""
    with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as extra:
        workspace_path = Path(workspace).resolve()
        extra_path = Path(extra).resolve()

        bus = MessageBus()
        provider = MockProvider()

        # Should accept allowed_dirs parameter
        agent = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=workspace_path,
            restrict_to_workspace=True,
            allowed_dirs=[str(extra_path)]
        )

        # Tools should have the allowed directories set
        read_tool = agent.tools.get("read_file")
        assert read_tool is not None
        assert hasattr(read_tool, "_allowed_dirs")
        # Workspace + extra should be in allowed dirs
        assert len(read_tool._allowed_dirs) == 2


def test_subagent_manager_with_allowed_dirs() -> None:
    """Test that SubagentManager can be initialized with allowed_dirs."""
    from nanobot.agent.subagent import SubagentManager

    with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as extra:
        workspace_path = Path(workspace).resolve()
        extra_path = Path(extra).resolve()

        bus = MessageBus()
        provider = MockProvider()

        # Just check that the parameter is accepted
        # (we don't need to fully test subagent execution)
        subagent_mgr = SubagentManager(
            provider=provider,
            workspace=workspace_path,
            bus=bus,
            restrict_to_workspace=True,
            allowed_dirs=[str(extra_path)]
        )
        assert subagent_mgr is not None
