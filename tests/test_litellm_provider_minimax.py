from types import SimpleNamespace

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


def _fake_response():
    message = SimpleNamespace(
        content="OK",
        tool_calls=None,
        reasoning_content=None,
        thinking_blocks=None,
    )
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    return SimpleNamespace(choices=[choice], usage=usage)


@pytest.mark.asyncio
async def test_chat_uses_normalized_anthropic_model_for_legacy_minimax_override(monkeypatch) -> None:
    provider = LiteLLMProvider(
        api_key="mini-key",
        api_base="https://api.minimaxi.com/anthropic",
        default_model="anthropic/MiniMax-M2.5",
    )
    seen: dict[str, object] = {}

    async def _fake_acompletion(**kwargs):
        seen.update(kwargs)
        return _fake_response()

    monkeypatch.setattr("nanobot.providers.litellm_provider.acompletion", _fake_acompletion)

    response = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="minimax/MiniMax-M2.5",
        max_tokens=8,
        temperature=0,
    )

    assert response.content == "OK"
    assert seen["model"] == "anthropic/MiniMax-M2.5"
    assert seen["api_base"] == "https://api.minimaxi.com/anthropic"
