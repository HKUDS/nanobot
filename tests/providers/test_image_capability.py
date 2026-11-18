from copy import deepcopy
from typing import Any

import pytest

from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderCallContext,
    ProviderConversationState,
)
from nanobot.providers.factory import make_provider, provider_signature
from nanobot.providers.fallback_provider import FallbackProvider

_IMAGE = {"type": "image_url", "image_url": {"url": "data:image/png;base64,c3ludGhldGlj"}}


class ImageProvider(LLMProvider):
    def __init__(self, supports_images: bool = True, response: LLMResponse | None = None):
        super().__init__(provider_name="custom")
        self.supports_images = supports_images
        self.response = response or LLMResponse("accepted")
        self.calls: list[dict[str, Any]] = []

    def get_default_model(self) -> str:
        return "custom/model"

    async def chat(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(deepcopy(kwargs))
        return self.response


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("native", [False, True])
async def test_text_only_preset_rejects_images_before_request(stream, native):
    provider = ImageProvider(False)
    messages = [{"role": "user", "content": "Continue" if native else [_IMAGE]}]
    state = ProviderConversationState(
        kind="fixture", provider="custom", model="custom/model", version=1,
        payload={"items": [{"role": "user", "content": [{"type": "input_image", "image_url": _IMAGE["image_url"]["url"]}]}]},
    ) if native else None
    before = deepcopy(messages)
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry
    response = await call(messages=messages, provider_context=ProviderCallContext(conversation_state=state))
    assert response.finish_reason == "error"
    assert response.error_code == "unsupported_image"
    assert response.error_should_retry is False
    assert provider.calls == []
    assert messages == before
    text_response = await call(messages=[{"role": "user", "content": "Text only"}])
    assert text_response.content == "accepted"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("primary_supports", [False, True])
async def test_image_fallback_skips_text_only_candidates_without_counting_capability_as_outage(stream, primary_supports):
    primary = ImageProvider(primary_supports, LLMResponse("unavailable", finish_reason="error", error_status_code=503))
    vision = ImageProvider()
    created = []

    def factory(preset):
        created.append(preset.model)
        return vision

    chain = FallbackProvider(primary, [
        ModelPresetConfig(model="text-only", supports_images=False),
        ModelPresetConfig(model="vision"),
    ], factory)
    messages = [{"role": "user", "content": [_IMAGE]}]
    before = deepcopy(messages)
    call = chain.chat_stream_with_context if stream else chain.chat_with_context
    response = await call(messages=messages, provider_context=ProviderCallContext())
    assert response.content == "accepted"
    assert response.is_fallback
    assert created == ["vision"]
    assert len(primary.calls) == int(primary_supports)
    assert chain._primary_failures == int(primary_supports)
    assert vision.calls[0]["messages"] == before
    assert messages == before


@pytest.mark.parametrize("stream", [False, True])
async def test_no_image_capable_candidate_fails_without_sending_or_stripping(stream):
    primary = ImageProvider(False)
    created = []
    chain = FallbackProvider(primary, [ModelPresetConfig(model="text", supports_images=False)], lambda preset: created.append(preset))
    call = chain.chat_stream_with_retry if stream else chain.chat_with_retry
    response = await call(messages=[{"role": "user", "content": [_IMAGE]}])
    assert response.error_code == "unsupported_image"
    assert response.error_should_retry is False
    assert primary.calls == created == []


@pytest.mark.parametrize("stream", [False, True])
async def test_declared_vision_does_not_hide_actual_upstream_rejection(stream):
    upstream = LLMResponse("unsupported image format", finish_reason="error", error_status_code=400)
    primary = ImageProvider(True, upstream)
    created = []
    chain = FallbackProvider(primary, [ModelPresetConfig(model="vision")], lambda preset: created.append(preset))
    messages = [{"role": "user", "content": [_IMAGE]}]
    before = deepcopy(messages)
    call = chain.chat_stream_with_retry if stream else chain.chat_with_retry
    response = await call(messages=messages)
    assert response.content == upstream.content
    assert response.error_status_code == 400
    assert len(primary.calls) == 1
    assert created == []
    assert messages == before


def test_factory_resolves_independent_capabilities_and_refresh_signature():
    config = Config.model_validate({
        "agents": {"defaults": {"modelPreset": "text", "fallbackModels": ["vision", {"provider": "custom", "model": "inline"}]}},
        "providers": {"custom": {"apiBase": "https://provider.example/v1"}},
        "modelPresets": {
            "text": {"model": "text", "provider": "custom", "supportsImages": False},
            "vision": {"model": "vision", "provider": "custom"},
        },
    })
    provider = make_provider(config)
    assert isinstance(provider, FallbackProvider)
    assert provider._primary.supports_images is False
    assert [preset.supports_images for preset in provider._fallback_presets] == [True, True]
    signature = provider_signature(config)
    config.model_presets["vision"].supports_images = False
    assert provider_signature(config) != signature
    signature = provider_signature(config)
    config.model_presets["text"].supports_images = True
    assert provider_signature(config) != signature
