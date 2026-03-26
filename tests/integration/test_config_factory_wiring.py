"""IT-18: build_agent with different config flags.

Verifies that the composition root produces a correctly wired AgentLoop
for both full and minimal configurations.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.agent import AgentConfig
from nanobot.providers.litellm_provider import LiteLLMProvider
from tests.integration.conftest import MODEL

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullConfig:
    def test_build_agent_returns_agent_loop(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        """build_agent with full config returns an AgentLoop instance."""
        config = AgentConfig(
            workspace=str(tmp_path),
            model=MODEL,
            max_iterations=5,
            planning_enabled=False,
            verification_mode="off",
            memory_enabled=True,
            delegation_enabled=True,
            skills_enabled=True,
        )
        loop = build_agent(bus=MessageBus(), provider=provider, config=config)

        assert isinstance(loop, AgentLoop)

    def test_full_config_has_tools(self, tmp_path: Path, provider: LiteLLMProvider) -> None:
        """Agent built with delegation enabled has a tool registry with tools."""
        config = AgentConfig(
            workspace=str(tmp_path),
            model=MODEL,
            max_iterations=5,
            planning_enabled=False,
            verification_mode="off",
            delegation_enabled=True,
        )
        loop = build_agent(bus=MessageBus(), provider=provider, config=config)

        assert loop.tools is not None
        # Should have at least basic filesystem tools
        assert loop.tools.has("read_file")


class TestMinimalConfig:
    def test_minimal_config_no_delegate_tool(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        """With delegation disabled, no 'delegate' tool is registered."""
        config = AgentConfig(
            workspace=str(tmp_path),
            model=MODEL,
            max_iterations=5,
            planning_enabled=False,
            verification_mode="off",
            delegation_enabled=False,
            memory_enabled=False,
            skills_enabled=False,
        )
        loop = build_agent(bus=MessageBus(), provider=provider, config=config)

        assert isinstance(loop, AgentLoop)
        assert not loop.tools.has("delegate")

    def test_memory_disabled_still_builds(self, tmp_path: Path, provider: LiteLLMProvider) -> None:
        """Agent builds successfully even with memory disabled."""
        config = AgentConfig(
            workspace=str(tmp_path),
            model=MODEL,
            max_iterations=5,
            planning_enabled=False,
            verification_mode="off",
            memory_enabled=False,
        )
        loop = build_agent(bus=MessageBus(), provider=provider, config=config)

        assert isinstance(loop, AgentLoop)
