"""Tests for nanobot.agents module - agent plugin infrastructure."""

import pytest

from nanobot.agents import BaseAgent
from nanobot.config.schema import AgentConfig, Config


class TestBaseAgent:
    """Test BaseAgent abstract class."""

    def test_base_agent_has_required_attributes(self):
        """BaseAgent should have name and display_name attributes."""
        assert hasattr(BaseAgent, "name")
        assert hasattr(BaseAgent, "display_name")

    def test_base_agent_has_default_config(self):
        """BaseAgent should have default_config classmethod."""
        assert hasattr(BaseAgent, "default_config")
        config = BaseAgent.default_config()
        assert isinstance(config, dict)

    def test_base_agent_has_create_hook(self):
        """BaseAgent should have create_hook classmethod."""
        assert hasattr(BaseAgent, "create_hook")


class TestConcreteAgent(BaseAgent):
    """Concrete implementation of BaseAgent for testing."""

    name = "test_agent"
    display_name = "Test Agent"

    @classmethod
    def default_config(cls):
        return {"test_option": True}

    @classmethod
    def create_hook(cls, **kwargs):
        return kwargs.get("mock_hook", "mock_hook_instance")


class TestBaseAgentSubclass:
    """Test concrete agent implementation."""

    def test_concrete_agent_name(self):
        """Concrete agent should have correct name."""
        assert TestConcreteAgent.name == "test_agent"

    def test_concrete_agent_display_name(self):
        """Concrete agent should have correct display_name."""
        assert TestConcreteAgent.display_name == "Test Agent"

    def test_concrete_agent_default_config(self):
        """Concrete agent should return config from default_config."""
        config = TestConcreteAgent.default_config()
        assert config == {"test_option": True}

    def test_concrete_agent_create_hook(self):
        """Concrete agent should create hook via create_hook."""
        hook = TestConcreteAgent.create_hook(mock_hook="test_hook")
        assert hook == "test_hook"

    def test_concrete_agent_is_subclass_of_base_agent(self):
        """Concrete agent should be subclass of BaseAgent."""
        assert issubclass(TestConcreteAgent, BaseAgent)


class TestAgentConfig:
    """Test AgentConfig schema."""

    def test_agent_config_defaults(self):
        """AgentConfig should have correct defaults."""
        config = AgentConfig()
        assert config.enabled is False
        assert config.plugins == {}

    def test_agent_config_accepts_enabled(self):
        """AgentConfig should accept enabled field."""
        config = AgentConfig(enabled=True)
        assert config.enabled is True

    def test_agent_config_accepts_plugins(self):
        """AgentConfig should accept plugins dict."""
        config = AgentConfig(plugins={"kosmos": {"host": "localhost"}})
        assert config.plugins == {"kosmos": {"host": "localhost"}}


class TestConfigHasPlugins:
    """Test that Config includes plugins field."""

    def test_config_has_plugins_field(self):
        """Config should have plugins field."""
        config = Config()
        assert hasattr(config, "plugins")

    def test_config_plugins_is_agent_config(self):
        """Config.plugins should be AgentConfig instance."""
        config = Config()
        assert isinstance(config.plugins, AgentConfig)

    def test_config_plugins_defaults(self):
        """Config.plugins should have correct defaults."""
        config = Config()
        assert config.plugins.enabled is False
        assert config.plugins.plugins == {}


class TestAgentRegistry:
    """Test agent registry functions."""

    def test_discover_agents_returns_dict(self):
        """discover_agents should return a dict."""
        from nanobot.agents.registry import discover_agents

        result = discover_agents()
        assert isinstance(result, dict)

    def test_discover_plugins_returns_dict(self):
        """discover_plugins should return a dict."""
        from nanobot.agents.registry import discover_plugins

        result = discover_plugins()
        assert isinstance(result, dict)

    def test_discover_all_returns_dict(self):
        """discover_all should return a dict."""
        from nanobot.agents.registry import discover_all

        result = discover_all()
        assert isinstance(result, dict)

    def test_discover_all_merges_builtin_and_plugins(self):
        """discover_all should merge built-in and external plugins."""
        from nanobot.agents.registry import discover_all

        result = discover_all()
        # Result should be dict of agent_name -> Agent class
        for name, agent_cls in result.items():
            assert isinstance(name, str)
            assert isinstance(agent_cls, type)
            assert issubclass(agent_cls, BaseAgent)
