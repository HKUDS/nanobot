"""Tests for provider routing in _make_provider.

Verifies that each provider type creates the correct provider class
with the right base URL, model name, and API key. Also covers Ollama
cloud/local routing and edge cases.
"""

from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest

from blackcat.providers.registry import PROVIDERS, find_by_name

OLLAMA_SPEC = find_by_name("ollama")
OPENAI_SPEC = find_by_name("openai")
ANTHROPIC_SPEC = find_by_name("anthropic")
DEEPSEEK_SPEC = find_by_name("deepseek")
GROQ_SPEC = find_by_name("groq")
VLLM_SPEC = find_by_name("vllm")


def _make_mock_config(
    model="ollama/glm-5:cloud",
    provider_name="ollama",
    api_base="http://localhost:11434/v1",
):
    """Build a mock config object with the minimal interface _make_provider needs."""
    config = MagicMock()
    config.agents.defaults.model = model
    config.agents.defaults.temperature = 0.7
    config.agents.defaults.max_tokens = 4096
    config.agents.defaults.reasoning_effort = "medium"
    config.agents.defaults.context_window_tokens = 128000
    config.agents.defaults.context_block_limit = 50
    config.agents.defaults.max_tool_result_chars = 50000
    config.agents.defaults.workspace = "/tmp/test"
    config.agents.defaults.max_tool_iterations = 10
    config.tools.exec = MagicMock()
    config.tools.restrict_to_workspace = False
    config.tools.mcp_servers = {}
    config.get_provider_name.return_value = provider_name
    config.get_api_base.return_value = api_base
    return config


def _make_mock_provider(api_key="test-key", api_base=None, extra_headers=None):
    """Build a mock provider config (what config.get_provider() returns)."""
    p = MagicMock()
    p.api_key = api_key
    p.api_base = api_base
    p.extra_headers = extra_headers
    return p


def _call_make_provider(config):
    """Call _make_provider with find_by_name mocked (import is local)."""
    from blackcat.blackcat import _make_provider

    with patch("blackcat.providers.registry.find_by_name") as mock_find:
        name = config.get_provider_name.return_value
        mock_find.return_value = find_by_name(name) if name else None
        return _make_provider(config)


# ── Registry integrity ─────────────────────────────────────────────


def test_all_providers_have_unique_names():
    names = [spec.name for spec in PROVIDERS]
    assert len(names) == len(set(names))


def test_all_providers_have_env_key_or_exempt():
    """OAuth, direct, and local providers don't need env_key."""
    for spec in PROVIDERS:
        if not (spec.is_oauth or spec.is_direct or spec.is_local):
            assert spec.env_key, f"{spec.name}: non-exempt provider needs env_key"


# ── Ollama cloud routing ──────────────────────────────────────────


class TestOllamaCloudRouting:
    """Ollama :cloud models route to ollama.com, local models stay local."""

    def test_cloud_model_routes_to_ollama_com(self):
        config = _make_mock_config(model="ollama/glm-5:cloud")
        config.get_provider.return_value = _make_mock_provider()
        # Cloud models should return ollama.com, not localhost
        config.get_api_base.return_value = "https://ollama.com/v1/"

        provider = _call_make_provider(config)
        parsed_base_url = urlparse(str(provider._client.base_url))
        assert parsed_base_url.hostname == "ollama.com"

    def test_cloud_model_default_model_includes_provider_prefix(self):
        """default_model stores the full model string; stripping happens at request time."""
        config = _make_mock_config(model="ollama/glm-5:cloud")
        config.get_provider.return_value = _make_mock_provider()

        provider = _call_make_provider(config)
        # default_model keeps the full string; strip_model_prefix strips "ollama/" in _build_kwargs
        assert provider.default_model == "ollama/glm-5:cloud"

    def test_local_model_uses_configured_base(self):
        config = _make_mock_config(model="ollama/ministral-3:8b")
        config.get_provider.return_value = _make_mock_provider(
            api_base="http://localhost:11434/v1"
        )

        provider = _call_make_provider(config)
        assert "localhost" in str(provider._client.base_url)
        assert "ollama.com" not in str(provider._client.base_url)

    def test_cloud_model_without_api_key_raises(self):
        config = _make_mock_config(model="ollama/glm-5:cloud")
        config.get_provider.return_value = _make_mock_provider(api_key=None)

        with pytest.raises(ValueError, match="No API key"):
            _call_make_provider(config)

    def test_cloud_model_with_empty_api_key_raises(self):
        config = _make_mock_config(model="ollama/glm-5:cloud")
        config.get_provider.return_value = _make_mock_provider(api_key="")

        with pytest.raises(ValueError, match="No API key"):
            _call_make_provider(config)

    def test_local_model_with_api_key_stays_local(self):
        """Having an API key set shouldn't force cloud routing for non-:cloud models."""
        config = _make_mock_config(model="ollama/ministral-3:8b")
        config.get_provider.return_value = _make_mock_provider(
            api_key="some-key", api_base="http://localhost:11434/v1"
        )

        provider = _call_make_provider(config)
        assert "localhost" in str(provider._client.base_url)


