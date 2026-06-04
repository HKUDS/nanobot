"""Tests for the configuration schema."""

from blackcat.config.schema import (
    AgentDefaults,
    AgentsConfig,
    ChannelsConfig,
    Config,
    GatewayConfig,
    ProviderConfig,
    ProvidersConfig,
    ToolsConfig,
    )

# ── Agent defaults ─────────────────────────────────────────────────


def test_agent_defaults():
    d = AgentDefaults()
    assert d.workspace == "~/.blackcat/workspace"
    assert "claude" in d.model.lower() or "anthropic" in d.model.lower()
    assert d.max_tokens > 0
    assert 0.0 <= d.temperature <= 2.0
    assert d.max_tool_iterations > 0


# ── Provider config ────────────────────────────────────────────────


def test_provider_config_defaults():
    p = ProviderConfig()
    assert p.api_key is None
    assert p.api_base is None
    assert p.extra_headers is None


def test_provider_config_with_values():
    p = ProviderConfig(api_key="sk-test", api_base="https://api.example.com")
    assert p.api_key == "sk-test"
    assert p.api_base == "https://api.example.com"


# ── Gateway config ─────────────────────────────────────────────────


def test_gateway_defaults():
    g = GatewayConfig()
    assert g.host == "127.0.0.1"
    assert g.port == 18790


# ── Tools config ───────────────────────────────────────────────────


def test_tools_config_defaults():
    t = ToolsConfig()
    assert t.restrict_to_workspace is False
    assert t.mcp_servers == {}


# ── Root Config ────────────────────────────────────────────────────


def test_config_defaults():
    cfg = Config()
    assert isinstance(cfg.agents, AgentsConfig)
    assert isinstance(cfg.channels, ChannelsConfig)
    assert isinstance(cfg.providers, ProvidersConfig)
    assert isinstance(cfg.gateway, GatewayConfig)
    assert isinstance(cfg.tools, ToolsConfig)


def test_config_workspace_path():
    cfg = Config()
    ws = cfg.workspace_path
    assert ws.is_absolute()
    assert "~" not in str(ws)


def test_config_get_api_key_none():
    """No API keys configured should return None."""
    cfg = Config()
    assert cfg.get_api_key() is None


def test_config_get_api_key_from_anthropic():
    cfg = Config()
    cfg.providers.anthropic.api_key = "sk-ant-test"
    key = cfg.get_api_key("anthropic/claude-opus-4-5")
    assert key == "sk-ant-test"


def test_config_get_provider_fallback():
    """When no model keyword matches, fall back to first provider with a key."""
    cfg = Config()
    cfg.providers.openai.api_key = "sk-openai"
    provider = cfg.get_provider("unknown-model-xyz")
    assert provider is not None
    assert provider.api_key == "sk-openai"


def test_config_get_api_base_for_gateway():
    cfg = Config()
    cfg.providers.openrouter.api_key = "sk-or-test"
    base = cfg.get_api_base("openrouter/claude-3")
    # Should return the default openrouter base
    assert base is not None
    assert "openrouter" in base


def test_config_get_api_base_none():
    cfg = Config()
    assert cfg.get_api_base() is None


# ── Provider matching ────────────────────────────────────────────────


def test_provider_match_prefix_with_no_key_uses_gateway():
    """Model with provider prefix, but that provider has no key -> use gateway."""
    cfg = Config()
    cfg.providers.anthropic.api_key = ""  # No Anthropic key
    cfg.providers.openrouter.api_key = "sk-or-test"  # Has gateway key
    cfg.providers.vllm.api_base = None  # No local configured

    p, name = cfg._match_provider("anthropic/claude-sonnet-4.6")
    assert name == "openrouter"
    assert p is not None
    assert p.api_key == "sk-or-test"


def test_provider_match_plain_model_uses_local():
    """Plain model (no prefix) should use local fallback if configured."""
    cfg = Config()
    cfg.providers.openrouter.api_key = "sk-or-test"
    cfg.providers.vllm.api_base = "http://localhost:11434/"

    p, name = cfg._match_provider("llama3.2")
    assert name == "vllm"
    assert p is not None
    assert p.api_base == "http://localhost:11434/"


def test_provider_match_explicit_prefix_with_key():
    """Explicit provider prefix with valid key should use that provider."""
    cfg = Config()
    cfg.providers.anthropic.api_key = "sk-ant-test"
    cfg.providers.openrouter.api_key = "sk-or-test"

    p, name = cfg._match_provider("anthropic/claude-sonnet-4.6")
    assert name == "anthropic"
    assert p is not None
    assert p.api_key == "sk-ant-test"


def test_provider_match_gateway_prefix():
    """OpenRouter prefix should route through OpenRouter."""
    cfg = Config()
    cfg.providers.openrouter.api_key = "sk-or-test"

    p, name = cfg._match_provider("openrouter/anthropic/claude-sonnet-4.6")
    assert name == "openrouter"
    assert p is not None


def test_provider_match_no_provider_available():
    """No matching provider with key should return None."""
    cfg = Config()
    # All providers have empty keys
    cfg.providers.anthropic.api_key = ""
    cfg.providers.openrouter.api_key = ""
    cfg.providers.vllm.api_base = None  # No local either

    p, name = cfg._match_provider("anthropic/claude-sonnet-4.6")
    # Gateway fallback will also fail, so None
    assert p is None or name is None or p.api_key == ""


def test_provider_match_keyword_match():
    """Match by keyword in model name."""
    cfg = Config()
    cfg.providers.openai.api_key = "sk-openai"

    p, name = cfg._match_provider("gpt-4o")
    assert name == "openai"
    assert p is not None
    assert p.api_key == "sk-openai"


def test_provider_match_forced_provider():
    """Forced provider in config should bypass auto-detection."""
    cfg = Config()
    cfg.agents.defaults.provider = "openrouter"
    cfg.providers.openrouter.api_key = "sk-or-test"
    cfg.providers.anthropic.api_key = "sk-ant-test"

    p, name = cfg._match_provider("claude-sonnet-4.6")
    assert name == "openrouter"
    assert p is not None
    assert p.api_key == "sk-or-test"
