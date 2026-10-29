"""Runtime actions cross the real WebSocket, bus and session admission boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

import pytest

from nanobot.bus.controls import SelectSessionModel, StopSession
from nanobot.bus.runtime_events import TurnCompleted
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.runtime_context import public_history_message
from nanobot.session.keys import session_key_for_channel
from nanobot.session.manager import SessionManager
from nanobot.session.model_selection import model_preset_from_metadata
from nanobot.webui.http_utils import http_json_response

from .test_webui_session_admission import _Connection, _Runtime
from .test_webui_session_admission import runtime as runtime


@asynccontextmanager
async def _running_loop(runtime: _Runtime) -> AsyncIterator[None]:
    task = asyncio.create_task(runtime.loop.run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _consume_control(runtime: _Runtime) -> None:
    control = await asyncio.wait_for(runtime.bus.consume_inbound(), 3)
    assert isinstance(control, StopSession | SelectSessionModel)
    await runtime.loop._dispatch_control(control)


async def _send_turn(runtime: _Runtime, text: str, turn_id: str) -> None:
    await runtime.channel._dispatch_envelope(runtime.connection, "webui-client", {
        "type": "message", "chat_id": "controlled", "content": text,
        "webui": True, "turn_id": turn_id,
    })


async def test_stop_queued_before_consumption_cannot_cancel_the_next_turn(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = []
    runtime.bus.subscribe(completed.append, TurnCompleted)
    next_started = asyncio.Event()
    release_next = asyncio.Event()
    original = runtime.provider.chat

    async def blocked_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        if "next turn" in str(messages[-1]["content"]):
            next_started.set()
            await release_next.wait()
            return await original(messages, **kwargs)
        await asyncio.Event().wait()
        raise AssertionError("the stopped request must not resume")

    monkeypatch.setattr(runtime.provider, "chat", blocked_chat)
    await _send_turn(runtime, "first turn", "old-turn")
    await runtime.request("stop-before-consume", "session.stop", {
        "chat_id": "controlled", "turn_id": "old-turn",
    })
    assert runtime.bus.inbound_size == 2
    assert runtime.provider.calls == 0

    async with _running_loop(runtime):
        stopped = await runtime.response("stop-before-consume")
        assert stopped["result"]["status"] == "stopped"
        assert stopped["result"]["turn_id"] == "old-turn"
        assert any(event.outcome == "cancelled" and event.context.metadata.get("webui_turn_id") == "old-turn"
                   for event in completed)
        await _send_turn(runtime, "next turn", "next-turn")
        await asyncio.wait_for(next_started.wait(), 3)
        await runtime.request("delayed-old-stop", "session.stop", {
            "chat_id": "controlled", "turn_id": "old-turn",
        })
        assert (await runtime.response("delayed-old-stop"))["result"]["status"] == "stale"
        await runtime.request("missing-target-stop", "session.stop", {
            "chat_id": "controlled", "turn_id": None,
        })
        assert (await runtime.response("missing-target-stop"))["result"]["status"] == "stale"
        await runtime.request("old-gateway-stop", "session.stop", {
            "chat_id": "controlled", "turn_id": "next-turn", "expected_gateway_id": "previous-instance",
        })
        assert (await runtime.response("old-gateway-stop"))["error"]["status"] == 409
        await runtime.request("stop-before-consume", "session.stop", {
            "chat_id": "controlled", "turn_id": "old-turn",
        })
        assert await runtime.response("stop-before-consume") == stopped
        release_next.set()
        tasks = tuple(task for group in runtime.loop._active_tasks.values() for task in group)
        await asyncio.wait_for(asyncio.gather(*tasks), 3)
        key = session_key_for_channel(
            "websocket", "controlled", unified_session=runtime.channel.gateway.unified_session,
        )
        saved = await runtime.sessions.state.read(key)
        assert saved is not None
        assert public_history_message(saved.messages[-1])["content"] == "hello back"
        assert runtime.provider.calls == 1


async def test_stop_keeps_completed_tool_context_for_the_next_real_turn(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = []
    runtime.bus.subscribe(completed.append, TurnCompleted)
    source = runtime.sessions.workspace / "context.txt"
    source.write_text("Partial context survives stop.", encoding="utf-8")
    awaiting_answer = asyncio.Event()
    next_answer = asyncio.Event()
    next_context: list[dict[str, Any]] = []
    calls = 0

    async def chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return LLMResponse(content="I will read the context.", tool_calls=[
                ToolCallRequest(id="read-context", name="read_file", arguments={"path": str(source)}),
            ])
        if calls == 2:
            awaiting_answer.set()
            await asyncio.Event().wait()
        next_context.extend(messages)
        next_answer.set()
        return LLMResponse(content="I retained the context.", finish_reason="stop")

    monkeypatch.setattr(runtime.provider, "chat", chat)
    await _send_turn(runtime, "read context", "partial-turn")
    async with _running_loop(runtime):
        await asyncio.wait_for(awaiting_answer.wait(), 3)
        await runtime.request("stop-partial", "session.stop", {
            "chat_id": "controlled", "turn_id": "partial-turn",
        })
        assert (await runtime.response("stop-partial"))["result"]["status"] == "stopped"
        assert any(event.outcome == "cancelled" and event.context.metadata.get("webui_turn_id") == "partial-turn"
                   for event in completed)
        await _send_turn(runtime, "use that context", "continue-turn")
        await asyncio.wait_for(next_answer.wait(), 3)
        tasks = tuple(task for group in runtime.loop._active_tasks.values() for task in group)
        await asyncio.wait_for(asyncio.gather(*tasks), 3)
        assert any(row["role"] == "tool" and "Partial context survives stop." in row["content"]
                   for row in next_context)
        assert any(row["role"] == "assistant" and row.get("tool_calls") for row in next_context)
        assert calls == 3


async def test_model_selection_reads_and_writes_the_actual_execution_session(runtime: _Runtime) -> None:
    for chat_id in ("model-a", "model-b"):
        await runtime.execute(await runtime.message(chat_id))
    await runtime.request("select-model", "session.model.select", {"chat_id": "model-b", "preset": "fast"})
    await _consume_control(runtime)
    assert (await runtime.response("select-model"))["result"]["model_name"] == "fast-model"

    for chat_id in ("model-a", "model-b"):
        await runtime.channel._dispatch_envelope(runtime.connection, "webui-client", {
            "type": "attach", "chat_id": chat_id,
        })
        await runtime.channel.webui_flush(runtime.connection)
        attached = next(frame for frame in reversed(runtime.connection.sent)
                        if frame["event"] == "attached" and frame["chat_id"] == chat_id)
        expected = "fast" if runtime.channel.gateway.unified_session or chat_id == "model-b" else None
        assert attached["model_preset"] == expected
        followup = await runtime.message(chat_id, "use selected model")
        await runtime.execute(followup)
        selected = await runtime.sessions.state.read_metadata(runtime.loop._effective_session_key(followup))
        assert selected is not None
        assert model_preset_from_metadata(selected["metadata"]) == expected
        assert runtime.provider.models[-1] == ("fast-model" if expected else "test-model")


async def test_temporary_model_selection_is_private_nonpersistent_and_not_replayed(
    runtime: _Runtime, history,
) -> None:
    await runtime.channel._dispatch_envelope(runtime.connection, "webui-client", {"type": "new_temporary_chat"})
    chat_id = next(frame["chat_id"] for frame in runtime.connection.sent if frame["event"] == "attached")
    first = await runtime.message(chat_id)
    await runtime.execute(first)
    await runtime.request("private-selection", "session.model.select", {"chat_id": chat_id, "preset": "fast"})
    await _consume_control(runtime)
    assert (await runtime.response("private-selection"))["result"]["model_preset"] == "fast"
    await runtime.execute(await runtime.message(chat_id, "keep private selection"))
    assert runtime.provider.models[-1] == "fast-model"
    snapshot = await runtime.sessions.state.read(first.session_key)
    assert snapshot is not None and snapshot.policy.persist is False
    assert model_preset_from_metadata(snapshot.metadata) == "fast"
    assert await runtime.sessions.state.list_sessions() == []
    assert SessionManager(runtime.sessions.workspace).get_existing(first.session_key) is None
    assert history.read(first.session_key) == []

    stranger = _Connection()
    runtime.channel._webui_connections.add(stranger)
    try:
        await runtime.request("private-selection", "session.model.select", {
            "chat_id": chat_id, "preset": "fast",
        }, connection=stranger)
        denied = await runtime.response("private-selection", connection=stranger)
        assert denied["ok"] is False
        assert denied["error"]["status"] == 404
        assert "result" not in denied
        assert runtime.bus.inbound_size == 0
    finally:
        await runtime.channel._cleanup_connection(stranger)


@pytest.mark.parametrize("action", ["session.stop", "session.model.select", "gateway.restart"])
async def test_controls_and_their_retries_do_not_wait_for_a_long_mutation(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch, action: str,
) -> None:
    await runtime.execute(await runtime.message("busy-settings"))
    mutation_started = asyncio.Event()
    release_mutation = asyncio.Event()

    async def mutate(_connection: object, _action: str, _payload: dict[str, Any]):
        mutation_started.set()
        await release_mutation.wait()
        return http_json_response({"saved": True})

    monkeypatch.setattr(runtime.channel.gateway.http, "dispatch_webui_mutation", mutate)
    await runtime.request("long-mutation", "settings.agent.update", {})
    await asyncio.wait_for(mutation_started.wait(), 3)
    payload = {} if action == "gateway.restart" else {"chat_id": "busy-settings"}
    if action == "session.stop":
        payload["turn_id"] = None
    elif action == "session.model.select":
        payload["preset"] = "fast"
    try:
        await runtime.request("unblocked-control", action, payload)
        if action != "gateway.restart":
            await _consume_control(runtime)
        receipt = await runtime.response("unblocked-control")
        assert receipt["ok"] is True
        await runtime.request("unblocked-control", action, payload)
        assert await runtime.response("unblocked-control") == receipt
        assert not release_mutation.is_set()
        assert not any(frame.get("request_id") == "long-mutation" for frame in runtime.connection.sent)
        assert runtime.bus.inbound_size == 0
    finally:
        release_mutation.set()
        await runtime.response("long-mutation")


@pytest.mark.parametrize("text", ["/stop/notes.txt", "/model/fast"])
async def test_slash_like_text_still_executes_as_an_ordinary_message(runtime: _Runtime, text: str) -> None:
    message = await runtime.message("ordinary-slash", text)
    await runtime.execute(message)
    saved = await runtime.sessions.state.read(runtime.loop._effective_session_key(message))
    assert saved is not None
    assert [public_history_message(row)["content"] for row in saved.messages if row["role"] == "user"] == [text]
    assert runtime.provider.calls == 1


@pytest.mark.parametrize("parent_finishes", [False, True], ids=["active-parent", "finished-parent"])
async def test_session_stop_waits_for_owned_child_before_reply_or_next_turn(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch, parent_finishes: bool,
) -> None:
    child_started, child_cancelled, release_child, parent_answered, next_started, release_next = (
        asyncio.Event() for _ in range(6)
    )
    parent_calls = 0
    monkeypatch.setattr(runtime.loop.subagents, "CANCEL_WAIT_SECONDS", 0.02)
    monkeypatch.setattr("nanobot.agent.loop._SUBAGENT_TERMINAL_WAIT_SECONDS", 0.02)

    async def chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        nonlocal parent_calls
        if messages[-1].get("content") == "hold the child":
            child_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                child_cancelled.set()
                await release_child.wait()
                raise
        if "next turn" in str(messages[-1].get("content")):
            next_started.set()
            await release_next.wait()
            return LLMResponse(content="next turn completed", finish_reason="stop")
        parent_calls += 1
        if parent_calls == 1:
            return LLMResponse(content="Starting background work.", tool_calls=[ToolCallRequest(
                id="child", name="subagent", arguments={"action": "create", "task": "hold the child"},
            )])
        parent_answered.set()
        if not parent_finishes:
            await asyncio.Event().wait()
        return LLMResponse(content="The child continues in the Gateway.", finish_reason="stop")

    monkeypatch.setattr(runtime.provider, "chat", chat)
    async with _running_loop(runtime):
        receipt = None
        try:
            await _send_turn(runtime, "start child", "parent-turn")
            await asyncio.wait_for(child_started.wait(), 3)
            await asyncio.wait_for(parent_answered.wait(), 3)
            if parent_finishes:
                await asyncio.wait_for(asyncio.gather(*tuple(
                    task for tasks in runtime.loop._active_tasks.values() for task in tasks
                )), 3)
            assert runtime.loop.subagents.get_running_count() == 1
            await runtime.request("stop-with-child", "session.stop", {
                "chat_id": "controlled", "turn_id": "parent-turn",
            })
            receipt = asyncio.create_task(runtime.response("stop-with-child"))
            await asyncio.wait_for(child_cancelled.wait(), 3)
            await _send_turn(runtime, "next turn", "next-turn")
            done, _ = await asyncio.wait({receipt}, timeout=0.08)
            assert not done, "stopped must confirm cleanup, not only a cancellation request"
            assert not next_started.is_set(), "old session work still owns its cleanup barrier"
            release_child.set()
            stopped = await receipt
            assert stopped["result"]["status"] == "stopped"
            assert stopped["result"]["turn_id"] == "parent-turn"
            assert runtime.loop.subagents.get_running_count() == 0
            await asyncio.wait_for(next_started.wait(), 3)
            await runtime.request("late-parent-stop", "session.stop", {
                "chat_id": "controlled", "turn_id": "parent-turn",
            })
            assert (await runtime.response("late-parent-stop"))["result"]["status"] == "stale"
            release_next.set()
            await asyncio.wait_for(asyncio.gather(*tuple(
                task for tasks in runtime.loop._active_tasks.values() for task in tasks
            )), 3)
            key = session_key_for_channel(
                "websocket", "controlled", unified_session=runtime.channel.gateway.unified_session,
            )
            saved = await runtime.sessions.state.read(key)
            assert saved is not None
            assert public_history_message(saved.messages[-1])["content"] == "next turn completed"
        finally:
            release_child.set()
            release_next.set()
            if receipt is not None:
                await receipt


async def test_stop_owns_followup_while_its_durable_admission_is_saving(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanobot.session.recovery import pending_followups

    running, saving, release_save, next_answered = (asyncio.Event() for _ in range(4))
    queue_followup = runtime.sessions.state.queue_followup
    next_context: list[dict[str, Any]] = []
    calls = 0

    async def chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            running.set()
            await asyncio.Event().wait()
        next_context.extend(messages)
        next_answered.set()
        return LLMResponse(content="fresh answer", finish_reason="stop")

    async def save_followup(key: str, msg: Any) -> str | None:
        saving.set()
        await release_save.wait()
        return await queue_followup(key, msg)

    monkeypatch.setattr(runtime.provider, "chat", chat)
    monkeypatch.setattr(runtime.sessions.state, "queue_followup", save_followup)
    async with _running_loop(runtime):
        try:
            await _send_turn(runtime, "first turn", "first-turn")
            await asyncio.wait_for(running.wait(), 3)
            await _send_turn(runtime, "discard this followup", "followup-turn")
            await asyncio.wait_for(saving.wait(), 3)
            await runtime.request("stop-during-save", "session.stop", {
                "chat_id": "controlled", "turn_id": "first-turn",
            })
            await _send_turn(runtime, "next turn", "next-turn")
            release_save.set()
            assert (await runtime.response("stop-during-save"))["result"]["status"] == "stopped"
            await asyncio.wait_for(next_answered.wait(), 3)
            await asyncio.wait_for(asyncio.gather(*tuple(
                task for tasks in runtime.loop._active_tasks.values() for task in tasks
            )), 3)
            key = session_key_for_channel(
                "websocket", "controlled", unified_session=runtime.channel.gateway.unified_session,
            )
            saved = await runtime.sessions.state.read(key)
            assert saved is not None and pending_followups(saved) == []
            assert not any("discard this followup" in str(row.get("content")) for row in next_context)
            assert public_history_message(saved.messages[-1])["content"] == "fresh answer"
        finally:
            release_save.set()


async def test_failed_cleanup_is_not_reported_stopped_and_blocks_new_execution_until_retry(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = asyncio.Event()
    calls = 0

    async def chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            running.set()
            await asyncio.Event().wait()
        return LLMResponse(content="clean next turn", finish_reason="stop")

    terminate = runtime.loop._exec_session_manager.terminate_by_owner

    async def failed_cleanup(key: str) -> int:
        raise RuntimeError("Process cleanup unavailable")

    monkeypatch.setattr(runtime.provider, "chat", chat)
    monkeypatch.setattr(runtime.loop._exec_session_manager, "terminate_by_owner", failed_cleanup)
    completed = asyncio.Queue()
    runtime.bus.subscribe(completed.put_nowait, TurnCompleted)
    async with _running_loop(runtime):
        await _send_turn(runtime, "first turn", "failed-turn")
        await asyncio.wait_for(running.wait(), 3)
        await runtime.request("failed-stop", "session.stop", {
            "chat_id": "controlled", "turn_id": "failed-turn",
        })
        assert (await runtime.response("failed-stop"))["error"]["status"] == 500
        assert (await asyncio.wait_for(completed.get(), 3)).outcome == "cancelled"
        await _send_turn(runtime, "must not execute", "rejected-turn")
        assert (await asyncio.wait_for(completed.get(), 3)).outcome == "failed"
        assert calls == 1
        monkeypatch.setattr(runtime.loop._exec_session_manager, "terminate_by_owner", terminate)
        await runtime.request("retry-cleanup", "session.stop", {
            "chat_id": "controlled", "turn_id": "failed-turn",
        })
        assert (await runtime.response("retry-cleanup"))["result"]["status"] == "idle"
        await _send_turn(runtime, "next turn", "next-turn")
        assert (await asyncio.wait_for(completed.get(), 3)).outcome == "completed"
        assert calls == 2


async def test_stop_cancels_an_accepted_user_shell_still_preparing_to_launch(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shlex
    import sys

    running, shell_preparing, shell_cancelled, release_shell = (asyncio.Event() for _ in range(4))
    marker = runtime.sessions.workspace / "shell-must-not-launch.txt"
    execute_shell = runtime.loop.execute_user_shell_command

    async def chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        running.set()
        await asyncio.Event().wait()
        raise AssertionError("cancelled model must not resume")

    async def preparing_shell(ctx: Any):
        shell_preparing.set()
        try:
            await release_shell.wait()
        except asyncio.CancelledError:
            shell_cancelled.set()
            raise
        return await execute_shell(ctx)

    monkeypatch.setattr(runtime.provider, "chat", chat)
    monkeypatch.setattr(runtime.loop, "execute_user_shell_command", preparing_shell)
    async with _running_loop(runtime):
        try:
            await _send_turn(runtime, "first turn", "parent-turn")
            await asyncio.wait_for(running.wait(), 3)
            command = shlex.join([sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('leaked')"])
            await runtime.channel._dispatch_envelope(runtime.connection, "webui-client", {
                "type": "message", "chat_id": "controlled", "content": f"!{command}",
                "webui": True, "user_shell": True, "turn_id": "shell-turn",
            })
            await asyncio.wait_for(shell_preparing.wait(), 3)
            await runtime.request("stop-preparing-shell", "session.stop", {
                "chat_id": "controlled", "turn_id": "parent-turn",
            })
            assert (await runtime.response("stop-preparing-shell"))["result"]["status"] == "stopped"
            assert shell_cancelled.is_set(), "accepted shell work must not outlive the Stop receipt"
            release_shell.set()
            assert not marker.exists()
        finally:
            release_shell.set()
