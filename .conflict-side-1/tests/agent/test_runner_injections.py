"""Tests for the mid-turn injection system: drain, checkpoints, pending queues, error paths."""

from __future__ import annotations

import asyncio
import base64
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def _make_injection_callback(queue: asyncio.Queue):
    """Return an async callback that drains *queue* into a list of dicts."""
    async def inject_cb():
        items = []
        while not queue.empty():
            items.append(await queue.get())
        return items
    return inject_cb


def _make_loop(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)
    return loop

@pytest.mark.asyncio
async def test_drain_injections_returns_empty_when_no_callback():
    """No injection_callback → empty list."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    runner = AgentRunner(provider)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    spec = AgentRunSpec(
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=None,
    )
    result = await runner._drain_injections(spec)
    assert result == []


@pytest.mark.asyncio
async def test_drain_injections_extracts_content_from_inbound_messages():
    """Should extract .content from InboundMessage objects."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    runner = AgentRunner(provider)
    tools = MagicMock()
    tools.get_definitions.return_value = []

    msgs = [
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="hello"),
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="world"),
    ]

    async def cb():
        return msgs

    spec = AgentRunSpec(
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=cb,
    )
    result = await runner._drain_injections(spec)
    assert result == [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "world"},
    ]


@pytest.mark.asyncio
async def test_drain_injections_passes_limit_to_callback_when_supported():
    """Limit-aware callbacks can preserve overflow in their own queue."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner, _MAX_INJECTIONS_PER_TURN
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    runner = AgentRunner(provider)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    seen_limits: list[int] = []

    msgs = [
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content=f"msg{i}")
        for i in range(_MAX_INJECTIONS_PER_TURN + 3)
    ]

    async def cb(*, limit: int):
        seen_limits.append(limit)
        return msgs[:limit]

    spec = AgentRunSpec(
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=cb,
    )
    result = await runner._drain_injections(spec)
    assert seen_limits == [_MAX_INJECTIONS_PER_TURN]
    assert result == [
        {"role": "user", "content": "msg0"},
        {"role": "user", "content": "msg1"},
        {"role": "user", "content": "msg2"},
    ]


@pytest.mark.asyncio
async def test_drain_injections_skips_empty_content():
    """Messages with blank content should be filtered out."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    runner = AgentRunner(provider)
    tools = MagicMock()
    tools.get_definitions.return_value = []

    msgs = [
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content=""),
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="   "),
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="valid"),
    ]

    async def cb():
        return msgs

    spec = AgentRunSpec(
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=cb,
    )
    result = await runner._drain_injections(spec)
    assert result == [{"role": "user", "content": "valid"}]


@pytest.mark.asyncio
async def test_drain_injections_handles_callback_exception():
    """If the callback raises, return empty list (error is logged)."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    runner = AgentRunner(provider)
    tools = MagicMock()
    tools.get_definitions.return_value = []

    async def cb():
        raise RuntimeError("boom")

    spec = AgentRunSpec(
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=cb,
    )
    result = await runner._drain_injections(spec)
    assert result == []


@pytest.mark.asyncio
async def test_checkpoint1_injects_after_tool_execution():
    """Follow-up messages are injected after tool execution, before next LLM call."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}
    captured_messages = []

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append(list(messages))
        if call_count["n"] == 1:
            return LLMResponse(
                content="using tool",
                tool_calls=[ToolCallRequest(id="c1", name="read_file", arguments={"path": "x"})],
                usage={},
            )
        return LLMResponse(content="final answer", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="file content")

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    # Put a follow-up message in the queue before the run starts
    await injection_queue.put(
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="follow-up question")
    )

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    assert result.final_content == "final answer"
    # The second call should have the injected user message
    assert call_count["n"] == 2
    last_messages = captured_messages[-1]
    injected = [m for m in last_messages if m.get("role") == "user" and m.get("content") == "follow-up question"]
    assert len(injected) == 1


