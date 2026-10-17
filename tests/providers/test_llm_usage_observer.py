from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from nanobot.llm_usage.context import current_llm_usage_source, llm_usage_source
from nanobot.llm_usage.models import LLMCallRecord
from nanobot.llm_usage.service import record_llm_call
from nanobot.llm_usage.store import LLMUsageStore
from nanobot.providers.base import LLMProvider, LLMResponse, LLMUsage
from nanobot.providers.fallback_provider import FallbackProvider


class _SequenceProvider(LLMProvider):
    _CHAT_RETRY_DELAYS = (0,)

    def __init__(self, responses: Iterator[LLMResponse]) -> None:
        super().__init__(provider_name="test-provider")
        self._responses = responses
        self.calls = 0

    async def chat(self, **_kwargs: object) -> LLMResponse:
        self.calls += 1
        return next(self._responses)

    def get_default_model(self) -> str:
        return "test-model"


class _NoRetryProvider(_SequenceProvider):
    _CHAT_RETRY_DELAYS = ()


class _EstimatingProvider(_SequenceProvider):
    def __init__(
        self, responses: Iterator[LLMResponse], estimate: Callable[[], tuple[int, str]],
    ) -> None:
        super().__init__(responses)
        self.estimate = estimate

    def estimate_prompt_tokens(self, messages, tools=None, model=None) -> tuple[int, str]:
        return self.estimate()


class _BlockingProvider(LLMProvider):
    async def chat(self, **_kwargs: object) -> LLMResponse:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def chat_stream(self, **_kwargs: object) -> LLMResponse:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    def get_default_model(self) -> str:
        return "test-model"


class _StreamingProvider(LLMProvider):
    async def chat(self, **_kwargs: object) -> LLMResponse:
        raise AssertionError("streaming path expected")

    async def chat_stream(self, **kwargs: object) -> LLMResponse:
        on_thinking_delta = kwargs.get("on_thinking_delta")
        if callable(on_thinking_delta):
            await on_thinking_delta("thinking")
        on_content_delta = kwargs.get("on_content_delta")
        if callable(on_content_delta):
            await on_content_delta("ok")
        return LLMResponse(
            content="ok",
            usage=LLMUsage.reported(input_tokens=12, output_tokens=2),
        )

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_observer_receives_every_retry_attempt(stream: bool) -> None:
    provider = _SequenceProvider(
        iter(
            [
                LLMResponse(
                    content="temporary failure",
                    finish_reason="error",
                    error_kind="timeout",
                ),
                LLMResponse(
                    content="ok",
                    usage=LLMUsage.reported(
                        input_tokens=100,
                        output_tokens=20,
                        cache_read_tokens=60,
                    ),
                ),
            ]
        )
    )
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry

    with llm_usage_source("api"):
        response = await call(
            messages=[{"role": "user", "content": "hello"}],
            model="selected-model",
        )

    assert response.finish_reason == "stop"
    assert response.content == "ok"
    assert provider.calls == 2
    assert len(events) == 2
    assert [event.finish_reason for event in events] == ["error", "stop"]
    assert all(event.provider == "test-provider" for event in events)
    assert all(event.model == "selected-model" for event in events)
    assert all(event.source == "api" for event in events)
    assert events[1].usage is not None
    assert events[1].usage.cache_read_tokens == 60
    assert events[1].usage.source == "reported"
    assert response.usage == events[1].usage


