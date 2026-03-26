"""IT-12: Answer verifier inside agent processing.

Tests that verification_mode controls answer verification behavior
with a real LLM provider.

Requires: LLM API key in ~/.nanobot/config.json or env var.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.litellm_provider import LiteLLMProvider
from tests.integration.conftest import MODEL, make_inbound

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVerificationOff:
    async def test_off_mode_returns_answer(self, agent: AgentLoop) -> None:
        """With verification_mode='off', agent returns a direct answer."""
        msg = make_inbound("What is 2+2?")
        result = await agent._process_message(msg)

        assert result is not None
        assert len(result.content) > 0
        assert "4" in result.content


class TestVerificationAlways:
    async def test_always_mode_produces_correct_answer(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        """With verification_mode='always', agent still produces a correct answer."""
        config = AgentConfig(
            workspace=str(tmp_path),
            model=MODEL,
            memory_window=10,
            max_iterations=5,
            planning_enabled=False,
            verification_mode="always",
            memory_enabled=False,
            graph_enabled=False,
            reranker_mode="disabled",
        )
        bus = MessageBus()
        agent = build_agent(bus=bus, provider=provider, config=config)

        msg = make_inbound("What is the capital of France?")
        result = await agent._process_message(msg)

        assert result is not None
        assert "paris" in result.content.lower(), (
            f"Expected 'paris' in response, got: {result.content}"
        )
