"""Tests for the AgentsLoader and agent-router integration."""

import pytest

from nanobot.agent.agents import AgentsLoader


RESEARCHER_AGENT_MD = """---
name: researcher
description: "Deep web research, fact-checking, and source synthesis"
agent: "tencent_server"
allowed_tools: "read_file, write_file, web_search, web_fetch"
---

# Researcher Agent

You are a research specialist.
"""

CODER_AGENT_MD = """---
name: coder
description: "Code writing, debugging, refactoring, and technical implementation"
allowed_tools: "read_file, write_file, edit_file, list_dir, exec"
---

# Coder Agent

You are a coding specialist.
"""

NO_FRONTMATTER_MD = """# Simple Agent

No frontmatter here.
"""


# ---------------------------------------------------------------------------
# AgentsLoader
# ---------------------------------------------------------------------------


class TestAgentsLoader:

    @pytest.fixture()
    def workspace(self, tmp_path):
        """Create a workspace with sample agents."""
        agents_dir = tmp_path / "agents"
        for name, content in [("researcher", RESEARCHER_AGENT_MD), ("coder", CODER_AGENT_MD)]:
            agent_dir = agents_dir / name
            agent_dir.mkdir(parents=True)
            (agent_dir / "AGENT.md").write_text(content, encoding="utf-8")
        return tmp_path

    @pytest.fixture()
    def loader(self, workspace):
        return AgentsLoader(workspace, builtin_agents_dir=None)

    def test_list_agents(self, loader):
        agents = loader.list_agents()
        names = [a["name"] for a in agents]
        assert "researcher" in names
        assert "coder" in names
        assert all(a["source"] == "workspace" for a in agents)

    def test_list_agents_empty(self, tmp_path):
        loader = AgentsLoader(tmp_path, builtin_agents_dir=tmp_path / "no_builtins")
        assert loader.list_agents() == []

    def test_load_agent(self, loader):
        agent = loader.load_agent("researcher")
        assert agent is not None
        assert agent["metadata"]["name"] == "researcher"
        assert "Deep web research" in agent["metadata"]["description"]
        assert agent["metadata"]["agent"] == "tencent_server"
        assert agent["metadata"]["allowed_tools"] == "read_file, write_file, web_search, web_fetch"
        assert "# Researcher Agent" in agent["body"]
        assert "---" not in agent["body"]

    def test_load_agent_not_found(self, loader):
        assert loader.load_agent("nonexistent") is None

    def test_load_agent_no_frontmatter(self, tmp_path):
        agents_dir = tmp_path / "agents" / "simple"
        agents_dir.mkdir(parents=True)
        (agents_dir / "AGENT.md").write_text(NO_FRONTMATTER_MD, encoding="utf-8")
        loader = AgentsLoader(tmp_path, builtin_agents_dir=None)
        agent = loader.load_agent("simple")
        assert agent is not None
        assert agent["metadata"] == {}
        assert "# Simple Agent" in agent["body"]

    def test_build_agents_summary(self, loader):
        summary = loader.build_agents_summary()
        assert "<agents>" in summary
        assert "</agents>" in summary
        assert "<name>researcher</name>" in summary
        assert "<name>coder</name>" in summary
        assert "Deep web research" in summary
        assert "<agent_config>tencent_server</agent_config>" in summary

    def test_build_agents_summary_no_agent(self, tmp_path):
        """Agents without an agent field should not have an <agent_config> tag."""
        agents_dir = tmp_path / "agents" / "simple"
        agents_dir.mkdir(parents=True)
        (agents_dir / "AGENT.md").write_text(
            "---\nname: simple\ndescription: a simple agent\n---\nSimple.",
            encoding="utf-8",
        )
        loader = AgentsLoader(tmp_path, builtin_agents_dir=tmp_path / "no_builtins")
        summary = loader.build_agents_summary()
        assert "<agent_config>" not in summary

    def test_build_agents_summary_empty(self, tmp_path):
        loader = AgentsLoader(tmp_path, builtin_agents_dir=tmp_path / "no_builtins")
        assert loader.build_agents_summary() == ""

    def test_workspace_overrides_builtin(self, tmp_path):
        """Workspace agents take priority over builtin agents with the same name."""
        # Create workspace agent
        ws_dir = tmp_path / "agents" / "researcher"
        ws_dir.mkdir(parents=True)
        (ws_dir / "AGENT.md").write_text(
            "---\nname: researcher\ndescription: custom\n---\nCustom researcher.",
            encoding="utf-8",
        )

        # Create builtin agent with same name
        builtin_dir = tmp_path / "builtin_agents" / "researcher"
        builtin_dir.mkdir(parents=True)
        (builtin_dir / "AGENT.md").write_text(RESEARCHER_AGENT_MD, encoding="utf-8")

        loader = AgentsLoader(tmp_path, builtin_agents_dir=tmp_path / "builtin_agents")
        agents = loader.list_agents()
        researcher_agents = [a for a in agents if a["name"] == "researcher"]
        assert len(researcher_agents) == 1
        assert researcher_agents[0]["source"] == "workspace"

        agent = loader.load_agent("researcher")
        assert agent["metadata"]["description"] == "custom"

    def test_builtin_agents_discovered(self, tmp_path):
        """Builtin agents are discovered when workspace has none."""
        builtin_dir = tmp_path / "builtin" / "researcher"
        builtin_dir.mkdir(parents=True)
        (builtin_dir / "AGENT.md").write_text(RESEARCHER_AGENT_MD, encoding="utf-8")

        loader = AgentsLoader(tmp_path, builtin_agents_dir=tmp_path / "builtin")
        agents = loader.list_agents()
        assert len(agents) == 1
        assert agents[0]["source"] == "builtin"


