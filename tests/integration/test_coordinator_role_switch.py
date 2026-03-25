"""IT-09: Coordinator classification → role switch → process → restore.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""

from __future__ import annotations

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import AgentRoleConfig

pytestmark = pytest.mark.integration


class TestRoleSwitchingIntegration:
    def test_role_config_changes_model(self, agent: AgentLoop) -> None:
        role = AgentRoleConfig(
            name="code",
            model="code-specialist-model",
            temperature=0.1,
        )
        assert agent._role_manager is not None
        ctx = agent._role_manager.apply(role)
        assert agent.model == "code-specialist-model"
        assert agent.temperature == 0.1
        agent._role_manager.reset(ctx)

    def test_denied_tools_excluded(self, agent: AgentLoop) -> None:
        role = AgentRoleConfig(
            name="research",
            denied_tools=["exec", "write_file", "edit_file"],
        )
        assert agent._role_manager is not None
        ctx = agent._role_manager.apply(role)
        defs = agent.tools.get_definitions()
        tool_names = [d["function"]["name"] for d in defs]
        assert "exec" not in tool_names
        assert "write_file" not in tool_names
        agent._role_manager.reset(ctx)

    def test_role_switch_restores_original(self, agent: AgentLoop) -> None:
        original_model = agent.model
        original_temp = agent.temperature
        role = AgentRoleConfig(name="specialist", model="other-model", temperature=0.0)
        assert agent._role_manager is not None
        ctx = agent._role_manager.apply(role)
        agent._role_manager.reset(ctx)
        assert agent.model == original_model
        assert agent.temperature == original_temp