# ── Standard providers ─────────────────────────────────────────────


class TestStandardProviders:
    """Each provider type creates the correct provider class."""

    def test_anthropic_provider(self):
        from blackcat.providers.anthropic_provider import AnthropicProvider

        config = _make_mock_config(
            model="anthropic/claude-sonnet-4-20250514",
            provider_name="anthropic",
            api_base="https://api.anthropic.com",
        )
        config.get_provider.return_value = _make_mock_provider(
            api_key="sk-ant-test", api_base="https://api.anthropic.com"
        )

        provider = _call_make_provider(config)
        assert isinstance(provider, AnthropicProvider)

    def test_openai_provider(self):
        from blackcat.providers.openai_compat_provider import OpenAICompatProvider

        config = _make_mock_config(
            model="openai/gpt-4o",
            provider_name="openai",
            api_base="https://api.openai.com/v1",
        )
        config.get_provider.return_value = _make_mock_provider(
            api_key="sk-test", api_base="https://api.openai.com/v1"
        )

        provider = _call_make_provider(config)
        assert isinstance(provider, OpenAICompatProvider)
        parsed_base_url = urlparse(str(provider._client.base_url))
        assert parsed_base_url.hostname == "api.openai.com"

    def test_deepseek_provider(self):
        from blackcat.providers.openai_compat_provider import OpenAICompatProvider

        config = _make_mock_config(
            model="deepseek/deepseek-chat",
            provider_name="deepseek",
            api_base="https://api.deepseek.com",
        )
        config.get_provider.return_value = _make_mock_provider(
            api_key="sk-ds-test", api_base="https://api.deepseek.com"
        )

        provider = _call_make_provider(config)
        assert isinstance(provider, OpenAICompatProvider)
        host = urlparse(str(provider._client.base_url)).hostname
        assert host == "api.deepseek.com"

    def test_groq_provider(self):
        from blackcat.providers.openai_compat_provider import OpenAICompatProvider

        config = _make_mock_config(
            model="groq/llama-3.1-8b",
            provider_name="groq",
            api_base="https://api.groq.com/openai/v1",
        )
        config.get_provider.return_value = _make_mock_provider(
            api_key="gsk_test", api_base="https://api.groq.com/openai/v1"
        )

        provider = _call_make_provider(config)
        assert isinstance(provider, OpenAICompatProvider)
        host = urlparse(str(provider._client.base_url)).hostname
        assert host == "api.groq.com"

    def test_vllm_provider_local(self):
        from blackcat.providers.openai_compat_provider import OpenAICompatProvider

        config = _make_mock_config(
            model="vllm/llama-3.1-8b",
            provider_name="vllm",
            api_base="http://localhost:8000/v1",
        )
        config.get_provider.return_value = _make_mock_provider(
            api_key=None, api_base="http://localhost:8000/v1"
        )

        provider = _call_make_provider(config)
        assert isinstance(provider, OpenAICompatProvider)
        assert "localhost" in str(provider._client.base_url)

    def test_ollama_local_provider(self):
        from blackcat.providers.openai_compat_provider import OpenAICompatProvider

        config = _make_mock_config(
            model="ollama/ministral-3:8b",
            api_base="http://localhost:11434/v1",
        )
        config.get_provider.return_value = _make_mock_provider(
            api_base="http://localhost:11434/v1"
        )

        provider = _call_make_provider(config)
        assert isinstance(provider, OpenAICompatProvider)
        host = urlparse(str(provider._client.base_url)).hostname
        assert host == "localhost"


# ── Ollama /v1 normalization ────────────────────────────────────────



# ── Registry lookups ───────────────────────────────────────────────


class TestRegistryLookups:
    """ProviderSpec lookups and properties."""

    def test_find_ollama(self):
        assert OLLAMA_SPEC is not None
        assert OLLAMA_SPEC.is_local is True
        assert OLLAMA_SPEC.strip_model_prefix is True

    def test_find_anthropic(self):
        assert ANTHROPIC_SPEC is not None
        assert ANTHROPIC_SPEC.supports_prompt_caching is True
        assert ANTHROPIC_SPEC.backend == "anthropic"

    def test_find_openai(self):
        assert OPENAI_SPEC is not None
        assert OPENAI_SPEC.backend == "openai_compat"

    def test_find_nonexistent(self):
        assert find_by_name("nonexistent_provider") is None

    def test_find_by_name_normalizes(self):
        """find_by_name should normalize hyphens and case."""
        assert find_by_name("azure_openai") is not None
        assert find_by_name("azure-openai") is not None