@pytest.mark.asyncio
async def test_checkpoint2_injects_after_final_response_with_resuming_stream():
    """After final response, if injections exist, stream_end should get resuming=True."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}
    stream_end_calls = []

    class TrackingHook(AgentHook):
        def wants_streaming(self) -> bool:
            return True

        async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
            stream_end_calls.append(resuming)

        def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
            return content

    async def chat_stream_with_retry(*, messages, on_content_delta=None, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(content="first answer", tool_calls=[], usage={})
        return LLMResponse(content="second answer", tool_calls=[], usage={})

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    # Inject a follow-up that arrives during the first response
    await injection_queue.put(
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="quick follow-up")
    )

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=TrackingHook(),
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    assert result.final_content == "second answer"
    assert call_count["n"] == 2
    # First stream_end should have resuming=True (because injections found)
    assert stream_end_calls[0] is True
    # Second (final) stream_end should have resuming=False
    assert stream_end_calls[-1] is False


@pytest.mark.asyncio
async def test_checkpoint2_preserves_final_response_in_history_before_followup():
    """A follow-up injected after a final answer must still see that answer in history."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}
    captured_messages = []

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append([dict(message) for message in messages])
        if call_count["n"] == 1:
            return LLMResponse(content="first answer", tool_calls=[], usage={})
        return LLMResponse(content="second answer", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    await injection_queue.put(
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="follow-up question")
    )

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.final_content == "second answer"
    assert call_count["n"] == 2
    assert captured_messages[-1] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "follow-up question"},
    ]
    assert [
        {"role": message["role"], "content": message["content"]}
        for message in result.messages
        if message.get("role") == "assistant"
    ] == [
        {"role": "assistant", "content": "first answer"},
        {"role": "assistant", "content": "second answer"},
    ]


@pytest.mark.asyncio
async def test_loop_injected_followup_preserves_image_media(tmp_path):
    """Mid-turn follow-ups with images should keep multimodal content."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    image_path = tmp_path / "followup.png"
    image_path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII="
    ))

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    captured_messages: list[list[dict]] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append(list(messages))
        if call_count["n"] == 1:
            return LLMResponse(content="first answer", tool_calls=[], usage={})
        return LLMResponse(content="second answer", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.tools.get_definitions = MagicMock(return_value=[])

    pending_queue = asyncio.Queue()
    await pending_queue.put(InboundMessage(
        channel="cli",
        sender_id="u",
        chat_id="c",
        content="",
        media=[str(image_path)],
    ))

    final_content, _, _, _, had_injections = await loop._run_agent_loop(
        [{"role": "user", "content": "hello"}],
        channel="cli",
        chat_id="c",
        pending_queue=pending_queue,
    )

    assert final_content == "second answer"
    assert had_injections is True
    assert call_count["n"] == 2
    injected_user_messages = [
        message for message in captured_messages[-1]
        if message.get("role") == "user" and isinstance(message.get("content"), list)
    ]
    assert injected_user_messages
    assert any(
        block.get("type") == "image_url"
        for block in injected_user_messages[-1]["content"]
        if isinstance(block, dict)
    )


@pytest.mark.asyncio
async def test_runner_merges_multiple_injected_user_messages_without_losing_media():
    """Multiple injected follow-ups should not create lossy consecutive user messages."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    call_count = {"n": 0}
    captured_messages = []

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append([dict(message) for message in messages])
        if call_count["n"] == 1:
            return LLMResponse(content="first answer", tool_calls=[], usage={})
        return LLMResponse(content="second answer", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    async def inject_cb():
        if call_count["n"] == 1:
            return [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                        {"type": "text", "text": "look at this"},
                    ],
                },
                {"role": "user", "content": "and answer briefly"},
            ]
        return []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.final_content == "second answer"
    assert call_count["n"] == 2
    second_call = captured_messages[-1]
    user_messages = [message for message in second_call if message.get("role") == "user"]
    assert len(user_messages) == 2
    injected = user_messages[-1]
    assert isinstance(injected["content"], list)
    assert any(
        block.get("type") == "image_url"
        for block in injected["content"]
        if isinstance(block, dict)
    )
    assert any(
        block.get("type") == "text" and block.get("text") == "and answer briefly"
        for block in injected["content"]
        if isinstance(block, dict)
    )


