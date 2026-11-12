"""Repeated SDK overrides reuse clients without changing execution ownership."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.model_runtime import ModelRuntimeResolver
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers import factory
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.utils.llm_runtime import runtime_from_provider_snapshot


@pytest.fixture
def configured_override(monkeypatch):
    config = Config.model_validate({
        "agents": {"defaults": {"provider": "tenant", "model": "tenant/base"}},
        "providers": {
            "tenant": {"apiKey": "primary-fixture", "apiBase": "https://primary.test/v1",
                       "extraBody": {"nested": {"value": True}}},
            "backup": {"apiKey": "backup-fixture", "apiBase": "https://backup.test/v1"},
        },
        "modelPresets": {"backup": {"provider": "backup", "model": "backup/model"}},
    })
    created = []

    def construct(owned, *, preset, model=None):
        factory.validate_provider_setup(owned, preset=preset, model=model)
        provider = MagicMock(spec=LLMProvider)
        provider.generation = preset.to_generation_settings()
        provider.provider_name = owned.get_provider_name(preset=preset)
        provider.get_default_model.return_value = model or preset.model
        provider.chat = AsyncMock(return_value=LLMResponse(content="ok"))
        provider.aclose = AsyncMock()
        provider.factory_config = owned
        provider.factory_preset = preset
        created.append(provider)
        return provider

    monkeypatch.setattr(factory, "_make_provider_core", construct)
    resolver = ModelRuntimeResolver(runtime_from_provider_snapshot(factory.build_provider_snapshot(config)))
    return config, resolver, created


def resolve(config, resolver, model="tenant/override"):
    runtime = resolver.resolve_override(model=model, model_preset=None, config=config)
    assert runtime is not None
    return runtime


@pytest.mark.asyncio
async def test_repeated_override_reuses_provider_and_keeps_default(configured_override):
    config, resolver, created = configured_override
    initial = resolver.runtime
    first = resolve(config, resolver)
    for _ in range(1000):
        current = resolve(config, resolver)
        assert current.provider is first.provider
        assert current.generation == first.generation
    assert resolve(config.model_copy(deep=True), resolver).provider is first.provider
    assert len(created) == 2
    assert resolver.runtime is initial
    assert all(provider.aclose.await_count == 0 for provider in created)
    await resolver.aclose()
    assert all(provider.aclose.await_count == 1 for provider in created)


@pytest.mark.parametrize(("section", "field", "value"), [
    ("primary", "api_key", "rotated-fixture"),
    ("primary", "api_base", "https://new.test/v1"),
    ("primary", "extra_headers", {"X-Tenant": "new"}),
    ("primary", "extra_query", {"tenant": "new"}),
    ("defaults", "temperature", 0.2),
    ("defaults", "context_window_tokens", 32_768),
    ("backup", "api_key", "backup-rotated"),
    ("backup-preset", "max_tokens", 1024),
])
@pytest.mark.asyncio
async def test_override_identity_tracks_effective_chain_changes(
    configured_override, section, field, value,
):
    config, resolver, created = configured_override
    config.agents.defaults.fallback_models = ["backup"]
    first = resolve(config, resolver)
    target = {
        "primary": config.get_provider("tenant/model"),
        "backup": config.get_provider(preset=config.model_presets["backup"]),
        "defaults": config.agents.defaults,
        "backup-preset": config.model_presets["backup"],
    }[section]
    setattr(target, field, value)
    second = resolve(config, resolver)
    assert second.provider is not first.provider
    assert resolve(config, resolver).provider is second.provider
    assert len(created) == 3
    await resolver.aclose()
    assert all(provider.aclose.await_count == 1 for provider in created)


@pytest.mark.asyncio
async def test_nested_signature_changes_are_typed_and_borrowers_are_detached(configured_override):
    config, resolver, created = configured_override
    first = resolve(config, resolver)
    second = resolve(config, resolver)
    assert first.snapshot_signature is not None
    body = next(item for item in first.snapshot_signature if isinstance(item, dict) and "nested" in item)
    body["nested"]["value"] = "borrower edit"
    assert first.provider is second.provider
    for borrower in (second, resolve(config, resolver)):
        assert borrower.snapshot_signature is not None
        untouched = next(item for item in borrower.snapshot_signature if isinstance(item, dict) and "nested" in item)
        assert untouched["nested"]["value"] is True
    assert config.get_provider("tenant/model").extra_body == {"nested": {"value": True}}
    primary = config.get_provider("tenant/model")
    for value in (1, 1.0):
        primary.extra_body["nested"]["value"] = value
        current = resolve(config, resolver)
        assert current.provider is not second.provider
        second = current
    assert len(created) == 4  # default, bool, int, float
    await resolver.aclose()


@pytest.mark.asyncio
async def test_replacement_and_invalidation_do_not_close_active_borrowers(configured_override):
    config, resolver, created = configured_override
    first = resolve(config, resolver)
    resolve(config, resolver, "tenant/other")
    before_invalidate = resolve(config, resolver)
    assert before_invalidate.provider is not first.provider
    resolver.invalidate()
    after_invalidate = resolve(config, resolver)
    assert after_invalidate.provider is not before_invalidate.provider
    assert resolve(config, resolver).provider is after_invalidate.provider
    resolver.refresh()  # No loader is also an explicit invalidation boundary.
    after_refresh = resolve(config, resolver)
    assert after_refresh.provider is not after_invalidate.provider
    resolver.adopt_snapshot(factory.build_provider_snapshot(config))
    assert resolve(config, resolver).provider is not after_refresh.provider
    assert all(provider.aclose.await_count == 0 for provider in created)
    assert (await first.provider.chat(messages=[])).content == "ok"
    await resolver.aclose()
    await resolver.aclose()
    assert all(provider.aclose.await_count == 1 for provider in created)


@pytest.mark.asyncio
async def test_late_fallback_keeps_captured_credentials_body_and_proxy(configured_override, monkeypatch):
    config, resolver, created = configured_override
    config.agents.defaults.fallback_models = ["backup"]
    backup = config.get_provider(preset=config.model_presets["backup"])
    backup.use_proxy = True
    backup.extra_body = {"metadata": {"token": "old-body"}}
    config.network.proxy = "${NANOBOT_REUSE_TEST_PROXY}"
    monkeypatch.setenv("NANOBOT_REUSE_TEST_PROXY", "http://old-proxy.test:9000")
    first = resolve(config, resolver)
    entered, release = asyncio.Event(), asyncio.Event()

    async def fail_primary(**_kwargs):
        entered.set()
        await release.wait()
        return LLMResponse(content="temporarily unavailable", finish_reason="error", error_kind="server_error")

    created[-1].chat = fail_primary
    pending = asyncio.create_task(first.provider.chat(messages=[], model=first.model))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        backup.api_key = "new-backup"
        backup.extra_body["metadata"]["token"] = "new-body"
        monkeypatch.setenv("NANOBOT_REUSE_TEST_PROXY", "http://new-proxy.test:9000")
        second = resolve(config, resolver)
        assert second.provider is not first.provider
        resolver.invalidate()
        release.set()
        assert (await asyncio.wait_for(pending, timeout=2)).content == "ok"
        late = created[-1]
        owned, preset = late.factory_config, late.factory_preset
        assert owned.get_api_key(preset=preset) == "backup-fixture"
        assert owned.get_provider(preset=preset).extra_body == {"metadata": {"token": "old-body"}}
        assert owned.network.resolve_proxy(True) == "http://old-proxy.test:9000"
        late.aclose.assert_awaited_once()
        assert all(provider.aclose.await_count == 0 for provider in created[:-1])
    finally:
        release.set()
        if not pending.done():
            await pending
        await resolver.aclose()
    assert all(provider.aclose.await_count == 1 for provider in created)


@pytest.mark.asyncio
async def test_non_json_override_keeps_existing_construction_contract(configured_override):
    config, resolver, created = configured_override
    first = resolve(config, resolver)

    class OpaqueValue:
        def __eq__(self, other):
            raise AssertionError("cache must not compare application objects")

    config.get_provider("tenant/model").extra_body = {"value": OpaqueValue()}
    for _ in range(2):
        assert (await resolve(config, resolver).provider.chat(messages=[])).content == "ok"
    config.get_provider("tenant/model").extra_body = {"nested": {"value": True}}
    assert resolve(config, resolver).provider is first.provider
    assert len(created) == 4
    await resolver.aclose()


@pytest.mark.asyncio
async def test_sdk_stream_survives_reuse_replacement_and_invalidation(configured_override, tmp_path):
    from nanobot.bus.events import OutboundMessage
    from nanobot.nanobot import Nanobot

    config, fixture_resolver, created = configured_override
    path = tmp_path / "config.json"
    path.write_text(config.model_dump_json(), encoding="utf-8")
    bot = Nanobot.from_config(path, workspace=tmp_path / "workspace")
    initial = bot._loop.runtime_resolver.runtime
    entered, release = asyncio.Event(), asyncio.Event()
    admitted = []

    async def process(message, *, session_key, hooks, runtime, **_kwargs):
        admitted.append(runtime)
        if message == "stream":
            entered.set()
            await release.wait()
        assert runtime.provider.aclose.await_count == 0
        return OutboundMessage(channel="cli", chat_id="direct", content=message)

    bot._loop.process_direct = process
    try:
        stream = await bot.run_streamed("stream", model="tenant/override", session_key="sdk:stream")
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert (await bot.run("same", model="tenant/override", session_key="sdk:same")).content == "same"
        assert admitted[0].provider is admitted[1].provider
        await bot.run("different", model="tenant/other", session_key="sdk:other")
        bot._loop.runtime_resolver.invalidate()
        assert not stream.done
        assert bot._loop.runtime_resolver.runtime is initial
        release.set()
        assert (await stream.wait()).content == "stream"
    finally:
        release.set()
        await bot.aclose()
    # The fixture resolver has its own initial provider, not owned by bot.
    assert all(provider.aclose.await_count == 1 for provider in created[1:])
    await fixture_resolver.aclose()


@pytest.mark.asyncio
async def test_same_effective_signature_still_validates_preset_input(configured_override):
    config, resolver, created = configured_override
    config.agents.defaults.model_preset = "codex"
    config.model_presets["codex"] = ModelPresetConfig(
        model="openai_codex/base", provider="openai_codex",
    )
    config.providers.openai_codex.extra_headers = {"X-Route": "fixture"}
    first = resolve(config, resolver, "openai_codex/override")
    # Connection headers and preset headers merge to the same effective signature,
    # but Codex does not support a preset-level header override.
    config.model_presets["codex"].extra_headers = {"X-Route": "fixture"}
    with pytest.raises(ValueError, match="extra_headers is not supported"):
        resolve(config, resolver, "openai_codex/override")
    config.model_presets["codex"].extra_headers = None
    assert resolve(config, resolver, "openai_codex/override").provider is first.provider
    assert len(created) == 2
    await resolver.aclose()


@pytest.mark.asyncio
async def test_equivalent_invalid_fallback_is_not_hidden_by_reuse(configured_override):
    config, resolver, created = configured_override
    config.agents.defaults.fallback_models = ["backup"]
    fallback = config.model_presets["backup"]
    fallback.provider = "openai_codex"
    fallback.model = "openai_codex/backup"
    config.providers.openai_codex.extra_headers = {"X-Route": "fixture"}
    error = LLMResponse(content="temporarily unavailable", finish_reason="error", error_kind="server_error")
    first = resolve(config, resolver)
    first.provider._primary.chat = AsyncMock(return_value=error)
    assert (await first.provider.chat(messages=[], model=first.model)).content == "ok"

    fallback.extra_headers = {"X-Route": "fixture"}
    second = resolve(config, resolver)  # Invalid fallback setup must remain lazy.
    second.provider._primary.chat = AsyncMock(return_value=error)
    result = await second.provider.chat(messages=[], model=second.model)
    assert result.finish_reason == "error"
    assert second.provider is not first.provider
    await resolver.aclose()
    assert all(provider.aclose.await_count == 1 for provider in created)
