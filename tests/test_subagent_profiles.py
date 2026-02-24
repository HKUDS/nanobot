"""Tests for subagent profiles feature."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from nanobot.config.schema import SubagentProfile, AgentsConfig
from nanobot.agent.subagent import SubagentManager, _TOOL_BUILDERS
from nanobot.agent.tools.spawn import SpawnTool


# ── Schema Tests ──


class TestSubagentProfileSchema:
    """Test SubagentProfile configuration model."""

    def test_default_profile(self):
        p = SubagentProfile()
        assert p.tools == []
        assert p.disallowed_tools == []
        assert p.skills == []
        assert p.model is None
        assert p.temperature is None
        assert p.max_tokens is None
        assert p.max_iterations == 15
        assert p.description == ""

    def test_custom_profile(self):
        p = SubagentProfile(
            description="Web researcher",
            tools=["web_search", "web_fetch"],
            disallowed_tools=["exec"],
            skills=["summarize"],
            model="anthropic/claude-haiku-4-5",
            temperature=0.3,
            max_iterations=10,
        )
        assert p.description == "Web researcher"
        assert p.tools == ["web_search", "web_fetch"]
        assert p.disallowed_tools == ["exec"]
        assert p.skills == ["summarize"]
        assert p.model == "anthropic/claude-haiku-4-5"
        assert p.temperature == 0.3
        assert p.max_iterations == 10

    def test_agents_config_with_profiles(self):
        ac = AgentsConfig(
            subagent_profiles={
                "researcher": SubagentProfile(tools=["web_search"]),
                "coder": SubagentProfile(tools=["read_file", "write_file", "exec"]),
            }
        )
        assert len(ac.subagent_profiles) == 2
        assert "researcher" in ac.subagent_profiles
        assert "coder" in ac.subagent_profiles

    def test_agents_config_empty_profiles_backward_compat(self):
        ac = AgentsConfig()
        assert ac.subagent_profiles == {}

    def test_camel_case_alias(self):
        """Ensure camelCase config keys work (JSON config compat)."""
        ac = AgentsConfig.model_validate({
            "subagentProfiles": {
                "researcher": {"tools": ["web_search"], "maxIterations": 10}
            }
        })
        assert "researcher" in ac.subagent_profiles
        assert ac.subagent_profiles["researcher"].max_iterations == 10


# ── SubagentManager Tests ──


class TestSubagentManager:
    """Test SubagentManager profile-related methods."""

    def _make_manager(self, profiles=None):
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        bus = MagicMock()
        return SubagentManager(
            provider=provider,
            workspace=Path("/tmp/test-workspace"),
            bus=bus,
            profiles=profiles or {},
        )

    def test_get_profile_names_empty(self):
        mgr = self._make_manager()
        assert mgr.get_profile_names() == []

    def test_get_profile_names(self):
        profiles = {
            "researcher": SubagentProfile(description="Research"),
            "coder": SubagentProfile(description="Code"),
        }
        mgr = self._make_manager(profiles)
        names = mgr.get_profile_names()
        assert set(names) == {"researcher", "coder"}

    def test_get_profiles_description(self):
        profiles = {
            "researcher": SubagentProfile(
                description="Web research",
                tools=["web_search", "web_fetch"],
            ),
        }
        mgr = self._make_manager(profiles)
        desc = mgr.get_profiles_description()
        assert "researcher" in desc
        assert "Web research" in desc
        assert "web_search" in desc

    def test_resolve_profile_none(self):
        mgr = self._make_manager({"researcher": SubagentProfile()})
        assert mgr._resolve_profile(None) is None
        assert mgr._resolve_profile("") is None

    def test_resolve_profile_found(self):
        p = SubagentProfile(description="test")
        mgr = self._make_manager({"researcher": p})
        assert mgr._resolve_profile("researcher") is p

    def test_resolve_profile_unknown_returns_none(self):
        mgr = self._make_manager({"researcher": SubagentProfile()})
        assert mgr._resolve_profile("nonexistent") is None

    def test_build_tools_no_profile_gets_all(self):
        mgr = self._make_manager()
        tools = mgr._build_tools_for_profile(None)
        registered = {t.name for t in tools._tools.values()}
        assert registered == set(_TOOL_BUILDERS.keys())

    def test_build_tools_with_allow_list(self):
        p = SubagentProfile(tools=["web_search", "web_fetch"])
        mgr = self._make_manager()
        tools = mgr._build_tools_for_profile(p)
        registered = {t.name for t in tools._tools.values()}
        assert registered == {"web_search", "web_fetch"}

    def test_build_tools_with_deny_list(self):
        p = SubagentProfile(disallowed_tools=["exec", "web_search"])
        mgr = self._make_manager()
        tools = mgr._build_tools_for_profile(p)
        registered = {t.name for t in tools._tools.values()}
        assert "exec" not in registered
        assert "web_search" not in registered
        assert "read_file" in registered

    def test_build_tools_allow_and_deny(self):
        """Deny list takes precedence over allow list."""
        p = SubagentProfile(
            tools=["web_search", "web_fetch", "exec"],
            disallowed_tools=["exec"],
        )
        mgr = self._make_manager()
        tools = mgr._build_tools_for_profile(p)
        registered = {t.name for t in tools._tools.values()}
        assert registered == {"web_search", "web_fetch"}

    def test_build_tools_unknown_tool_skipped(self):
        p = SubagentProfile(tools=["web_search", "nonexistent_tool"])
        mgr = self._make_manager()
        tools = mgr._build_tools_for_profile(p)
        registered = {t.name for t in tools._tools.values()}
        assert registered == {"web_search"}

    def test_build_subagent_prompt_default(self):
        mgr = self._make_manager()
        prompt = mgr._build_subagent_prompt("do something")
        assert "Subagent" in prompt
        assert str(mgr.workspace) in prompt

    def test_build_subagent_prompt_with_profile_description(self):
        p = SubagentProfile(description="Expert web researcher")
        mgr = self._make_manager()
        prompt = mgr._build_subagent_prompt("do something", profile=p)
        assert "Expert web researcher" in prompt

    def test_load_skills_content_no_loader(self):
        mgr = self._make_manager()
        assert mgr._load_skills_content(["summarize"]) == ""

    def test_load_skills_content_with_loader(self):
        loader = MagicMock()
        loader.load_skill.return_value = "# Summarize\nSummarize stuff."
        mgr = self._make_manager()
        mgr._skills_loader = loader
        content = mgr._load_skills_content(["summarize"])
        assert "Summarize" in content
        assert "### Skill: summarize" in content
        loader.load_skill.assert_called_once_with("summarize")

    def test_load_skills_content_missing_skill(self):
        loader = MagicMock()
        loader.load_skill.return_value = None
        mgr = self._make_manager()
        mgr._skills_loader = loader
        content = mgr._load_skills_content(["nonexistent"])
        assert content == ""


# ── SpawnTool Tests ──


class TestSpawnToolProfiles:
    """Test SpawnTool profile parameter exposure."""

    def test_parameters_no_profiles(self):
        mgr = MagicMock()
        mgr.get_profile_names.return_value = []
        tool = SpawnTool(manager=mgr)
        params = tool.parameters
        assert "profile" not in params["properties"]

    def test_parameters_with_profiles(self):
        mgr = MagicMock()
        mgr.get_profile_names.return_value = ["researcher", "coder"]
        mgr.get_profiles_description.return_value = "- researcher: Web research\n- coder: Code"
        tool = SpawnTool(manager=mgr)
        params = tool.parameters
        assert "profile" in params["properties"]
        assert params["properties"]["profile"]["enum"] == ["researcher", "coder"]

    @pytest.mark.asyncio
    async def test_execute_passes_profile(self):
        mgr = MagicMock()
        mgr.spawn = AsyncMock(return_value="started")
        tool = SpawnTool(manager=mgr)
        tool.set_context("feishu", "chat123")
        result = await tool.execute(task="research AI", profile="researcher")
        mgr.spawn.assert_called_once_with(
            task="research AI",
            label=None,
            profile="researcher",
            origin_channel="feishu",
            origin_chat_id="chat123",
        )

    @pytest.mark.asyncio
    async def test_execute_no_profile(self):
        mgr = MagicMock()
        mgr.spawn = AsyncMock(return_value="started")
        tool = SpawnTool(manager=mgr)
        tool.set_context("cli", "direct")
        result = await tool.execute(task="do stuff")
        mgr.spawn.assert_called_once_with(
            task="do stuff",
            label=None,
            profile=None,
            origin_channel="cli",
            origin_chat_id="direct",
        )
