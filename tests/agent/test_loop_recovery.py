from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.hook import AgentHook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.filesystem import WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import (
    PENDING_FOLLOWUP_ID_KEY,
    PENDING_FOLLOWUPS_KEY,
    RECOVERY_METADATA_KEY,
    RUNTIME_CHECKPOINT_KEY,
    RecoveryCoordinator,
    record_pending_followup,
)
from nanobot.session.turn_continuation import INTERNAL_CONTINUATION_META
from nanobot.webui import session_list_index, transcript


@pytest.mark.asyncio
async def test_recovery_continuation_runs_without_a_sustained_goal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MessageBus()
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.metadata.update({
        "webui": True,
        RECOVERY_METADATA_KEY: {
            "status": "awaiting_user",
            "recovery_id": "recovery-1",
            "attempts": 0,
        },
    })
    sessions.save(session)
    recovery = RecoveryCoordinator(sessions, bus)

    loop = AgentLoop.__new__(AgentLoop)
    loop.sessions = sessions
    loop._unified_session = False
    loop._recovery_admission = recovery
    loop._session_locks = {}
    loop._concurrency_gate = None
    loop._automation_turn_coordinators = []
    loop._discarding_sessions = set()
    loop._preserve_inflight_turns_on_shutdown = False
    loop.turn_delivery_factory = TurnDeliveryFactory(bus)
    process_message = AsyncMock(return_value=OutboundMessage(
        channel="websocket",
        chat_id="chat",
        content="done",
    ))
    monkeypatch.setattr(loop, "_process_message", process_message)

    await recovery.handle_action(
        "continue",
        {"chat_id": "chat", "recovery_id": "recovery-1"},
    )
    continuation = bus.inbound.get_nowait()

    assert continuation.metadata[INTERNAL_CONTINUATION_META] is True
    await loop._dispatch_one(continuation, asyncio.Queue())

    process_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase,followup", [
    ("tools_completed", True),
    ("awaiting_tools", False),
    ("final_response", False),
    ("normal_completion", False),
])
async def test_multi_iteration_recovery_preserves_completed_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, followup: bool,
) -> None:
    """Real tool effects and the next provider request agree across a restart."""
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir()
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)
    monkeypatch.setattr(transcript, "get_webui_dir", lambda: webui_dir)
    (webui_dir / "websocket_chat.jsonl").write_text("", encoding="utf-8")
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    provider.estimate_prompt_tokens.return_value = (1000, "test")
    waiting = asyncio.Event()
    calls = 0

    async def pause():
        waiting.set()
        await asyncio.Event().wait()

    async def respond(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            if phase == "tools_completed":
                await pause()
            elif phase != "awaiting_tools":
                return LLMResponse(content="Both writes are complete.")
        return LLMResponse(content="", tool_calls=[ToolCallRequest(
            id=f"operation_{calls}", name="write_file",
            arguments={"path": f"receipt_{calls}.txt", "content": f"Completed operation {calls}"},
        )])

    provider.chat_stream_with_retry = respond
    bus = MessageBus()
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path,
                     model="test-model", context_window_tokens=128_000)
    session = loop.sessions.get_or_create("websocket:chat")
    session.add_message("user", "Previous request")
    session.add_message("assistant", "Previous answer")
    loop.sessions.save(session)
    queue = asyncio.Queue()

    class PauseAtCheckpoint(AgentHook):
        async def before_execute_tools(self, context):
            if phase == "awaiting_tools" and context.iteration == 2:
                await pause()

        async def after_iteration(self, context):
            if followup and context.iteration == 0:
                message = InboundMessage(channel="websocket", sender_id="user", chat_id="chat",
                                         content="Also include the receipt names.")
                message.metadata[PENDING_FOLLOWUP_ID_KEY] = record_pending_followup(session, message)
                loop.sessions.save(session)
                await queue.put(message)
            if phase == "final_response" and context.iteration == 2:
                await pause()

    tools = ToolRegistry()
    tools.register(WriteFileTool(workspace=tmp_path, allowed_dir=tmp_path))
    task = asyncio.create_task(loop._process_message(
        InboundMessage(channel="websocket", sender_id="user", chat_id="chat",
                       content="Write two receipts, then report their results."),
        tools=tools, hooks=[PauseAtCheckpoint()], pending_queue=queue,
    ))
    try:
        if phase == "normal_completion":
            await asyncio.wait_for(task, timeout=10)
        else:
            await asyncio.wait_for(waiting.wait(), timeout=10)
            loop.preserve_inflight_turns_on_shutdown()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        for n in (1, 2):
            assert (tmp_path / f"receipt_{n}.txt").read_text() == f"Completed operation {n}"
        assert not (tmp_path / "receipt_3.txt").exists()
        await loop.aclose()

        restarted = SessionManager(tmp_path)
        recovery = RecoveryCoordinator(restarted, MessageBus())
        await recovery.scan()
        restored = restarted.get_or_create(session.key)
        history = restored.get_history()
        ids = [m["tool_call_id"] for m in history if m["role"] == "tool"]
        expected_ids = ["operation_1", "operation_2"]
        if phase == "awaiting_tools":
            expected_ids.append("operation_3")
            assert restored.messages[-1]["_recovery_interrupted"] is True
        assert ids == expected_ids
        assert [m["content"] for m in history[:3]] == [
            "Previous request", "Previous answer", "Write two receipts, then report their results.",
        ]
        assert RUNTIME_CHECKPOINT_KEY not in restored.metadata
        assert PENDING_FOLLOWUPS_KEY not in restored.metadata
        assert recovery.bus.inbound.empty()
        if followup:
            assert sum(m["content"] == "Also include the receipt names." for m in history) == 1
            roles = [m["role"] for m in history[3:]]
            assert roles == ["assistant", "tool", "user", "assistant", "tool"]
        await recovery.scan()
        assert restored.get_history() == history

        if phase in {"normal_completion", "final_response"}:
            assert history[-1]["content"] == "Both writes are complete."
            return
        assert restored.metadata[RECOVERY_METADATA_KEY]["status"] == "awaiting_user"
        captured = []

        async def finish(**kwargs):
            captured.extend(kwargs["messages"])
            return LLMResponse(content="Recovered both receipts.")

        provider.chat_stream_with_retry = finish
        await recovery.handle_action("continue", {
            "chat_id": "chat",
            "recovery_id": restored.metadata[RECOVERY_METADATA_KEY]["recovery_id"],
        })
        resumed = AgentLoop(bus=recovery.bus, provider=provider, workspace=tmp_path,
                            model="test-model", context_window_tokens=128_000,
                            session_manager=restarted)
        try:
            await resumed._process_message(await recovery.bus.consume_inbound(), tools=tools)
        finally:
            await resumed.aclose()
        assert [m["tool_call_id"] for m in captured if m["role"] == "tool"] == expected_ids
        reloaded = SessionManager(tmp_path).get_or_create(session.key)
        assert [m["tool_call_id"] for m in reloaded.messages if m["role"] == "tool"] == expected_ids
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await loop.aclose()