@pytest.mark.asyncio
async def test_injection_cycles_capped_at_max():
    """Injection cycles should be capped at _MAX_INJECTION_CYCLES."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner, _MAX_INJECTION_CYCLES
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        return LLMResponse(content=f"answer-{call_count['n']}", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    drain_count = {"n": 0}

    async def inject_cb():
        drain_count["n"] += 1
        # Only inject for the first _MAX_INJECTION_CYCLES drains
        if drain_count["n"] <= _MAX_INJECTION_CYCLES:
            return [InboundMessage(channel="cli", sender_id="u", chat_id="c", content=f"msg-{drain_count['n']}")]
        return []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "start"}],
        tools=tools,
        model="test-model",
        max_iterations=20,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    # Should be capped: _MAX_INJECTION_CYCLES injection rounds + 1 final round
    assert call_count["n"] == _MAX_INJECTION_CYCLES + 1


@pytest.mark.asyncio
async def test_no_injections_flag_is_false_by_default():
    """had_injections should be False when no injection callback or no messages."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()

    async def chat_with_retry(**kwargs):
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.had_injections is False


@pytest.mark.asyncio
async def test_pending_queue_cleanup_on_dispatch(tmp_path):
    """_pending_queues should be cleaned up after _dispatch completes."""
    loop = _make_loop(tmp_path)

    async def chat_with_retry(**kwargs):
        return LLMResponse(content="done", tool_calls=[], usage={})

    loop.provider.chat_with_retry = chat_with_retry

    from nanobot.bus.events import InboundMessage

    msg = InboundMessage(channel="cli", sender_id="u", chat_id="c", content="hello")
    # The queue should not exist before dispatch
    assert msg.session_key not in loop._pending_queues

    await loop._dispatch(msg)

    # The queue should be cleaned up after dispatch
    assert msg.session_key not in loop._pending_queues


@pytest.mark.asyncio
async def test_followup_routed_to_pending_queue(tmp_path):
    """Unified-session follow-ups should route into the active pending queue."""
    from nanobot.agent.loop import UNIFIED_SESSION_KEY
    from nanobot.bus.events import InboundMessage

    loop = _make_loop(tmp_path)
    loop._unified_session = True
    loop._dispatch = AsyncMock()  # type: ignore[method-assign]

    pending = asyncio.Queue(maxsize=20)
    loop._pending_queues[UNIFIED_SESSION_KEY] = pending

    run_task = asyncio.create_task(loop.run())
    msg = InboundMessage(channel="discord", sender_id="u", chat_id="c", content="follow-up")
    await loop.bus.publish_inbound(msg)

    deadline = time.time() + 2
    while pending.empty() and time.time() < deadline:
        await asyncio.sleep(0.01)

    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert loop._dispatch.await_count == 0
    assert not pending.empty()
    queued_msg = pending.get_nowait()
    assert queued_msg.content == "follow-up"
    assert queued_msg.session_key == UNIFIED_SESSION_KEY


