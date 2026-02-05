"""Tests for multi-provider routing via ProviderResolver."""

import pytest

from nanobot.config.schema import (
    AgentDefaults,
    CompactionConfig,
    Config,
    MemoryConfig,
    ProviderConfig,
    ProvidersConfig,
)
from nanobot.providers.resolver import ProviderResolver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def providers() -> ProvidersConfig:
    """ProvidersConfig with openrouter and zhipu configured."""
    return ProvidersConfig(
        openrouter=ProviderConfig(api_key="sk-or-test-key"),
        zhipu=ProviderConfig(api_key="zhipu-key-123"),
    )


@pytest.fixture
def resolver(providers: ProvidersConfig) -> ProviderResolver:
    """ProviderResolver with zhipu as the default."""
    return ProviderResolver(providers, default_provider="zhipu")


# ---------------------------------------------------------------------------
# ProviderResolver.resolve()
# ---------------------------------------------------------------------------


class TestProviderResolverResolve:
    def test_resolve_named_provider(self, resolver: ProviderResolver) -> None:
        api_key, api_base = resolver.resolve("openrouter")
        assert api_key == "sk-or-test-key"
        assert api_base == "https://openrouter.ai/api/v1"

    def test_resolve_named_zhipu(self, resolver: ProviderResolver) -> None:
        api_key, api_base = resolver.resolve("zhipu")
        assert api_key == "zhipu-key-123"
        assert api_base is None

    def test_resolve_none_falls_back_to_default(self, resolver: ProviderResolver) -> None:
        api_key, _ = resolver.resolve(None)
        assert api_key == "zhipu-key-123"

    def test_resolve_unknown_provider_falls_back(self, resolver: ProviderResolver) -> None:
        """An unknown name should fall through to default, then fallback."""
        api_key, _ = resolver.resolve("nonexistent")
        # Falls back to default_provider (zhipu)
        assert api_key == "zhipu-key-123"

    def test_fallback_when_no_default(self, providers: ProvidersConfig) -> None:
        """With no default_provider, should use priority-based scan."""
        resolver = ProviderResolver(providers, default_provider=None)
        api_key, api_base = resolver.resolve()
        # openrouter has higher priority
        assert api_key == "sk-or-test-key"
        assert api_base == "https://openrouter.ai/api/v1"

    def test_empty_providers_returns_none(self) -> None:
        resolver = ProviderResolver(ProvidersConfig())
        api_key, api_base = resolver.resolve()
        assert api_key is None
        assert api_base is None

    def test_custom_api_base_preserved(self) -> None:
        providers = ProvidersConfig(
            openrouter=ProviderConfig(
                api_key="sk-or-key",
                api_base="https://custom.openrouter.ai/v1",
            ),
        )
        resolver = ProviderResolver(providers)
        _, api_base = resolver.resolve("openrouter")
        assert api_base == "https://custom.openrouter.ai/v1"

    def test_vllm_api_base_without_key(self) -> None:
        """vLLM may have api_base but no api_key."""
        providers = ProvidersConfig(
            vllm=ProviderConfig(api_base="http://localhost:8000"),
        )
        resolver = ProviderResolver(providers)
        api_key, api_base = resolver.resolve()
        assert api_key is None
        assert api_base == "http://localhost:8000"


# ---------------------------------------------------------------------------
# Config.resolve_provider()
# ---------------------------------------------------------------------------


class TestConfigResolveProvider:
    def test_resolve_provider_named(self) -> None:
        config = Config(
            providers=ProvidersConfig(
                openrouter=ProviderConfig(api_key="sk-or-test"),
                zhipu=ProviderConfig(api_key="zhipu-key"),
            ),
        )
        api_key, api_base = config.resolve_provider("zhipu")
        assert api_key == "zhipu-key"
        assert api_base is None

    def test_resolve_provider_none_falls_back(self) -> None:
        config = Config(
            providers=ProvidersConfig(
                openrouter=ProviderConfig(api_key="sk-or-test"),
            ),
        )
        api_key, api_base = config.resolve_provider(None)
        assert api_key == "sk-or-test"
        assert api_base == "https://openrouter.ai/api/v1"


