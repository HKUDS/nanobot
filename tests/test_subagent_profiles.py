"""Tests for subagent profiles feature."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import SubagentProfile, AgentsConfig, Config
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.spawn import SpawnTool


# ---------------------------------------------------------------------------
# Config schema tests
# ---------------------------------------------------------------------------


def test_subagent_profile_defaults():
    """SubagentProfile has sensible defaults."""
    p = SubagentProfile()
    assert p.tools is None
    assert p.skills == []
    assert p.model is None
    assert p.max_iterations is None


def test_subagent_profile_full():
    """SubagentProfile accepts all fields."""
    p = SubagentProfile(
        tools=["read_file", "web_search"],
        skills=["summarization"],
        model="anthropic/claude-haiku-4-5",
        max_iterations=10,
    )
    assert p.tools == ["read_file", "web_search"]
    assert p.skills == ["summarization"]
    assert p.model == "anthropic/claude-haiku-4-5"
    assert p.max_iterations == 10


def test_agents_config_profiles_default_empty():
    """AgentsConfig defaults to empty subagent_profiles."""
    cfg = AgentsConfig()
    assert cfg.subagent_profiles == {}


def test_agents_config_profiles_from_dict():
    """AgentsConfig parses subagent_profiles from nested dict."""
    cfg = AgentsConfig(
        subagent_profiles={
            "researcher": SubagentProfile(
                tools=["web_search", "web_fetch"],
                skills=["summarization"],
                model="anthropic/claude-haiku-4-5",
                max_iterations=10,
            ),
            "coder": SubagentProfile(
                tools=["read_file", "write_file", "edit_file", "exec", "list_dir"],
                max_iterations=20,
            ),
        }
    )
    assert "researcher" in cfg.subagent_profiles
    assert "coder" in cfg.subagent_profiles
    assert cfg.subagent_profiles["researcher"].model == "anthropic/claude-haiku-4-5"
    assert cfg.subagent_profiles["coder"].tools == ["read_file", "write_file", "edit_file", "exec", "list_dir"]


def test_config_camel_case_alias():
    """Config accepts camelCase for subagentProfiles."""
    cfg = AgentsConfig.model_validate({
        "subagentProfiles": {
            "test": {"tools": ["read_file"], "maxIterations": 5}
        }
    })
    assert "test" in cfg.subagent_profiles
    assert cfg.subagent_profiles["test"].max_iterations == 5


# ---------------------------------------------------------------------------
# Spawn tool schema tests
# ---------------------------------------------------------------------------


def test_spawn_tool_has_profile_param():
    """SpawnTool schema includes profile parameter."""
    manager = MagicMock()
    tool = SpawnTool(manager=manager)
    params = tool.parameters
    assert "profile" in params["properties"]
    assert params["properties"]["profile"]["type"] == "string"
    assert "profile" not in params["required"]


# ---------------------------------------------------------------------------
# SubagentManager._build_tools tests
# ---------------------------------------------------------------------------


def _make_manager(**kwargs) -> SubagentManager:
    """Helper to create a SubagentManager with mocks."""
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    bus = MagicMock()
    workspace = Path("/tmp/test-workspace")
    return SubagentManager(
        provider=provider,
        workspace=workspace,
        bus=bus,
        **kwargs,
    )


def test_build_tools_no_profile():
    """Without a profile, all default tools are registered."""
    mgr = _make_manager()
    tools = mgr._build_tools(profile=None)
    expected = {"read_file", "write_file", "edit_file", "list_dir", "exec", "web_search", "web_fetch"}
    assert set(tools.tool_names) == expected


def test_build_tools_with_profile_filter():
    """Profile with explicit tool list only registers those tools."""
    profile = SubagentProfile(tools=["read_file", "web_search"])
    mgr = _make_manager()
    tools = mgr._build_tools(profile=profile)
    assert set(tools.tool_names) == {"read_file", "web_search"}


def test_build_tools_profile_empty_tools():
    """Profile with empty tools list registers nothing."""
    profile = SubagentProfile(tools=[])
    mgr = _make_manager()
    tools = mgr._build_tools(profile=profile)
    assert tools.tool_names == []


def test_build_tools_profile_tools_none_means_all():
    """Profile with tools=None registers all defaults."""
    profile = SubagentProfile(tools=None, model="fast-model")
    mgr = _make_manager()
    tools = mgr._build_tools(profile=profile)
    assert len(tools.tool_names) == 7


def test_build_tools_unknown_tool_skipped():
    """Unknown tool names in profile are skipped without error."""
    profile = SubagentProfile(tools=["read_file", "nonexistent_tool"])
    mgr = _make_manager()
    tools = mgr._build_tools(profile=profile)
    assert set(tools.tool_names) == {"read_file"}


# ---------------------------------------------------------------------------
# SubagentManager.spawn tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_unknown_profile_returns_error():
    """Spawning with an unknown profile name returns an error."""
    mgr = _make_manager(profiles={})
    result = await mgr.spawn(task="test", profile="nonexistent")
    assert "Error" in result
    assert "nonexistent" in result


@pytest.mark.asyncio
async def test_spawn_no_profile_works():
    """Spawning without a profile still works (backward compat)."""
    mgr = _make_manager()
    result = await mgr.spawn(task="do something")
    assert "started" in result
    # Let the background task clean up
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_spawn_valid_profile_starts():
    """Spawning with a valid profile name starts successfully."""
    profiles = {
        "researcher": SubagentProfile(
            tools=["web_search", "web_fetch"],
            model="fast-model",
            max_iterations=5,
        )
    }
    mgr = _make_manager(profiles=profiles)
    result = await mgr.spawn(task="research something", profile="researcher")
    assert "started" in result
    await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# _build_subagent_prompt tests
# ---------------------------------------------------------------------------


def test_prompt_lists_tools():
    """Subagent prompt includes available tool names."""
    mgr = _make_manager()
    profile = SubagentProfile(tools=["read_file", "web_search"])
    tools = mgr._build_tools(profile)
    prompt = mgr._build_subagent_prompt("test task", tools=tools)
    assert "read_file" in prompt
    assert "web_search" in prompt
    assert "exec" not in prompt


def test_prompt_includes_skills():
    """Subagent prompt includes pre-loaded skills section."""
    mgr = _make_manager()
    tools = mgr._build_tools()
    prompt = mgr._build_subagent_prompt(
        "test task", tools=tools, skills_content="### Skill: summarization\n\nSummarize text."
    )
    assert "Pre-loaded Skills" in prompt
    assert "summarization" in prompt


def test_prompt_no_skills_by_default():
    """Without skills content, prompt doesn't include skills section."""
    mgr = _make_manager()
    tools = mgr._build_tools()
    prompt = mgr._build_subagent_prompt("test task", tools=tools)
    assert "Pre-loaded Skills" not in prompt
