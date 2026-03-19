import pytest

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.multi_model_provider import ModelCandidate, MultiModelProvider


class ScriptedProvider(LLMProvider):
    def __init__(self, responses, default_model: str):
        super().__init__()
        self._responses = list(responses)
        self._default_model = default_model
        self.calls: list[dict] = []

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        return self._responses.pop(0)

    def get_default_model(self) -> str:
        return self._default_model


@pytest.mark.asyncio
async def test_multi_model_provider_falls_back_to_next_candidate() -> None:
    primary = ScriptedProvider(
        [LLMResponse(content="429 rate limit", finish_reason="error")],
        default_model="anthropic/claude-opus-4-5",
    )
    secondary = ScriptedProvider(
        [LLMResponse(content="ok")],
        default_model="openrouter/openai/gpt-5-mini",
    )
    provider = MultiModelProvider(
        [
            ModelCandidate("anthropic/claude-opus-4-5", "anthropic", primary),
            ModelCandidate("openrouter/openai/gpt-5-mini", "openrouter", secondary),
        ],
        default_model="anthropic/claude-opus-4-5",
    )

    response = await provider.chat(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert primary.calls[0]["model"] == "anthropic/claude-opus-4-5"
    assert secondary.calls[0]["model"] == "openrouter/openai/gpt-5-mini"


@pytest.mark.asyncio
async def test_multi_model_provider_prioritizes_requested_model_when_configured() -> None:
    primary = ScriptedProvider(
        [LLMResponse(content="ok from requested")],
        default_model="openrouter/openai/gpt-5-mini",
    )
    secondary = ScriptedProvider(
        [LLMResponse(content="should not be used")],
        default_model="anthropic/claude-opus-4-5",
    )
    provider = MultiModelProvider(
        [
            ModelCandidate("anthropic/claude-opus-4-5", "anthropic", secondary),
            ModelCandidate("openrouter/openai/gpt-5-mini", "openrouter", primary),
        ],
        default_model="anthropic/claude-opus-4-5",
    )

    response = await provider.chat(
        messages=[{"role": "user", "content": "hello"}],
        model="openrouter/openai/gpt-5-mini",
    )

    assert response.content == "ok from requested"
    assert len(primary.calls) == 1
    assert secondary.calls == []