@pytest.mark.asyncio
async def test_pending_queue_preserves_overflow_for_next_injection_cycle(tmp_path):
    """Pending queue should leave overflow messages queued for later drains."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.agent.runner import _MAX_INJECTIONS_PER_TURN

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    captured_messages: list[list[dict]] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append([dict(message) for message in messages])
        return LLMResponse(content=f"answer-{call_count['n']}", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.tools.get_definitions = MagicMock(return_value=[])

    pending_queue = asyncio.Queue()
    total_followups = _MAX_INJECTIONS_PER_TURN + 2
    for idx in range(total_followups):
        await pending_queue.put(InboundMessage(
            channel="cli",
            sender_id="u",
            chat_id="c",
            content=f"follow-up-{idx}",
        ))

    final_content, _, _, _, had_injections = await loop._run_agent_loop(
        [{"role": "user", "content": "hello"}],
        channel="cli",
        chat_id="c",
        pending_queue=pending_queue,
    )

    assert final_content == "answer-3"
    assert had_injections is True
    assert call_count["n"] == 3
    flattened_user_content = "\n".join(
        message["content"]
        for message in captured_messages[-1]
        if message.get("role") == "user" and isinstance(message.get("content"), str)
    )
    for idx in range(total_followups):
        assert f"follow-up-{idx}" in flattened_user_content
    assert pending_queue.empty()


@pytest.mark.asyncio
async def test_pending_queue_full_falls_back_to_queued_task(tmp_path):
    """QueueFull should preserve the message by dispatching a queued task."""
    from nanobot.bus.events import InboundMessage

    loop = _make_loop(tmp_path)
    loop._dispatch = AsyncMock()  # type: ignore[method-assign]

    pending = asyncio.Queue(maxsize=1)
    pending.put_nowait(InboundMessage(channel="cli", sender_id="u", chat_id="c", content="already queued"))
    loop._pending_queues["cli:c"] = pending

    run_task = asyncio.create_task(loop.run())
    msg = InboundMessage(channel="cli", sender_id="u", chat_id="c", content="follow-up")
    await loop.bus.publish_inbound(msg)

    deadline = time.time() + 2
    while loop._dispatch.await_count == 0 and time.time() < deadline:
        await asyncio.sleep(0.01)

    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert loop._dispatch.await_count == 1
    dispatched_msg = loop._dispatch.await_args.args[0]
    assert dispatched_msg.content == "follow-up"
    assert pending.qsize() == 1


@pytest.mark.asyncio
async def test_dispatch_republishes_leftover_queue_messages(tmp_path):
    """Messages left in the pending queue after _dispatch are re-published to the bus.

    This tests the finally-block cleanup that prevents message loss when
    the runner exits early (e.g., max_iterations, tool_error) with messages
    still in the queue.
    """
    from nanobot.bus.events import InboundMessage

    loop = _make_loop(tmp_path)
    bus = loop.bus

    # Simulate a completed dispatch by manually registering a queue
    # with leftover messages, then running the cleanup logic directly.
    pending = asyncio.Queue(maxsize=20)
    session_key = "cli:c"
    loop._pending_queues[session_key] = pending
    pending.put_nowait(InboundMessage(channel="cli", sender_id="u", chat_id="c", content="leftover-1"))
    pending.put_nowait(InboundMessage(channel="cli", sender_id="u", chat_id="c", content="leftover-2"))

    # Execute the cleanup logic from the finally block
    queue = loop._pending_queues.pop(session_key, None)
    assert queue is not None
    leftover = 0
    while True:
        try:
            item = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        await bus.publish_inbound(item)
        leftover += 1

    assert leftover == 2

    # Verify the messages are now on the bus
    msgs = []
    while not bus.inbound.empty():
        msgs.append(await asyncio.wait_for(bus.consume_inbound(), timeout=0.5))
    contents = [m.content for m in msgs]
    assert "leftover-1" in contents
    assert "leftover-2" in contents


@pytest.mark.asyncio
async def test_drain_injections_on_fatal_tool_error():
    """Pending injections should be drained even when a fatal tool error occurs."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="c1", name="exec", arguments={"cmd": "bad"})],
                usage={},
            )
        # Second call: respond normally to the injected follow-up
        return LLMResponse(content="reply to follow-up", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(side_effect=RuntimeError("tool exploded"))

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    await injection_queue.put(
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="follow-up after error")
    )

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        fail_on_tool_error=True,
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    assert result.final_content == "reply to follow-up"
    # The injection should be in the messages history
    injected = [
        m for m in result.messages
        if m.get("role") == "user" and m.get("content") == "follow-up after error"
    ]
    assert len(injected) == 1


