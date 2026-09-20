"""Actual invocation identity survives delivery and the display transcript."""

import asyncio
import json
from copy import deepcopy
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import StreamDeltaEvent, StreamEndEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.events import EventSink, ResponseSource, ResponseSourceEvent
from nanobot.providers.base import LLMProvider, LLMResponse, ProviderCallContext
from nanobot.providers.factory import make_provider, provider_signature
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.webui.transcript import (
    WebUITranscriptRecorder,
    append_transcript_object,
    build_webui_thread_response,
    webui_transcript_path,
)


class AnswerProvider(LLMProvider):
    def __init__(self, name, text="answer", *, fail=False, chunks=()):
        super().__init__(provider_name=name)
        self.text, self.fail, self.chunks = text, fail, chunks

    def get_default_model(self):
        return "same-model"

    async def chat(self, **kwargs):
        return LLMResponse(
            content=self.text,
            finish_reason="error" if self.fail else "stop",
            error_status_code=401 if self.fail else None,
        )

    async def chat_stream(self, on_content_delta=None, **kwargs):
        if on_content_delta:
            for text in self.chunks:
                await asyncio.sleep(0)
                await on_content_delta(text)
        return await self.chat(**kwargs)


def delivery(chat="chat", *, streaming=True):
    bus = MessageBus()
    turn = TurnDeliveryFactory(bus).create(InboundMessage(
        channel="websocket", sender_id="user", chat_id=chat, content="hello",
        metadata={"_wants_stream": streaming, "webui_turn_id": f"turn-{chat}"},
    ), f"websocket:{chat}", enable_stream=streaming)
    return bus, turn


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("failures", [0, 1, 2, 3])
async def test_actual_candidate_is_delivered_and_replayed(
    streaming,
    failures,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    bus, turn = delivery(streaming=streaming)
    candidates = [AnswerProvider(
        f"provider-{i}", fail=i < failures,
        chunks=("answer",) if streaming and i >= failures else (),
    ) for i in range(3)]
    fallback = FallbackProvider(
        candidates[0], [ModelPresetConfig(model="same-model")] * 2,
        lambda _: candidates.pop(1), fallback_preset_names=["backup-one", "backup-two"],
    )

    async def delta(text):
        await turn.events.emit(StreamDeltaEvent(text))

    result = await fallback.chat_stream_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        model="same-model", on_content_delta=delta if streaming else None,
        provider_context=ProviderCallContext(events=turn.events, response_preset="chosen"),
    )
    if streaming:
        await turn.events.emit(StreamEndEvent())
    else:
        turn.record_stop_reason("error" if result.finish_reason == "error" else "completed")
        await turn.complete(OutboundMessage(
            channel="websocket", chat_id="chat", content=result.content or "",
        ), publish_completion=False)
    records = []
    recorder = WebUITranscriptRecorder()
    while not bus.outbound.empty():
        msg = bus.outbound.get_nowait()
        if msg.event is not None and not isinstance(msg.event, StreamDeltaEvent | StreamEndEvent):
            continue
        record = {
            "event": "stream_end" if isinstance(msg.event, StreamEndEvent) else
                "delta" if isinstance(msg.event, StreamDeltaEvent) else "message",
            "text": "answer" if isinstance(msg.event, StreamEndEvent) and failures < 3 else msg.content,
        }
        recorder.prepare_event("chat", record, metadata=msg.metadata, phase="answer", include_source=True)
        records.append(record)
    # Completed segment is the durable record; token-sized deltas aren't needed on replay.
    for record in (r for r in records if r["event"] != "delta"):
        append_transcript_object("websocket:chat", record)
    replay = build_webui_thread_response("websocket:chat")
    if failures == 3:
        assert all(not r.get("response_sources") for r in records)
        if replay is None:
            return
        replayed_answers = [
            event for event in replay["events"]
            if event["event"] in {"message", "stream_end"}
        ]
        assert all(not event.get("response_sources") for event in replayed_answers)
    else:
        assert replay is not None
        replayed_answers = [
            event for event in replay["events"]
            if event["event"] in {"message", "stream_end"}
        ]
        expected = [{"provider": f"provider-{failures}", "model": "same-model",
                     "preset": ["chosen", "backup-one", "backup-two"][failures],
                     "fallback": failures > 0}]
        assert all(r.get("response_sources") == expected for r in records)
        assert replayed_answers[-1]["response_sources"] == expected


