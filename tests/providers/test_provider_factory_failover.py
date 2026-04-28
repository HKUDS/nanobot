from __future__ import annotations

from nanobot.config.schema import Config
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.factory import build_provider_snapshot, provider_signature
from nanobot.providers.failover import ModelRouter


class DummyProvider(LLMProvider):
    def __init__(self, model: str) -> None:
        super().__init__()
        self.model = model

    async def chat(self, **kwargs) -> LLMResponse:
        return LLMResponse(content=self.model)

    def get_default_model(self) -> str:
        return self.model


def test_provider_signature_changes_when_fallback_config_changes() -> None:
    base = Config.model_validate({
        "agents": {"defaults": {"model": "anthropic/claude-opus-4-5"}}
    })
    with_fallback = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "anthropic/claude-opus-4-5",
                "fallbackModels": ["openai/gpt-4.1-mini"],
            }
        }
    })
    with_failover_policy = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "anthropic/claude-opus-4-5",
                "fallbackModels": ["openai/gpt-4.1-mini"],
                "failover": {"cooldownSeconds": 5},
            }
        }
    })

    assert provider_signature(base) != provider_signature(with_fallback)
    assert provider_signature(with_fallback) != provider_signature(with_failover_policy)


def test_build_provider_snapshot_returns_plain_provider_without_fallback(monkeypatch) -> None:
    config = Config.model_validate({
        "agents": {"defaults": {"model": "anthropic/claude-opus-4-5"}}
    })

    monkeypatch.setattr(
        "nanobot.providers.factory.make_provider_for_model",
        lambda _config, model: DummyProvider(model),
    )

    snapshot = build_provider_snapshot(config)

    assert isinstance(snapshot.provider, DummyProvider)
    assert snapshot.fallback_models == ()


def test_build_provider_snapshot_wraps_router_and_lazily_builds_fallback(monkeypatch) -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "anthropic/claude-opus-4-5",
                "fallbackModels": ["openai/gpt-4.1-mini"],
                "temperature": 0.3,
                "maxTokens": 123,
            }
        }
    })
    built_models: list[str] = []

    def make_dummy(_config: Config, model: str) -> DummyProvider:
        built_models.append(model)
        return DummyProvider(model)

    monkeypatch.setattr("nanobot.providers.factory.make_provider_for_model", make_dummy)

    snapshot = build_provider_snapshot(config)

    assert isinstance(snapshot.provider, ModelRouter)
    assert snapshot.fallback_models == ("openai/gpt-4.1-mini",)
    assert built_models == ["anthropic/claude-opus-4-5"]

    fallback_provider = snapshot.provider._get_provider(snapshot.provider.fallback_candidates[0])
    assert fallback_provider.get_default_model() == "openai/gpt-4.1-mini"
    assert built_models == ["anthropic/claude-opus-4-5", "openai/gpt-4.1-mini"]
