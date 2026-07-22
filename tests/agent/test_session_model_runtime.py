import asyncio

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ModelPresetConfig
from nanobot.nanobot import Nanobot
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse
from nanobot.providers.factory import ProviderSnapshot
from nanobot.sdk.types import SessionSnapshot
from nanobot.session.model_selection import (
    SESSION_MODEL_PRESET_METADATA_KEY,
    model_preset_from_metadata,
)
from nanobot.utils.llm_runtime import LLMRuntime


class RecordingProvider(LLMProvider):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.generation = GenerationSettings(max_tokens=256, temperature=0.1)
        self.calls: list[str | None] = []

    async def chat(self, messages, tools=None, model=None, **kwargs):
        await asyncio.sleep(0)
        self.calls.append(model)
        return LLMResponse(content=f"reply from {self.name}", finish_reason="stop")

    def get_default_model(self) -> str:
        return self.name


@pytest.mark.asyncio
async def test_sessions_run_concurrently_with_isolated_model_presets(tmp_path) -> None:
    base = RecordingProvider("base-model")
    fast = RecordingProvider("fast-model")
    deep = RecordingProvider("deep-model")
    providers = {"fast": fast, "deep": deep}
    load_counts = {"fast": 0, "deep": 0}
    presets = {
        "default": ModelPresetConfig(model="base-model", context_window_tokens=8_000),
        "fast": ModelPresetConfig(model="fast-model", context_window_tokens=16_000),
        "deep": ModelPresetConfig(model="deep-model", context_window_tokens=32_000),
    }

    def load_preset(name: str) -> ProviderSnapshot:
        load_counts[name] += 1
        preset = presets[name]
        provider = base if name == "default" else providers[name]
        return ProviderSnapshot(
            provider=provider,
            model=preset.model,
            context_window_tokens=preset.context_window_tokens,
            signature=(name, preset.model),
        )

    loop = AgentLoop(
        bus=MessageBus(),
        provider=base,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=8_000,
        model_presets=presets,
        preset_snapshot_loader=load_preset,
    )
    loop._schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    loop.set_session_model_preset("sdk:fast", "fast")
    loop.set_session_model_preset("sdk:deep", "deep")

    fast_reply, deep_reply = await asyncio.gather(
        loop.process_direct("hello", session_key="sdk:fast"),
        loop.process_direct("hello", session_key="sdk:deep"),
    )

    assert fast_reply is not None and fast_reply.content == "reply from fast-model"
    assert deep_reply is not None and deep_reply.content == "reply from deep-model"
    assert fast.calls == ["fast-model"]
    assert deep.calls == ["deep-model"]
    assert base.calls == []
    assert loop.provider is base
    assert loop.model == "base-model"
    assert load_counts == {"fast": 1, "deep": 1}

    loop.sessions.invalidate("sdk:fast")
    restored = loop.sessions.get_or_create("sdk:fast")
    assert model_preset_from_metadata(restored.metadata) == "fast"

    override = RecordingProvider("override-model")
    override_runtime = LLMRuntime.capture(
        override,
        "override-model",
        context_window_tokens=24_000,
    )
    override_reply = await loop.process_direct(
        "hello",
        session_key="sdk:fast",
        runtime=override_runtime,
    )

    assert override_reply is not None
    assert override_reply.content == "reply from override-model"
    assert override.calls == ["override-model"]
    assert fast.calls == ["fast-model"]
    assert load_counts == {"fast": 1, "deep": 1}


@pytest.mark.asyncio
async def test_streamed_sdk_resolves_session_runtime_after_lock_admission(tmp_path) -> None:
    base = RecordingProvider("base-model")
    fast = RecordingProvider("fast-model")
    deep = RecordingProvider("deep-model")
    providers = {"fast": fast, "deep": deep}
    presets = {
        "fast": ModelPresetConfig(model="fast-model", context_window_tokens=16_000),
        "deep": ModelPresetConfig(model="deep-model", context_window_tokens=32_000),
    }

    def load_preset(name: str) -> ProviderSnapshot:
        preset = presets[name]
        return ProviderSnapshot(
            provider=providers[name],
            model=preset.model,
            context_window_tokens=preset.context_window_tokens,
            signature=(name, preset.model),
        )

    loop = AgentLoop(
        bus=MessageBus(),
        provider=base,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=8_000,
        model_presets=presets,
        preset_snapshot_loader=load_preset,
    )
    loop._schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    session_key = "sdk:queued"
    loop.set_session_model_preset(session_key, "fast")

    lock = loop._session_locks.setdefault(session_key, asyncio.Lock())
    await lock.acquire()
    try:
        run = await Nanobot(loop).run_streamed("hello", session_key=session_key)
        loop.set_session_model_preset(session_key, "deep")
    finally:
        lock.release()

    events = [event async for event in run.stream_events()]
    result = await run.wait()

    assert result.content == "reply from deep-model"
    assert fast.calls == []
    assert deep.calls == ["deep-model"]
    assert events[0].type == "run.started"
    assert events[0].metadata["model"] == "deep-model"
    assert events[0].metadata["model_preset"] == "deep"


@pytest.mark.parametrize("custom_value", ["legacy-tag", 7])
@pytest.mark.asyncio
async def test_sdk_custom_model_preset_metadata_does_not_select_runtime(
    tmp_path,
    custom_value,
) -> None:
    base = RecordingProvider("base-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=base,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=8_000,
    )
    loop._schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    bot = Nanobot(loop)

    await bot.sessions.ingest(
        "sdk:custom-metadata",
        [],
        metadata={"model_preset": custom_value},
    )
    ingested_result = await bot.run("hello", session_key="sdk:custom-metadata")
    exported = bot.sessions.export("sdk:custom-metadata")
    restored = await bot.sessions.restore(
        SessionSnapshot(
            key="sdk:restored-metadata",
            messages=[],
            metadata={"model_preset": custom_value},
        )
    )
    restored_result = await bot.run("hello", session_key=restored.key)

    assert ingested_result.content == "reply from base-model"
    assert restored_result.content == "reply from base-model"
    assert base.calls == ["base-model", "base-model"]
    assert exported is not None
    assert exported.metadata["model_preset"] == custom_value
    assert restored.metadata["model_preset"] == custom_value


@pytest.mark.parametrize("invalid_value", [{"invalid": True}, "  "])
@pytest.mark.asyncio
async def test_sdk_invalid_internal_model_preset_metadata_fails_explicitly(
    tmp_path,
    invalid_value,
) -> None:
    base = RecordingProvider("base-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=base,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=8_000,
    )
    loop._schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    bot = Nanobot(loop)

    await bot.sessions.ingest(
        "sdk:invalid-internal-metadata",
        [],
        metadata={SESSION_MODEL_PRESET_METADATA_KEY: invalid_value},
    )

    with pytest.raises(ValueError, match="session model preset must be a non-empty string"):
        await bot.run("hello", session_key="sdk:invalid-internal-metadata")

    assert base.calls == []