# ---------------------------------------------------------------------------
# Context integration
# ---------------------------------------------------------------------------


class TestContextAgentsIntegration:

    @pytest.fixture()
    def workspace(self, tmp_path):
        """Minimal workspace with one agent and required bootstrap files."""
        agents_dir = tmp_path / "agents" / "researcher"
        agents_dir.mkdir(parents=True)
        (agents_dir / "AGENT.md").write_text(RESEARCHER_AGENT_MD, encoding="utf-8")
        return tmp_path

    def test_agents_summary_in_system_prompt(self, workspace):
        from nanobot.agent.context import ContextBuilder

        builder = ContextBuilder(workspace)
        prompt = builder.build_system_prompt()
        assert "# Agents" in prompt
        assert "<agents>" in prompt
        assert "<name>researcher</name>" in prompt

    def test_no_agents_section_when_empty(self, tmp_path):
        from nanobot.agent.context import ContextBuilder

        builder = ContextBuilder(tmp_path)
        # Override the agents loader to use a non-existent builtin dir
        builder.agents = AgentsLoader(tmp_path, builtin_agents_dir=tmp_path / "no_builtins")
        prompt = builder.build_system_prompt()
        assert "# Agents" not in prompt


# ---------------------------------------------------------------------------
# Spawn tool parameters
# ---------------------------------------------------------------------------


class TestSpawnToolParameters:

    def test_spawn_tool_has_new_params(self):
        from unittest.mock import MagicMock

        from nanobot.agent.tools.spawn import SpawnTool

        tool = SpawnTool(manager=MagicMock())
        params = tool.parameters
        props = params["properties"]
        assert "system_prompt" in props
        assert "allowed_tools" in props
        assert props["allowed_tools"]["type"] == "array"
        assert "agent" in props
        assert props["agent"]["type"] == "string"

    def test_spawn_tool_no_model_param(self):
        """The old 'model' param should no longer exist."""
        from unittest.mock import MagicMock

        from nanobot.agent.tools.spawn import SpawnTool

        tool = SpawnTool(manager=MagicMock())
        props = tool.parameters["properties"]
        assert "model" not in props


# ---------------------------------------------------------------------------
# Subagent tool filtering
# ---------------------------------------------------------------------------


class TestSubagentToolFiltering:

    def test_build_subagent_tools_all(self):
        from unittest.mock import MagicMock

        from nanobot.agent.subagent import SubagentManager

        manager = SubagentManager(
            provider=MagicMock(),
            workspace=MagicMock(),
            bus=MagicMock(),
        )
        tools = manager._build_subagent_tools(allowed_tools=None)
        names = [t.name for t in tools._tools.values()]
        assert "read_file" in names
        assert "web_search" in names
        assert "exec" in names

    def test_build_subagent_tools_filtered(self):
        from unittest.mock import MagicMock

        from nanobot.agent.subagent import SubagentManager

        manager = SubagentManager(
            provider=MagicMock(),
            workspace=MagicMock(),
            bus=MagicMock(),
        )
        tools = manager._build_subagent_tools(allowed_tools=["read_file", "web_search"])
        names = [t.name for t in tools._tools.values()]
        assert "read_file" in names
        assert "web_search" in names
        assert "exec" not in names
        assert "write_file" not in names

    def test_build_agent_prompt(self):
        from unittest.mock import MagicMock

        from nanobot.agent.subagent import SubagentManager

        manager = SubagentManager(
            provider=MagicMock(),
            workspace=MagicMock(spec=["__str__"], __str__=lambda self: "/workspace"),
            bus=MagicMock(),
        )
        prompt = manager._build_agent_prompt("You are a research specialist.")
        assert "You are a research specialist." in prompt
        assert "# Agent" in prompt
        assert "Workspace" in prompt
        assert "Guidelines" in prompt


