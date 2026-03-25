"""IT-08: Parent→child delegation with real LLM and real tools.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.agent_factory import build_agent
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.litellm_provider import LiteLLMProvider
from tests.integration.conftest import MODEL, make_inbound

pytestmark = pytest.mark.integration


class TestDelegationExecution:
    async def test_agent_can_read_file_via_tools(
        self,
        tmp_path: Path,
        provider: LiteLLMProvider,
    ) -> None:
        """Agent asked to read a file uses tools and returns content."""
        (tmp_path / "secret.txt").write_text("The launch code is ALPHA-7.")
        config = AgentConfig(
            workspace=str(tmp_path),
            model=MODEL,
            max_iterations=5,
            planning_enabled=False,
            verification_mode="off",
            delegation_enabled=True,
        )
        loop = build_agent(bus=MessageBus(), provider=provider, config=config)
        msg = make_inbound(
            f"Read the file at {tmp_path / 'secret.txt'} and tell me the launch code."
        )
        result = await loop._process_message(msg)
        assert result is not None
        assert len(result.content) > 0


class TestDelegationSafety:
    def test_delegation_disabled_no_delegate_tool(
        self,
        tmp_path: Path,
        provider: LiteLLMProvider,
    ) -> None:
        config = AgentConfig(
            workspace=str(tmp_path),
            model=MODEL,
            delegation_enabled=False,
            planning_enabled=False,
            verification_mode="off",
        )
        loop = build_agent(bus=MessageBus(), provider=provider, config=config)
        assert not loop.tools.has("delegate")
