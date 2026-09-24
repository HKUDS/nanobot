import asyncio

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundAdmission, InboundMessage, SessionInitialization
from nanobot.bus.outbound_events import TurnEndEvent, TurnModelUpdatedEvent
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ModelPresetConfig
from nanobot.nanobot import Nanobot
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse
from nanobot.providers.factory import ProviderSnapshot
from nanobot.sdk.types import SessionSnapshot
from nanobot.session.model_selection import (
    SESSION_MODEL_PRESET_METADATA_KEY,
    SessionInitializationConflictError,
    model_preset_from_metadata,
)
from nanobot.session.webui_turns import WebuiTurnCoordinator, WebuiTurnRoutePolicy
from nanobot.utils.llm_runtime import LLMRuntime


class RecordingProvider(LLMProvider):
    def __init__(self, name: str) -> None:
        super().__init__(provider_name=name)
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
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
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
@pytest.mark.parametrize("channel", ["websocket", "matrix"])
async def test_initialized_first_turn_uses_model_preset_context_window(
    tmp_path,
    channel: str,
) -> None:
    bus = MessageBus()
    default = RecordingProvider("default-model")
    codex = RecordingProvider("openai-codex/gpt-5.6")
    presets = {
        "Codex": ModelPresetConfig(
            model="openai-codex/gpt-5.6",
            context_window_tokens=262_144,
        ),
    }

    def load_preset(name: str) -> ProviderSnapshot:
        preset = presets[name]
        return ProviderSnapshot(
            provider=codex,
            model=preset.model,
            context_window_tokens=preset.context_window_tokens,
            signature=(name, preset.model),
        )

    loop = AgentLoop(
        bus=bus,
        provider=default,
        workspace=tmp_path,
        model="default-model",
        context_window_tokens=200_000,
        model_presets=presets,
        preset_snapshot_loader=load_preset,
    )
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    coordinator = WebuiTurnCoordinator(
        bus=bus,
        sessions=loop.sessions,
        schedule_background=lambda coro: coro.close(),
    )
    unsubscribe = coordinator.subscribe()
    loop.turn_delivery_factory.route_policy = WebuiTurnRoutePolicy(loop.sessions)
    msg = InboundMessage(
        channel=channel,
        sender_id="client",
        chat_id="new-chat",
        content="hello",
        metadata={"webui": True},
        session_initialization=SessionInitialization(model_preset="codex"),
    )
    delivery = loop.turn_delivery_factory.create(msg, msg.session_key)

    try:
        response = await loop._process_message(msg, delivery=delivery)
        await delivery.complete(response, publish_completion=True)

        outbounds = [
            await bus.consume_outbound()
            for _ in range(bus.outbound_size)
        ]
        session = loop.sessions.get_or_create(msg.session_key)
        runtime = loop.runtime_for_session(session)
        if channel == "websocket":
            model_event = next(
                outbound.event
                for outbound in outbounds
                if isinstance(outbound.event, TurnModelUpdatedEvent)
            )
            turn_end = next(
                outbound.event
                for outbound in outbounds
                if isinstance(outbound.event, TurnEndEvent)
            )
            assert model_event.model_preset == "Codex"
            assert model_event.context_window_tokens == 262_144
            assert turn_end.context_window_tokens == 262_144

        assert runtime.context_window_tokens == 262_144
        assert codex.calls == ["openai-codex/gpt-5.6"]
        assert default.calls == []
        assert model_preset_from_metadata(session.metadata) == "Codex"
        loop.sessions.invalidate(msg.session_key)
        restored = loop.sessions.get_or_create(msg.session_key)
        assert model_preset_from_metadata(restored.metadata) == "Codex"
    finally:
        unsubscribe()
        await loop.aclose()


@pytest.mark.asyncio
async def test_removed_session_model_preset_falls_back_and_clears_metadata(tmp_path) -> None:
    base = RecordingProvider("base-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=base,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=16_000,
    )
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    session_key = "sdk:removed-preset"
    session = loop.sessions.get_or_create(session_key)
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "removed"
    loop.sessions.save(session)

    reply = await loop.process_direct("hello", session_key=session_key)

    assert reply is not None
    assert reply.content == "reply from base-model"
    assert base.calls == ["base-model"]
    loop.sessions.invalidate(session_key)
    restored = loop.sessions.get_or_create(session_key)
    assert model_preset_from_metadata(restored.metadata) is None


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
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
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
        context_window_tokens=16_000,
    )
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
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
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    bot = Nanobot(loop)

    await bot.sessions.ingest(
        "sdk:invalid-internal-metadata",
        [],
        metadata={SESSION_MODEL_PRESET_METADATA_KEY: invalid_value},
    )

    with pytest.raises(ValueError, match="session model preset must be a non-empty string"):
        await bot.run("hello", session_key="sdk:invalid-internal-metadata")

    assert base.calls == []


class BlockingRecordingProvider(RecordingProvider):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.calls.append(model)
        self.entered.set()
        await self.release.wait()
        return LLMResponse(content=f"reply from {self.name}", finish_reason="stop")


