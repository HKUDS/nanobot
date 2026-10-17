"""Prompt preparation must leave the public runtime responsive."""

import asyncio
import threading
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.hook import AgentHook
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.context import current_request_context
from nanobot.providers.base import LLMProvider, LLMResponse, LLMUsage
from nanobot.runtime_context import public_history_message
from nanobot.security.workspace_access import current_workspace_scope
from nanobot.session.manager import Session


class ControlledProvider(LLMProvider):
    def __init__(self, *, report_usage=True):
        super().__init__(provider_name="prompt-test")
        self.requests = []
        self.report_usage = report_usage

    def get_default_model(self):
        return "test-model"

    def estimate_prompt_tokens(self, messages, tools, model):
        return 10, "controlled-counter"

    async def chat(self, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        return LLMResponse(
            content="Done",
            usage=LLMUsage.reported(input_tokens=10, output_tokens=1) if self.report_usage else None,
        )

    async def chat_stream_with_retry(self, **kwargs):
        return await self.chat(**kwargs)


@pytest.mark.parametrize("phase", ["prompt", "history", "request", "usage"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_preparation_allows_status_heartbeat_and_cancellation(
    tmp_path, monkeypatch, loop_factory, phase, cancel,
):
    provider = ControlledProvider(report_usage=phase != "usage")
    loop = loop_factory(provider=provider)
    runtime_loop = asyncio.get_running_loop()
    key = f"cli:prepare-{phase}"
    live = loop.sessions.get_or_create(key)
    live.messages = [
        {"role": "user", "content": [{"type": "text", "text": "Earlier question"}]},
        {"role": "assistant", "content": "Earlier answer"},
        *[
            {"role": role, "content": "long history " * 256}
            for _ in range(128)
            for role in ("user", "assistant")
        ],
    ]
    loop.sessions.save(live)
    entered = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()
    captured = []
    finalized = []
    heartbeat_requested = asyncio.Event()
    heartbeat_progress = asyncio.Event()

    class Lifecycle(AgentHook):
        async def on_finally(self, context):
            finalized.append((
                context.stop_reason, current_request_context(),
                asyncio.get_running_loop(), context.messages,
            ))
            if context.messages:
                context.messages[0]["content"] = "hook-only"

    async def heartbeat():
        while True:
            await heartbeat_requested.wait()
            heartbeat_requested.clear()
            heartbeat_progress.set()

    def blocked(operation, *args, **kwargs):
        captured.append((current_request_context(), current_workspace_scope(), threading.get_ident()))
        runtime_loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(10), "test did not release prompt preparation"
            return operation(*args, **kwargs)
        finally:
            runtime_loop.call_soon_threadsafe(finished.set)

    if phase == "prompt":
        original = loop.context.build_system_prompt

        def build(**kwargs):
            request = current_request_context()
            if request is not None and request.session_key == key:
                return blocked(original, **kwargs)
            return original(**kwargs)

        monkeypatch.setattr(loop.context, "build_system_prompt", build)
    elif phase == "history":
        original = Session.get_history

        def history(session, *args, **kwargs):
            if session.key == key:
                assert session is not live
                return blocked(original, session, *args, **kwargs)
            return original(session, *args, **kwargs)

        monkeypatch.setattr(Session, "get_history", history)
    else:
        module = "context_governance" if phase == "request" else "runner"
        from nanobot.utils.helpers import estimate_prompt_tokens_chain

        def count(*args, **kwargs):
            request = current_request_context()
            if request is not None and request.session_key == key:
                return blocked(estimate_prompt_tokens_chain, *args, **kwargs)
            return estimate_prompt_tokens_chain(*args, **kwargs)

        monkeypatch.setattr(f"nanobot.agent.{module}.estimate_prompt_tokens_chain", count)

    task = asyncio.create_task(loop.process_direct("Hello", session_key=key, hooks=[Lifecycle()]))
    pulse = asyncio.create_task(heartbeat())
    tasks = [task, pulse]
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        status = await asyncio.wait_for(loop.process_direct("/status", session_key="cli:status"), 5)
        assert status is not None and "test-model" in status.content
        heartbeat_requested.set()
        await asyncio.wait_for(heartbeat_progress.wait(), 5)
        assert not release.is_set()
        assert not finished.is_set()
        assert captured[0][2] != threading.get_ident()
        if phase != "history":
            request, scope, _ = captured[0]
            assert request.session_key == key
            assert scope.project_path == tmp_path.resolve()
        assert current_request_context() is None
        assert current_workspace_scope() is None
        expected_requests = 1 if phase == "usage" else 0
        assert len(provider.requests) == expected_requests
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert not finished.is_set()
            if phase != "history":
                assert len(finalized) == 1
                reason, request, final_loop, snapshot = finalized[0]
                assert reason == "cancelled"
                assert request.session_key == key
                assert final_loop is runtime_loop
                if phase != "prompt":
                    assert snapshot
            # Observe the new session entering the real semaphore, not a settling delay.
            slots = loop.runner.context_governor._preparation_slots
            acquire_slot = slots.acquire
            queued = asyncio.Event()
            acquired = asyncio.Event()

            async def acquire():
                # History preparation queues before RequestContext is bound.
                is_waiting = asyncio.current_task() is waiting
                if is_waiting:
                    queued.set()
                result = await acquire_slot()
                if is_waiting:
                    acquired.set()
                return result

            monkeypatch.setattr(slots, "acquire", acquire)
            waiting = asyncio.create_task(loop.process_direct("Queued", session_key="cli:waiting"))
            tasks.append(waiting)
            await asyncio.wait_for(queued.wait(), 5)
            assert not acquired.is_set()
            assert len(provider.requests) == expected_requests
            assert not waiting.done()
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(waiting, 5)
        elif phase == "history":
            # The live nested payload may change after capture; the worker owns its copy.
            live.messages[0]["content"][0]["text"] = "Changed after capture"
        release.set()
        await asyncio.wait_for(finished.wait(), 5)
        if cancel:
            result = await asyncio.wait_for(loop.process_direct("After", session_key="cli:after"), 5)
            assert result is not None and result.content == "Done"
            assert len(provider.requests) == expected_requests + 1
            assert provider.requests[-1][-1]["content"].startswith("After")
        else:
            result = await asyncio.wait_for(task, 5)
            assert result is not None and result.content == "Done"
            assert len(provider.requests) == 1
            assert provider.requests[0][1]["content"][0]["text"] == "Earlier question"
            saved = loop.sessions.get_or_create(key)
            assert [public_history_message(message)["content"] for message in saved.messages[-2:]] == ["Hello", "Done"]
        assert current_request_context() is None
        assert current_workspace_scope() is None
    finally:
        release.set()
        for pending in tasks:
            if not pending.done():
                pending.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if captured:
            await asyncio.wait_for(finished.wait(), 5)
        await loop.aclose()


@pytest.mark.parametrize("phase", ["success_snapshot", "finally_snapshot"])
async def test_cancellation_during_run_cleanup_delivers_finally_once(
    tmp_path, monkeypatch, loop_factory, phase,
):
    provider = ControlledProvider()
    loop = loop_factory(provider=provider)
    prompt_file = tmp_path / "AGENTS.md"
    prompt_file.write_text("Lifecycle test instructions", encoding="utf-8")
    session = loop.sessions.get_or_create("cli:first")
    session.messages = [
        {"role": "user", "content": [{"type": "text", "text": "Earlier question"}]},
        {"role": "assistant", "content": "Earlier answer"},
    ]
    loop.sessions.save(session)
    runtime_loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    snapshot_entered = asyncio.Event()
    worker_finished = asyncio.Event()
    release = threading.Event()
    events = []
    finals = []
    raw_messages = []
    blockers = []

    class Lifecycle(AgentHook):
        async def start_other_session(self):
            blockers.append(asyncio.create_task(
                loop.process_direct("Blocked", session_key="cli:blocker"),
            ))
            await asyncio.wait_for(entered.wait(), 5)

        async def before_run(self, context):
            events.append("before_run")

        async def after_iteration(self, context):
            raw_messages.append(context.messages)
            events.append("after_iteration")
            if phase == "success_snapshot":
                await self.start_other_session()

        async def after_run(self, context):
            events.append("after_run")
            if phase == "finally_snapshot":
                await self.start_other_session()

        async def on_error(self, context):
            events.append("on_error")

        async def on_finally(self, context):
            events.append("on_finally")
            finals.append(context)
            assert context.messages is not raw_messages[0]
            context.messages[1]["content"][0]["text"] = "hook-only"

    original_read = type(prompt_file).read_text

    def read_text(path, *args, **kwargs):
        request = current_request_context()
        if path == prompt_file and request is not None and request.session_key == "cli:blocker":
            runtime_loop.call_soon_threadsafe(entered.set)
            try:
                assert release.wait(5), "test did not release the other session's prompt read"
                return original_read(path, *args, **kwargs)
            finally:
                runtime_loop.call_soon_threadsafe(worker_finished.set)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(type(prompt_file), "read_text", read_text)
    original_snapshot = loop.runner._run_context_snapshot
    snapshot_paused = False

    async def snapshot(hook, messages):
        nonlocal snapshot_paused
        boundary = "after_iteration" if phase == "success_snapshot" else "after_run"
        if events and events[-1] == boundary and not snapshot_paused:
            snapshot_paused = True
            snapshot_entered.set()
            await asyncio.Event().wait()
        return await original_snapshot(hook, messages)

    monkeypatch.setattr(loop.runner, "_run_context_snapshot", snapshot)
    first = asyncio.create_task(loop.process_direct("First", session_key="cli:first", hooks=[Lifecycle()]))
    try:
        await asyncio.wait_for(snapshot_entered.wait(), 5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, 0.5)
        assert not worker_finished.is_set()
        assert len(provider.requests) == 1
        assert provider.requests[0][-1]["content"].startswith("First")
        assert len(finals) == 1
        assert finals[0].stop_reason == "cancelled"
        assert isinstance(finals[0].exception, asyncio.CancelledError)
        assert finals[0].error is None
        assert len(finals[0].messages) == 5
        assert raw_messages[0][1]["content"][0]["text"] == "Earlier question"
        assert events == [
            "before_run", "after_iteration",
            *(["after_run"] if phase == "finally_snapshot" else []),
            "on_finally",
        ]
        assert current_request_context() is None
        assert current_workspace_scope() is None
    finally:
        for task in [first, *blockers]:
            if not task.done():
                task.cancel()
        release.set()
        await asyncio.gather(first, *blockers, return_exceptions=True)
        if entered.is_set():
            await asyncio.wait_for(worker_finished.wait(), 5)
        await loop.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_prompt_preparation_preserves_context_and_allows_cancellation(
    tmp_path, monkeypatch, loop_factory, cancel,
) -> None:
    loop = loop_factory()
    loop.provider.provider_name = "prompt-test"
    loop.provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="Done"))
    runtime_loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    completed = asyncio.Event()
    release = threading.Event()
    original = loop.context.build_system_prompt
    captured = []
    finalized = []

    class Lifecycle(AgentHook):
        async def on_finally(self, context):
            finalized.append((context.stop_reason, current_request_context(), asyncio.get_running_loop()))

    loop._extra_hooks.append(Lifecycle())

    def build(**kwargs):
        captured.append(current_request_context())
        runtime_loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(5), "test did not release prompt filesystem work"
            return original(**kwargs)
        finally:
            runtime_loop.call_soon_threadsafe(completed.set)

    monkeypatch.setattr(loop.context, "build_system_prompt", build)
    task = asyncio.create_task(loop.process_direct("Hello", session_key="cli:prompt-work"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert captured[0] is not None
        assert captured[0].session_key == "cli:prompt-work"
        assert captured[0].workspace_scope.project_path == tmp_path.resolve()
        assert current_request_context() is None
        loop.provider.chat_stream_with_retry.assert_not_awaited()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            loop.provider.chat_stream_with_retry.assert_not_awaited()
            assert len(finalized) == 1
            reason, request, final_loop = finalized[0]
            assert reason == "cancelled"
            assert request is not None and request.session_key == "cli:prompt-work"
            assert final_loop is runtime_loop
        release.set()
        await asyncio.wait_for(completed.wait(), timeout=5)
        if not cancel:
            result = await asyncio.wait_for(task, timeout=5)
            assert result is not None and result.content == "Done"
            saved = loop.sessions.read_session_snapshot("cli:prompt-work")
            assert [public_history_message(message)["content"] for message in saved.messages] == ["Hello", "Done"]
        assert current_request_context() is None
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if captured:
            await asyncio.wait_for(completed.wait(), timeout=5)
        await loop.aclose()


@pytest.mark.asyncio
async def test_cancelled_prompt_keeps_its_worker_slot_until_read_finishes() -> None:
    runner = AgentRunner()
    runtime_loop = asyncio.get_running_loop()
    entered = {name: asyncio.Event() for name in ("first", "second")}
    released = {name: threading.Event() for name in entered}

    def read(name):
        runtime_loop.call_soon_threadsafe(entered[name].set)
        assert released[name].wait(5), "test did not release prompt read"
        return name

    first = asyncio.create_task(runner.prepare_prompt(read, "first"))
    tasks = [first]
    try:
        await asyncio.wait_for(entered["first"].wait(), timeout=5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, timeout=5)
        second = asyncio.create_task(runner.prepare_prompt(read, "second"))
        tasks.append(second)
        await asyncio.sleep(0)
        # The cancelled caller's read keeps its slot until the worker exits.
        assert not entered["second"].is_set()
        released["first"].set()
        await asyncio.wait_for(entered["second"].wait(), timeout=5)
        released["second"].set()
        assert await asyncio.wait_for(second, timeout=5) == "second"
    finally:
        for release in released.values():
            release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*tuple(runner.context_governor._preparation_jobs), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["request", "usage"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_local_token_estimation_leaves_loop_available(
    tmp_path, monkeypatch, loop_factory, phase, cancel,
) -> None:
    loop = loop_factory()
    loop.provider.provider_name = "token-test"
    loop.provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="Done"))
    runtime_loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    completed = asyncio.Event()
    release = threading.Event()
    captured = []
    finalized = []

    class Lifecycle(AgentHook):
        async def on_finally(self, context):
            finalized.append((context.stop_reason, current_request_context(), asyncio.get_running_loop()))

    loop._extra_hooks.append(Lifecycle())

    def count(*_args, **_kwargs):
        captured.append(current_request_context())
        runtime_loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(5), "test did not release local token estimation"
            return 10, "test-counter"
        finally:
            runtime_loop.call_soon_threadsafe(completed.set)

    module = "context_governance" if phase == "request" else "runner"
    monkeypatch.setattr(f"nanobot.agent.{module}.estimate_prompt_tokens_chain", count)
    task = asyncio.create_task(loop.process_direct("Hello", session_key="cli:token-work"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert captured[0] is not None
        assert captured[0].session_key == "cli:token-work"
        assert captured[0].workspace_scope.project_path == tmp_path.resolve()
        assert current_request_context() is None
        if phase == "request":
            loop.provider.chat_stream_with_retry.assert_not_awaited()
        else:
            loop.provider.chat_stream_with_retry.assert_awaited_once()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), timeout=1)
            assert len(finalized) == 1
            reason, request, final_loop = finalized[0]
            assert reason == "cancelled"
            assert request is not None and request.session_key == "cli:token-work"
            assert final_loop is runtime_loop
        else:
            release.set()
            result = await asyncio.wait_for(task, timeout=5)
            assert result is not None and result.content == "Done"
            saved = loop.sessions.read_session_snapshot("cli:token-work")
            assert [public_history_message(message)["content"] for message in saved.messages] == ["Hello", "Done"]
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if captured:
            await asyncio.wait_for(completed.wait(), timeout=5)
        await loop.aclose()