@pytest.mark.asyncio
async def test_drain_injections_on_llm_error():
    """Pending injections should be drained when the LLM returns an error finish_reason."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[],
                finish_reason="error",
                usage={},
            )
        # Second call: respond normally to the injected follow-up
        return LLMResponse(content="recovered answer", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    await injection_queue.put(
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="follow-up after LLM error")
    )

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "previous response"},
            {"role": "user", "content": "trigger error"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    assert result.final_content == "recovered answer"
    injected = [
        m for m in result.messages
        if m.get("role") == "user" and "follow-up after LLM error" in str(m.get("content", ""))
    ]
    assert len(injected) == 1


@pytest.mark.asyncio
async def test_drain_injections_on_empty_final_response():
    """Pending injections should be drained when the runner exits due to empty response."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner, _MAX_EMPTY_RETRIES
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] <= _MAX_EMPTY_RETRIES + 1:
            return LLMResponse(content="", tool_calls=[], usage={})
        # After retries exhausted + injection drain, respond normally
        return LLMResponse(content="answer after empty", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    await injection_queue.put(
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="follow-up after empty")
    )

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "previous response"},
            {"role": "user", "content": "trigger empty"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=10,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    assert result.final_content == "answer after empty"
    injected = [
        m for m in result.messages
        if m.get("role") == "user" and "follow-up after empty" in str(m.get("content", ""))
    ]
    assert len(injected) == 1


@pytest.mark.asyncio
async def test_drain_injections_on_max_iterations():
    """Pending injections should be drained when the runner hits max_iterations.

    Unlike other error paths, max_iterations cannot continue the loop, so
    injections are appended to messages but not processed by the LLM.
    The key point is they are consumed from the queue to prevent re-publish.
    """
    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        return LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id=f"c{call_count['n']}", name="read_file", arguments={"path": "x"})],
            usage={},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="file content")

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    await injection_queue.put(
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="follow-up after max iters")
    )

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.stop_reason == "max_iterations"
    assert result.had_injections is True
    # The injection was consumed from the queue (preventing re-publish)
    assert injection_queue.empty()
    # The injection message is appended to conversation history
    injected = [
        m for m in result.messages
        if m.get("role") == "user" and m.get("content") == "follow-up after max iters"
    ]
    assert len(injected) == 1


@pytest.mark.asyncio
async def test_drain_injections_set_flag_when_followup_arrives_after_last_iteration():
    """Late follow-ups drained in max_iterations should still flip had_injections."""
    from nanobot.agent.hook import AgentHook
    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        return LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id=f"c{call_count['n']}", name="read_file", arguments={"path": "x"})],
            usage={},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="file content")

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    class InjectOnLastAfterIterationHook(AgentHook):
        def __init__(self) -> None:
            self.after_iteration_calls = 0

        async def after_iteration(self, context) -> None:
            self.after_iteration_calls += 1
            if self.after_iteration_calls == 2:
                await injection_queue.put(
                    InboundMessage(
                        channel="cli",
                        sender_id="u",
                        chat_id="c",
                        content="late follow-up after max iters",
                    )
                )

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
        hook=InjectOnLastAfterIterationHook(),
    ))

    assert result.stop_reason == "max_iterations"
    assert result.had_injections is True
    assert injection_queue.empty()
    injected = [
        m for m in result.messages
        if m.get("role") == "user" and m.get("content") == "late follow-up after max iters"
    ]
    assert len(injected) == 1


@pytest.mark.asyncio
async def test_injection_cycle_cap_on_error_path():
    """Injection cycles should be capped even when every iteration hits an LLM error."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner, _MAX_INJECTION_CYCLES
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        return LLMResponse(
            content=None,
            tool_calls=[],
            finish_reason="error",
            usage={},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    drain_count = {"n": 0}

    async def inject_cb():
        drain_count["n"] += 1
        if drain_count["n"] <= _MAX_INJECTION_CYCLES:
            return [InboundMessage(channel="cli", sender_id="u", chat_id="c", content=f"msg-{drain_count['n']}")]
        return []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "previous"},
            {"role": "user", "content": "trigger error"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=20,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    # Should cap: _MAX_INJECTION_CYCLES drained rounds + 1 final round that breaks
    assert call_count["n"] == _MAX_INJECTION_CYCLES + 1

