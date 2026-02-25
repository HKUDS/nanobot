"""Tests for exec tool enable/disable configuration (issue #1013)."""

from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from nanobot.config.schema import ExecToolConfig
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.shell import ExecTool


def _make_agent_loop(exec_enabled: bool) -> AgentLoop:
    """Create an AgentLoop with minimal mocks for tool registration testing."""
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    config = ExecToolConfig(enabled=exec_enabled)
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=Path("/tmp/nanobot-test"),
        exec_config=config,
    )


def test_exec_tool_registered_by_default() -> None:
    loop = _make_agent_loop(exec_enabled=True)
    tool_names = [t.name for t in loop.tools._tools.values()]
    assert "exec" in tool_names


def test_exec_tool_not_registered_when_disabled() -> None:
    loop = _make_agent_loop(exec_enabled=False)
    tool_names = [t.name for t in loop.tools._tools.values()]
    assert "exec" not in tool_names


def test_exec_config_enabled_defaults_to_true() -> None:
    config = ExecToolConfig()
    assert config.enabled is True


def test_other_tools_still_registered_when_exec_disabled() -> None:
    loop = _make_agent_loop(exec_enabled=False)
    tool_names = [t.name for t in loop.tools._tools.values()]
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "list_dir" in tool_names