@pytest.mark.asyncio
async def test_observer_estimates_missing_success_usage_without_storing_content() -> None:
    prompt = "observer-prompt-canary-38a7cf"
    reply = "observer-response-canary-92b6de"
    provider = _SequenceProvider(iter([LLMResponse(content=reply)]))
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": prompt}],
    )

    assert response.content == reply
    assert response.finish_reason == "stop"
    assert provider.calls == 1
    assert len(events) == 1
    assert events[0].finish_reason == "stop"
    assert response.usage is not None
    assert response.usage.source == "estimated"
    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0
    assert response.usage.estimated_tokens == response.usage.total_tokens > 0
    assert events[0].usage == response.usage
    serialized = json.dumps(asdict(events[0]))
    assert prompt not in serialized
    assert reply not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_observer_failure_never_breaks_provider_call(stream: bool) -> None:
    provider = _SequenceProvider(iter([LLMResponse(content="ok")]))

    def _fail(_event: LLMCallRecord) -> None:
        raise RuntimeError("disk unavailable")

    provider.set_llm_call_observer(_fail)
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry
    response = await call(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response.content == "ok"
    assert response.usage is not None and response.usage.source == "estimated"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
async def test_missing_usage_keeps_loop_responsive_and_settles_before_cancellation(
    monkeypatch, stream: bool, cancel: bool,
) -> None:
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()
    sources = []
    worker_threads = []
    events: list[LLMCallRecord] = []
    observer_loops = []
    clock = [1_000_000_000]
    monkeypatch.setattr("nanobot.providers.base.time.monotonic_ns", lambda: clock[0])

    def estimate() -> tuple[int, str]:
        sources.append(current_llm_usage_source())
        worker_threads.append(threading.get_ident())
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5), "estimator was not released"
        finished.set()
        return 17, "provider-local"

    provider = _EstimatingProvider(iter([LLMResponse(content="hello")]), estimate)
    original_chat = provider.chat

    async def chat(**kwargs):
        response = await original_chat(**kwargs)
        clock[0] = 1_013_000_000
        return response

    monkeypatch.setattr(provider, "chat", chat)

    def observe(event: LLMCallRecord) -> None:
        observer_loops.append(asyncio.get_running_loop())
        events.append(event)

    provider.set_llm_call_observer(observe)
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry
    kwargs = {"messages": [{"role": "user", "content": "hello"}]}
    if stream:
        kwargs["on_content_delta"] = lambda _delta: asyncio.sleep(0)
    with llm_usage_source("api"):
        task = asyncio.create_task(call(**kwargs))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        beats = []

        async def heartbeat() -> None:
            for tick in range(3):
                await asyncio.sleep(0)
                beats.append(tick)

        await asyncio.wait_for(heartbeat(), timeout=1)
        assert beats == [0, 1, 2]
        assert len(worker_threads) == 1
        assert worker_threads[0] != threading.get_ident()
        assert sources == ["api"]
        assert provider.calls == 1
        assert not events
        clock[0] = 6_000_000_000
        if cancel:
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
        else:
            response = await asyncio.wait_for(task, timeout=5)
            assert response.content == "hello"
            assert response.usage == events[0].usage
        assert finished.is_set()
        assert len(events) == 1
        assert events[0].source == "api"
        assert events[0].stream == stream
        assert events[0].finish_reason == "stop"
        assert events[0].duration_ms == 13
        assert events[0].usage is not None
        assert events[0].usage.source == "estimated"
        assert events[0].usage.input_tokens == 17
        if stream:
            assert events[0].usage.ttft_ms == 13
            assert events[0].usage.generation_ms == 1
        assert observer_loops == [loop]
        assert provider.calls == 1
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_provider_bounds_estimators_and_drains_cancelled_queued_call() -> None:
    loop = asyncio.get_running_loop()
    two_entered = asyncio.Event()
    release = threading.Event()
    lock = threading.Lock()
    active = peak = completed = 0

    def estimate() -> tuple[int, str]:
        nonlocal active, peak, completed
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                loop.call_soon_threadsafe(two_entered.set)
        assert release.wait(5), "estimators were not released"
        with lock:
            active -= 1
            completed += 1
        return 17, "provider-local"

    provider = _EstimatingProvider(
        iter([LLMResponse(content=str(index)) for index in range(3)]), estimate,
    )
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)
    tasks = [asyncio.create_task(provider.chat_with_retry(messages=[])) for _ in range(3)]
    try:
        await asyncio.wait_for(two_entered.wait(), timeout=5)
        assert provider.calls == 3
        tasks[2].cancel()
        await asyncio.sleep(0)
        assert not tasks[2].done()
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
        assert isinstance(results[2], asyncio.CancelledError)
        assert [result.content for result in results[:2]] == ["0", "1"]
        assert peak == 2
        assert active == 0
        assert completed == 3
        assert len(events) == 3
        assert all(event.finish_reason == "stop" for event in events)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("kind", ["reported", "error", "unobserved"])