async def test_fallback_flag_is_call_scoped_even_with_identical_identity():
    seen = []

    async def publish(event):
        if isinstance(event, ResponseSourceEvent) and event.source is not None:
            seen.append(event.source)

    primary = AnswerProvider("openai", fail=True)
    provider = FallbackProvider(
        primary, [ModelPresetConfig(model="same-model")], lambda _: AnswerProvider("openai"),
        fallback_preset_names=["chosen"],
    )
    context = ProviderCallContext(events=EventSink(publish), response_preset="chosen")
    await provider.chat_with_retry(messages=[], provider_context=context)
    primary.fail = False
    await provider.chat_with_retry(messages=[], provider_context=context)
    assert seen == [
        ResponseSource("openai", "same-model", "chosen", fallback=True),
        ResponseSource("openai", "same-model", "chosen", fallback=False),
    ]


async def test_auxiliary_calls_do_not_publish_response_identity():
    seen = []

    async def publish(event):
        seen.append(event)

    await AnswerProvider("auxiliary").chat_stream_with_retry(
        messages=[], provider_context=ProviderCallContext(events=EventSink(publish)),
    )
    assert not any(isinstance(event, ResponseSourceEvent) for event in seen)


@pytest.mark.parametrize("with_tools", [False, True])
@pytest.mark.parametrize("with_images", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
async def test_attribution_does_not_change_provider_requests(with_tools, with_images, fallback):
    """Display metadata must not modify the cacheable prompt or generation payload."""
    requests = []

    class CapturingProvider(AnswerProvider):
        async def chat(self, **kwargs):
            requests.append((self.provider_name, deepcopy({
                key: value for key, value in kwargs.items() if not key.startswith("on_")
            })))
            if with_images and len(requests) == 1:
                return LLMResponse(content="Images unsupported", finish_reason="error",
                                   error_status_code=400)
            return await super().chat(**kwargs)

    messages = [{"role": "system", "content": "Stable system prompt"},
                {"role": "user", "content": "Hello"}]
    if with_images:
        messages[-1]["content"] = [
            {"type": "text", "text": "Hello"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
    tools = [{"type": "function", "function": {"name": "test_tool", "parameters": {
        "type": "object", "properties": {},
    }}}] if with_tools else None
    original = deepcopy(messages)
    results = []
    for preset in (None, "primary"):
        requests.clear()
        provider = FallbackProvider(
            CapturingProvider("primary", fail=fallback),
            [ModelPresetConfig(model="same-model")], lambda _: CapturingProvider("backup"),
            fallback_preset_names=["backup"],
        )
        result = await provider.chat_stream_with_retry(
            messages=deepcopy(messages), tools=tools, model="same-model",
            provider_context=ProviderCallContext(events=EventSink(AsyncMock()), response_preset=preset),
        )
        assert result.content == "answer"
        results.append(deepcopy(requests))
    assert results[0] == results[1]
    assert messages == original


@pytest.mark.parametrize("streaming", [False, True])
async def test_synthetic_final_text_does_not_inherit_an_earlier_model(streaming):
    bus, turn = delivery(streaming=streaming)
    await turn.events.emit(ResponseSourceEvent(ResponseSource("openai", "gpt", "codex"), "Working"))
    if streaming:
        await turn.events.emit(StreamDeltaEvent("Reached the iteration limit"))
        await turn.events.emit(StreamEndEvent())
    else:
        await turn.complete(OutboundMessage(channel="websocket", chat_id="chat", content="Reached the iteration limit"), publish_completion=False)
    while not bus.outbound.empty():
        assert not bus.outbound.get_nowait().metadata.get("response_sources")


async def test_unnamed_fallback_does_not_borrow_the_primary_preset():
    bus, turn = delivery()
    provider = FallbackProvider(AnswerProvider("openai", fail=True), [ModelPresetConfig(model="grok")],
                                lambda _: AnswerProvider("xai", chunks=("answer",)))

    async def delta(text):
        await turn.events.emit(StreamDeltaEvent(text))

    await provider.chat_stream_with_retry(messages=[], on_content_delta=delta,
        provider_context=ProviderCallContext(events=turn.events, response_preset="primary"))
    await turn.events.emit(StreamEndEvent())
    while not bus.outbound.empty():
        assert not bus.outbound.get_nowait().metadata.get("response_sources")


async def test_concurrent_calls_and_segments_have_independent_snapshots():
    async def run(chat, preset):
        bus, turn = delivery(chat)

        async def delta(text):
            await turn.events.emit(StreamDeltaEvent(text))

        await AnswerProvider("openai", chunks=("one", "two")).chat_stream_with_retry(
            messages=[], on_content_delta=delta,
            provider_context=ProviderCallContext(events=turn.events, response_preset=preset),
        )
        await turn.events.emit(StreamEndEvent())
        return [bus.outbound.get_nowait() for _ in range(bus.outbound.qsize())]

    left, right = await asyncio.gather(run("left", "writer"), run("right", "reviewer"))
    assert {m.metadata["response_sources"][0]["preset"] for m in left if isinstance(m.event, StreamDeltaEvent | StreamEndEvent)} == {"writer"}
    assert {m.metadata["response_sources"][0]["preset"] for m in right if isinstance(m.event, StreamDeltaEvent | StreamEndEvent)} == {"reviewer"}


async def test_merged_segments_keep_all_actual_sources_and_unknown_text_is_not_mislabeled():
    bus, turn = delivery()
    a = ResponseSource("openai", "a", "writer")
    b = ResponseSource("xai", "b", "reviewer", fallback=True)
    for source in (a, b):
        await turn.events.emit(ResponseSourceEvent(source))
        await turn.events.emit(StreamDeltaEvent("text"))
        await turn.events.emit(StreamEndEvent(resuming=True, merge_next=True))
    assert bus.outbound.get_nowait().metadata["response_sources"] == [asdict(a)]
    bus.outbound.get_nowait()
    assert bus.outbound.get_nowait().metadata["response_sources"] == [asdict(a), asdict(b)]
    bus.outbound.get_nowait()
    await turn.events.emit(ResponseSourceEvent(None))
    await turn.events.emit(StreamDeltaEvent("unattributed text"))
    await turn.events.emit(StreamEndEvent())
    assert bus.outbound.get_nowait().metadata["response_sources"] == []
    assert bus.outbound.get_nowait().metadata["response_sources"] == []
    await turn.events.emit(ResponseSourceEvent(b))
    await turn.events.emit(StreamDeltaEvent("new segment"))
    assert bus.outbound.get_nowait().metadata["response_sources"] == [asdict(b)]


def test_factory_captures_names_even_when_models_and_settings_are_identical():
    config = Config.model_validate({
        "agents": {"defaults": {"modelPreset": "primary", "fallbackModels": ["backup"]}},
        "modelPresets": {name: {"provider": "openai", "model": "same-model"}
                         for name in ("primary", "backup", "renamed")},
        "providers": {"openai": {"apiKey": "test-only"}},
    })
    before = provider_signature(config)
    provider = make_provider(config)
    config.agents.defaults.fallback_models = ["renamed"]
    assert provider_signature(config) != before
    assert provider._fallback_preset_names == ("backup",)
    assert make_provider(config)._fallback_preset_names == ("renamed",)


def test_old_history_and_malformed_identity_are_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    records = [
        {"event": "message", "text": "legacy"},
        {"event": "message", "text": "invalid", "response_sources": [{"model": "gpt"}]},
        {"event": "message", "text": "recorded", "response_sources": [
            {"provider": "xai", "model": "grok", "preset": "old name", "api_key": "never expose"},
        ]},
        {"event": "message", "text": "invalid flag", "response_sources": [
            {"provider": "xai", "model": "grok", "preset": "old name", "fallback": "true"},
        ]},
    ]
    for record in records:
        append_transcript_object("websocket:source-history", record)
    replay = build_webui_thread_response("websocket:source-history")
    assert replay is not None
    events = replay["events"]
    assert "response_sources" not in events[0]
    assert events[1]["response_sources"] == []
    expected = [{"provider": "xai", "model": "grok", "preset": "old name", "fallback": False}]
    assert events[2]["response_sources"] == expected
    assert events[3]["response_sources"] == expected


async def test_runner_records_each_provider_when_streaming_times_out_and_recovers():
    class StalledProvider(AnswerProvider):
        _CHAT_RETRY_DELAYS = ()

        async def chat(self, **kwargs):
            return LLMResponse(content="stalled", finish_reason="error", error_kind="timeout")

    bus, turn = delivery()
    primary = StalledProvider("openai_codex", chunks=("Partial answer",))
    backup = AnswerProvider("xai", text="Recovered answer", chunks=("Recovered answer",))
    provider = FallbackProvider(primary, [ModelPresetConfig(model="grok")], lambda _: backup,
                                fallback_preset_names=["grok"])
    runtime = LLMRuntime.capture(provider, "gpt", context_window_tokens=32_000, model_preset="codex")
    result = await AgentRunner().run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hello"}], tools=ToolRegistry(),
        runtime=runtime, max_iterations=2, max_tool_result_chars=4096,
        session_key="websocket:chat", events=turn.events,
        hook=AgentProgressHook(turn.events, streaming=True),
    ))
    assert result.final_content == "Recovered answer"
    outgoing = [bus.outbound.get_nowait() for _ in range(bus.outbound.qsize())]
    ends = [msg for msg in outgoing if isinstance(msg.event, StreamEndEvent)]
    assert [m.metadata["response_sources"][0]["preset"] for m in ends if m.metadata["response_sources"]] == ["codex", "grok"]
    assert [m.metadata["response_sources"][0]["fallback"] for m in ends if m.metadata["response_sources"]] == [False, True]
    assert len({m.event.stream_id for m in ends}) == len(ends)
    # Display provenance stays out of canonical model input/history.
    assert all("response_sources" not in message for message in result.messages)


@pytest.mark.parametrize("temporary", [False, True])
async def test_websocket_wire_and_disk_replay_preserve_sources(tmp_path, monkeypatch, temporary):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    channel = WebSocketChannel({"allowFrom": ["*"]}, MessageBus(), gateway=MagicMock())
    channel._media.rewrite_local_markdown_images.side_effect = lambda text: text
    channel._transcripts = WebUITranscriptRecorder()
    channel._temporary_chats.should_persist_transcript = lambda _: not temporary
    channel._safe_send_to = AsyncMock()
    channel._subs["source-chat"] = {MagicMock()}
    sources = [{"provider": "xai", "model": "grok", "preset": "snapshot name", "fallback": True}]
    metadata = {"webui_turn_id": "source-turn", "response_sources": sources}
    await channel.send_delta("source-chat", "Hello", metadata, stream_id="s")
    await channel.send_delta("source-chat", "", metadata, stream_id="s", stream_end=True)
    frames = [json.loads(call.args[1]) for call in channel._safe_send_to.call_args_list]
    assert [frame["event"] for frame in frames] == ["delta", "stream_end"]
    assert all(frame["response_sources"] == sources for frame in frames)
    if temporary:
        assert not webui_transcript_path("websocket:source-chat").exists()
    else:
        # A fresh reader after an unrelated preset rename/delete sees the saved snapshot.
        sources[0]["preset"] = "renamed later"
        replay = build_webui_thread_response("websocket:source-chat")
        assert replay is not None
        end = next(e for e in replay["events"] if e["event"] == "stream_end")
        assert end["response_sources"][0]["preset"] == "snapshot name"
        assert end["response_sources"][0]["fallback"] is True
