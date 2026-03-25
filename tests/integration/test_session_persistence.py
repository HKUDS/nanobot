"""IT-06: Session persistence across agent restarts.

Verifies that conversation history survives agent teardown and
reconstruction, and that SessionManager correctly persists and
reloads session data.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.agent_factory import build_agent
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.session.manager import SessionManager
from tests.integration.conftest import make_inbound

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    async def test_history_persists_across_agent_instances(
        self,
        tmp_path: Path,
        provider: LiteLLMProvider,
        config: AgentConfig,
    ) -> None:
        """Messages processed by one agent instance are recalled by a second."""
        # Override workspace so both agents share the same directory.
        shared_workspace = tmp_path / "shared"
        shared_workspace.mkdir()
        shared_config = config.model_copy(update={"workspace": str(shared_workspace)})

        # --- First agent: process a distinctive message ---
        agent1 = build_agent(bus=MessageBus(), provider=provider, config=shared_config)
        msg1 = make_inbound("My absolute favorite color is cerulean blue.")
        result1 = await agent1._process_message(msg1)
        assert result1 is not None, "first agent should produce a response"

        # --- Second agent: same workspace, ask about the color ---
        agent2 = build_agent(bus=MessageBus(), provider=provider, config=shared_config)
        msg2 = make_inbound("What is my favorite color?")
        result2 = await agent2._process_message(msg2)
        assert result2 is not None, "second agent should produce a response"
        assert "cerulean" in result2.content.lower(), (
            f"Expected 'cerulean' in second agent's response, got: {result2.content}"
        )

    def test_session_manager_reload(self, tmp_path: Path) -> None:
        """SessionManager persists messages and reloads them from a fresh instance."""
        workspace = tmp_path / "sessions-test"
        workspace.mkdir()

        # --- First manager: create session and save ---
        mgr1 = SessionManager(workspace)
        session = mgr1.get_or_create("test:reload")
        session.add_message("user", "Remember that pi is approximately 3.14159")
        session.add_message("assistant", "Noted! Pi is approximately 3.14159.")
        mgr1.save(session)

        # --- Second manager: load from same workspace ---
        mgr2 = SessionManager(workspace)
        reloaded = mgr2.get_or_create("test:reload")

        assert len(reloaded.messages) == 2, (
            f"Expected 2 messages after reload, got {len(reloaded.messages)}"
        )
        contents = " ".join(m.get("content", "") for m in reloaded.messages).lower()
        assert "3.14159" in contents, f"Expected '3.14159' in reloaded messages, got: {contents}"
