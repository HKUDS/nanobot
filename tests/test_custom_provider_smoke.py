import pytest

from nanobot.providers.custom_provider import CustomLLMConfig, CustomLLMProvider


@pytest.mark.asyncio
async def test_smoke_model_passthrough(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)

        class DummyMessage:
            def __init__(self):
                self.content = "ok"
                self.tool_calls = []

        class DummyChoice:
            def __init__(self):
                self.message = DummyMessage()
                self.finish_reason = "stop"

        class DummyResponse:
            def __init__(self):
                self.choices = [DummyChoice()]
                self.usage = None

        return DummyResponse()

    monkeypatch.setattr(
        "nanobot.providers.custom_provider.acompletion",
        fake_acompletion,
    )

    provider = CustomLLMProvider(
        CustomLLMConfig(api_key="sk-or-123", default_model="openai/gpt-4o"),
    )
    await provider.chat(messages=[{"role": "user", "content": "hi"}])
    assert captured["model"] == "openai/gpt-4o"

    provider = CustomLLMProvider(
        CustomLLMConfig(
            api_key="test",
            api_url="http://localhost:8000",
            default_model="openai/gpt-4o",
        ),
    )
    await provider.chat(messages=[{"role": "user", "content": "hi"}])
    assert captured["model"] == "openai/gpt-4o"

    provider = CustomLLMProvider(
        CustomLLMConfig(api_key="test", default_model="gemini/gemini-2.0-flash"),
    )
    await provider.chat(messages=[{"role": "user", "content": "hi"}])
    assert captured["model"] == "gemini/gemini-2.0-flash"

    provider = CustomLLMProvider(
        CustomLLMConfig(api_key="test", default_model="glm-4.7-flash"),
    )
    await provider.chat(messages=[{"role": "user", "content": "hi"}])
    assert captured["model"] == "glm-4.7-flash"


class PrefixingProvider(CustomLLMProvider):
    def prepare_model(self, model: str) -> str:
        return f"openrouter/{model}"


@pytest.mark.asyncio
async def test_smoke_model_prepare_hook(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)

        class DummyMessage:
            def __init__(self):
                self.content = "ok"
                self.tool_calls = []

        class DummyChoice:
            def __init__(self):
                self.message = DummyMessage()
                self.finish_reason = "stop"

        class DummyResponse:
            def __init__(self):
                self.choices = [DummyChoice()]
                self.usage = None

        return DummyResponse()

    monkeypatch.setattr(
        "nanobot.providers.custom_provider.acompletion",
        fake_acompletion,
    )

    provider = PrefixingProvider(
        CustomLLMConfig(api_key="sk-or-123", default_model="openai/gpt-4o"),
    )
    await provider.chat(messages=[{"role": "user", "content": "hi"}])
    assert captured["model"] == "openrouter/openai/gpt-4o"