@pytest.mark.asyncio
async def test_session_initialization_admission_semantics(tmp_path) -> None:
    base = RecordingProvider("base-model")
    fast = RecordingProvider("fast-model")
    deep = RecordingProvider("deep-model")
    providers = {"Fast": fast, "Deep": deep}
    presets = {
        "Fast": ModelPresetConfig(model="fast-model", context_window_tokens=16_000),
        "Deep": ModelPresetConfig(model="deep-model", context_window_tokens=32_000),
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
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]

    default_msg = InboundMessage("discord", "user", "default", "hello")
    default_session = loop._admit_message_session(default_msg, default_msg.session_key)
    assert model_preset_from_metadata(default_session.metadata) is None

    invalid_msg = InboundMessage(
        "matrix",
        "user",
        "invalid",
        "hello",
        session_initialization=SessionInitialization(model_preset="Missing"),
    )
    with pytest.raises(KeyError, match="Missing"):
        loop._admit_message_session(invalid_msg, invalid_msg.session_key)
    assert loop.sessions.get_cached(invalid_msg.session_key) is None
    assert base.calls == []

    first = InboundMessage(
        "telegram",
        "user",
        "initialized",
        "hello",
        session_initialization=SessionInitialization(model_preset=" fast "),
    )
    session = loop._admit_message_session(first, first.session_key)
    assert model_preset_from_metadata(session.metadata) == "Fast"

    replay = InboundMessage(
        "telegram",
        "user",
        "initialized",
        "again",
        session_initialization=SessionInitialization(model_preset="FAST"),
    )
    assert loop._admit_message_session(replay, replay.session_key) is session

    conflict = InboundMessage(
        "telegram",
        "user",
        "initialized",
        "conflict",
        session_initialization=SessionInitialization(model_preset="Deep"),
    )
    with pytest.raises(SessionInitializationConflictError):
        loop._admit_message_session(conflict, conflict.session_key)
    assert model_preset_from_metadata(session.metadata) == "Fast"

    late = InboundMessage(
        "discord",
        "user",
        "default",
        "late",
        session_initialization=SessionInitialization(model_preset="Fast"),
    )
    with pytest.raises(SessionInitializationConflictError):
        loop._admit_message_session(late, late.session_key)

    await loop.aclose()


@pytest.mark.asyncio
async def test_concurrent_first_messages_initialize_session_once(tmp_path) -> None:
    base = RecordingProvider("base-model")
    fast = BlockingRecordingProvider("fast-model")
    deep = RecordingProvider("deep-model")
    presets = {
        "Fast": ModelPresetConfig(model="fast-model", context_window_tokens=16_000),
        "Deep": ModelPresetConfig(model="deep-model", context_window_tokens=32_000),
    }

    def load_preset(name: str) -> ProviderSnapshot:
        preset = presets[name]
        return ProviderSnapshot(
            provider={"Fast": fast, "Deep": deep}[name],
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
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    first = InboundMessage(
        "matrix",
        "user",
        "same-chat",
        "first",
        session_initialization=SessionInitialization(model_preset="Fast"),
    )
    conflicting = InboundMessage(
        "matrix",
        "user",
        "same-chat",
        "second",
        session_initialization=SessionInitialization(model_preset="Deep"),
    )
    assert loop._can_inject_message(first) is False

    first_task = asyncio.create_task(loop._dispatch_one(first, asyncio.Queue()))
    await fast.entered.wait()
    conflicting_task = asyncio.create_task(loop._dispatch_one(conflicting, asyncio.Queue()))
    await asyncio.sleep(0)
    assert conflicting_task.done() is False

    fast.release.set()
    await asyncio.gather(first_task, conflicting_task)

    session = loop.sessions.get_or_create(first.session_key)
    assert model_preset_from_metadata(session.metadata) == "Fast"
    assert fast.calls == ["fast-model"]
    assert deep.calls == []
    assert base.calls == []
    await loop.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "has_active_queue"),
    [("/status", False), ("/model Deep", True)],
)
async def test_run_rejects_initialized_commands_before_inline_dispatch(
    tmp_path,
    content: str,
    has_active_queue: bool,
) -> None:
    base = RecordingProvider("base-model")
    deep = RecordingProvider("deep-model")
    presets = {
        "Deep": ModelPresetConfig(model="deep-model", context_window_tokens=32_000),
    }

    def load_preset(name: str) -> ProviderSnapshot:
        preset = presets[name]
        return ProviderSnapshot(
            provider=deep,
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
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    msg = InboundMessage(
        "websocket",
        "user",
        "initialized-command",
        content,
        metadata={"webui_turn_id": "turn-command"},
        session_initialization=SessionInitialization(model_preset="Missing"),
        admission=InboundAdmission(),
    )
    if has_active_queue:
        loop._pending_queues[msg.session_key] = asyncio.Queue()

    consume_count = 0

    async def consume_once() -> InboundMessage:
        nonlocal consume_count
        consume_count += 1
        if consume_count == 1:
            return msg
        loop.stop()
        raise asyncio.TimeoutError

    loop.bus.consume_inbound = consume_once  # type: ignore[method-assign]

    await loop.run()

    assert consume_count == 2
    assert msg.admission is not None
    assert not (await msg.admission.wait()).accepted
    assert loop.sessions.get_cached(msg.session_key) is None
    assert deep.calls == []
    assert base.calls == []


@pytest.mark.asyncio
async def test_cancelled_initialization_does_not_create_a_session(tmp_path) -> None:
    loop = AgentLoop(
        bus=MessageBus(), provider=RecordingProvider("base"), workspace=tmp_path,
        model="base",
    )
    admission = InboundAdmission()
    msg = InboundMessage(
        "websocket", "user", "cancelled", "hello",
        session_initialization=SessionInitialization(model_preset="Fast"),
        admission=admission,
    )
    async with loop._get_session_lock(msg.session_key):
        task = asyncio.create_task(loop._dispatch_one(msg, asyncio.Queue()))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not (await admission.wait()).accepted
    assert loop.sessions.get_cached(msg.session_key) is None
    assert loop.sessions.list_sessions() == []
    await loop.aclose()