# ---------------------------------------------------------------------------
# Subagent agent config override
# ---------------------------------------------------------------------------


class TestSubagentAgentConfigOverride:

    @pytest.mark.asyncio
    async def test_spawn_passes_agent_config_name_to_run_subagent(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from nanobot.agent.subagent import SubagentManager

        manager = SubagentManager(
            provider=MagicMock(),
            workspace=MagicMock(),
            bus=MagicMock(),
            model="default-model",
        )

        with patch.object(manager, "_run_subagent", new_callable=AsyncMock) as mock_run:
            await manager.spawn(
                task="test task",
                agent_config_name="tencent_server",
            )
            # Give the asyncio task a chance to start
            import asyncio
            await asyncio.sleep(0.05)

            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            # agent_config_name is the 7th positional arg
            assert call_kwargs[0][6] == "tencent_server"

    @pytest.mark.asyncio
    async def test_spawn_default_when_no_agent_config(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from nanobot.agent.subagent import SubagentManager

        manager = SubagentManager(
            provider=MagicMock(),
            workspace=MagicMock(),
            bus=MagicMock(),
            model="default-model",
        )

        with patch.object(manager, "_run_subagent", new_callable=AsyncMock) as mock_run:
            await manager.spawn(task="test task")
            import asyncio
            await asyncio.sleep(0.05)

            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            # agent_config_name should be None (not specified)
            assert call_kwargs[0][6] is None

    def test_make_provider_for_agent_no_config(self):
        """_make_provider_for_agent raises when config is None."""
        from unittest.mock import MagicMock

        from nanobot.agent.subagent import SubagentManager

        manager = SubagentManager(
            provider=MagicMock(),
            workspace=MagicMock(),
            bus=MagicMock(),
            config=None,
        )
        with pytest.raises(ValueError, match="no Config object"):
            manager._make_provider_for_agent("tencent_server")

    def test_make_provider_for_agent_unknown_agent(self):
        """_make_provider_for_agent raises for unknown agent name."""
        from unittest.mock import MagicMock

        from nanobot.agent.subagent import SubagentManager
        from nanobot.config.schema import Config

        config = Config()
        manager = SubagentManager(
            provider=MagicMock(),
            workspace=MagicMock(),
            bus=MagicMock(),
            config=config,
        )
        with pytest.raises(ValueError, match="not found"):
            manager._make_provider_for_agent("nonexistent_agent")

    def test_make_provider_for_agent_valid(self):
        """_make_provider_for_agent constructs provider for a known agent config."""
        from unittest.mock import MagicMock, patch

        from nanobot.agent.subagent import SubagentManager
        from nanobot.config.schema import Config

        # Build a config with a custom agent entry
        config = Config.model_validate({
            "agents": {
                "defaults": {"model": "gpt-4o", "provider": "openai"},
                "test_agent": {
                    "model": "qwen3-4b",
                    "provider": "custom",
                    "temperature": 0.5,
                    "max_tokens": 2048,
                },
            },
            "providers": {
                "custom": {"api_key": "test-key", "api_base": "http://localhost:8080/v1"},
            },
        })
        manager = SubagentManager(
            provider=MagicMock(),
            workspace=MagicMock(),
            bus=MagicMock(),
            config=config,
        )

        mock_provider = MagicMock()
        with patch("nanobot.providers.factory.make_provider", return_value=mock_provider) as mock_factory:
            provider, model = manager._make_provider_for_agent("test_agent")
            assert model == "qwen3-4b"
            assert provider is mock_provider
            # Verify factory was called with a config that has _active_agent set
            call_cfg = mock_factory.call_args[0][0]
            assert call_cfg._active_agent == "test_agent"