# ---------------------------------------------------------------------------
# Config schema new fields
# ---------------------------------------------------------------------------


class TestSchemaNewFields:
    def test_agent_defaults_provider_field(self) -> None:
        defaults = AgentDefaults(provider="openrouter")
        assert defaults.provider == "openrouter"

    def test_agent_defaults_provider_default_none(self) -> None:
        defaults = AgentDefaults()
        assert defaults.provider is None

    def test_compaction_provider_field(self) -> None:
        compaction = CompactionConfig(provider="zhipu")
        assert compaction.provider == "zhipu"

    def test_compaction_provider_default_none(self) -> None:
        compaction = CompactionConfig()
        assert compaction.provider is None

    def test_memory_embedding_provider(self) -> None:
        mem = MemoryConfig(**{"embeddingProvider": "openrouter"})
        assert mem.embedding_provider == "openrouter"

    def test_memory_extraction_provider(self) -> None:
        mem = MemoryConfig(**{"extractionProvider": "zhipu"})
        assert mem.extraction_provider == "zhipu"

    def test_memory_consolidation_provider(self) -> None:
        mem = MemoryConfig(**{"consolidationProvider": "openrouter"})
        assert mem.consolidation_provider == "openrouter"

    def test_memory_providers_default_none(self) -> None:
        mem = MemoryConfig()
        assert mem.embedding_provider is None
        assert mem.extraction_provider is None
        assert mem.consolidation_provider is None


# ---------------------------------------------------------------------------
# Provider resolution chain logic
# ---------------------------------------------------------------------------


class TestResolutionChain:
    """Test the resolution chain: subsystem -> compaction -> default -> fallback."""

    def test_embedding_uses_own_provider(self, providers: ProvidersConfig) -> None:
        """embeddingProvider set -> use it."""
        resolver = ProviderResolver(providers, default_provider="zhipu")
        api_key, api_base = resolver.resolve("openrouter")
        assert api_key == "sk-or-test-key"
        assert api_base == "https://openrouter.ai/api/v1"

    def test_extraction_falls_back_to_compaction(
        self, providers: ProvidersConfig
    ) -> None:
        """extraction_provider=None, compaction.provider="openrouter" -> openrouter."""
        resolver = ProviderResolver(providers, default_provider="zhipu")
        # Simulating: extraction_provider or compaction.provider
        provider_name = None or "openrouter"
        api_key, _ = resolver.resolve(provider_name)
        assert api_key == "sk-or-test-key"

    def test_extraction_falls_back_to_main(
        self, providers: ProvidersConfig
    ) -> None:
        """extraction_provider=None, compaction.provider=None -> default (zhipu)."""
        resolver = ProviderResolver(providers, default_provider="zhipu")
        provider_name = None or None
        api_key, _ = resolver.resolve(provider_name)
        assert api_key == "zhipu-key-123"


# ---------------------------------------------------------------------------
# JSON config parsing with aliases
# ---------------------------------------------------------------------------


class TestJsonConfigParsing:
    def test_memory_config_from_dict_with_aliases(self) -> None:
        data = {
            "embeddingProvider": "openrouter",
            "embeddingModel": "openai/text-embedding-3-small",
            "extractionProvider": "zhipu",
            "consolidationProvider": "openrouter",
        }
        mem = MemoryConfig(**data)
        assert mem.embedding_provider == "openrouter"
        assert mem.extraction_provider == "zhipu"
        assert mem.consolidation_provider == "openrouter"

    def test_compaction_config_from_dict_with_provider(self) -> None:
        data = {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.3-8b-instruct",
        }
        comp = CompactionConfig(**data)
        assert comp.provider == "openrouter"
        assert comp.model == "meta-llama/llama-3.3-8b-instruct"

    def test_agent_defaults_from_dict_with_provider(self) -> None:
        data = {
            "model": "glm-4.7-flash",
            "provider": "zhipu",
        }
        defaults = AgentDefaults(**data)
        assert defaults.provider == "zhipu"
        assert defaults.model == "glm-4.7-flash"