async def test_usage_fast_paths_skip_local_estimation(stream: bool, kind: str) -> None:
    estimates = []

    def estimate() -> tuple[int, str]:
        estimates.append(True)
        return 17, "provider-local"

    expected = LLMResponse(content="ok")
    if kind == "reported":
        expected.usage = LLMUsage.reported(input_tokens=12, output_tokens=2)
    elif kind == "error":
        expected.finish_reason = "error"
        expected.error_should_retry = False
    provider = _EstimatingProvider(iter([expected]), estimate)
    events: list[LLMCallRecord] = []
    if kind != "unobserved":
        provider.set_llm_call_observer(events.append)
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry
    response = await call(messages=[])
    assert response is expected
    assert estimates == []
    assert len(events) == (0 if kind == "unobserved" else 1)
    if kind == "reported":
        assert response.usage is not None and response.usage.source == "reported"
    else:
        assert response.usage is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_gateway_usage_observer_records_missing_usage_and_retry(
    monkeypatch, tmp_path, stream: bool,
) -> None:
    prompt = "gateway-prompt-canary-f6d5a4"
    reply = "gateway-response-canary-27be91"
    error = "gateway-error-canary-64a8cd"
    store = LLMUsageStore(tmp_path / "usage.sqlite3")
    monkeypatch.setattr("nanobot.llm_usage.service.get_llm_usage_store", lambda: store)
    provider = _SequenceProvider(iter([
        LLMResponse(content=error, finish_reason="error", error_kind="timeout"),
        LLMResponse(content=reply),
    ]))
    provider.set_llm_call_observer(record_llm_call)
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry
    try:
        with llm_usage_source("api"):
            response = await call(messages=[{"role": "user", "content": prompt}])
        assert response.content == reply
        assert response.usage is not None and response.usage.source == "estimated"
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0
        assert response.usage.estimated_tokens == response.usage.total_tokens > 0
        assert provider.calls == 2
        with closing(sqlite3.connect(store.path)) as connection:
            connection.row_factory = sqlite3.Row
            records = [dict(row) for row in connection.execute("SELECT * FROM llm_calls ORDER BY id")]
        assert len(records) == 2
        assert [record["finish_reason"] for record in records] == ["error", "stop"]
        assert records[0]["error_kind"] == "timeout"
        assert all(record["source"] == "api" for record in records)
        assert all(record["stream"] == int(stream) for record in records)
        assert records[0]["total_tokens"] is None
        assert records[1]["total_tokens"] == response.usage.total_tokens
        assert records[1]["estimated_tokens"] == response.usage.estimated_tokens
        serialized = json.dumps(records)
        for canary in (prompt, reply, error):
            assert canary not in serialized
    finally:
        store.close()


@pytest.mark.asyncio
async def test_stream_observer_records_physical_attempt_timing(monkeypatch) -> None:
    provider = _StreamingProvider(provider_name="streaming-provider")
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)
    monotonic_values = iter(
        [
            1_000_000_000,
            1_005_000_000,
            1_012_000_000,
            1_013_000_000,
        ]
    )
    monkeypatch.setattr(
        "nanobot.providers.base.time.monotonic_ns",
        lambda: next(monotonic_values),
    )

    response = await provider.chat_stream_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        on_content_delta=lambda _delta: asyncio.sleep(0),
        on_thinking_delta=lambda _delta: asyncio.sleep(0),
    )

    assert len(events) == 1
    usage = events[0].usage
    assert usage is not None
    assert usage.ttft_ms == 5
    assert usage.generation_ms == 7
    assert usage.timed_requests == 1
    assert usage.measured_output_tokens == 2
    assert response.usage == usage


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_observer_records_cancelled_provider_attempt(stream: bool) -> None:
    provider = _BlockingProvider(provider_name="blocking-provider")
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            call(messages=[{"role": "user", "content": "hello"}]),
            timeout=0.01,
        )

    assert len(events) == 1
    assert events[0].finish_reason == "cancelled"
    assert events[0].error_kind == "cancelled"
    assert events[0].usage is None


@pytest.mark.asyncio
async def test_fallback_provider_propagates_observer_to_every_leaf() -> None:
    primary = _NoRetryProvider(
        iter(
            [
                LLMResponse(
                    content="primary unavailable",
                    finish_reason="error",
                    error_kind="timeout",
                )
            ]
        )
    )
    fallback = _SequenceProvider(
        iter(
            [
                LLMResponse(
                    content="fallback ok",
                    usage=LLMUsage.reported(input_tokens=12, output_tokens=3),
                )
            ]
        )
    )
    preset = SimpleNamespace(
        model="fallback-model",
        max_tokens=256,
        temperature=0.2,
        reasoning_effort=None,
        context_window_tokens=4_096,
    )
    provider = FallbackProvider(primary, [preset], lambda _preset: fallback)
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        model="primary-model",
    )

    assert response.content == "fallback ok"
    assert [(event.model, event.finish_reason) for event in events] == [
        ("primary-model", "error"),
        ("fallback-model", "stop"),
    ]
