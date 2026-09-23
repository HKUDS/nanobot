"""Tests for the mid-turn injection system: drain, checkpoints, pending queues, error paths."""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.runner_helpers import make_run_spec
from agent.session_helpers import run_session
from nanobot.agent.context import TranscriptInput
from nanobot.agent.tools.context import RequestContext
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


def _make_loop(tmp_path, *, recovery_admission=None):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr:
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        mock_sub_mgr.return_value.close = AsyncMock()
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            recovery_admission=recovery_admission,
        )
    return loop

@pytest.mark.asyncio
async def test_drain_injections_returns_empty_when_no_callback():
    """No injection_callback → empty list."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    runner = AgentRunner()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    spec = make_run_spec(provider,
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=None,
    )
    result = await runner._drain_injections(spec)
    assert result == []


@pytest.mark.asyncio
async def test_drain_injections_extracts_content_from_inbound_messages():
    """Should extract .content from InboundMessage objects."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    runner = AgentRunner()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    msgs = [
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="hello"),
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="world"),
    ]

    async def cb():
        return msgs

    spec = make_run_spec(provider,
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
async def test_drain_injections_keeps_entire_callback_snapshot():
    """A callback snapshot is never split by an arbitrary message count."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    runner = AgentRunner()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    msgs = [
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content=f"msg{i}")
        for i in range(8)
    ]

    async def cb():
        return msgs

    spec = make_run_spec(provider,
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=cb,
    )
    result = await runner._drain_injections(spec)
    assert result == [
        {"role": "user", "content": f"msg{i}"}
        for i in range(8)
    ]


@pytest.mark.asyncio
async def test_drain_injections_skips_empty_content():
    """Messages with blank content should be filtered out."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    runner = AgentRunner()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    msgs = [
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content=""),
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="   "),
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="valid"),
    ]

    async def cb():
        return msgs

    spec = make_run_spec(provider,
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=cb,
    )
    result = await runner._drain_injections(spec)
    assert result == [{"role": "user", "content": "valid"}]


@pytest.mark.asyncio
async def test_drain_injections_filters_empty_dict_payloads():
    """Pre-normalized dict injections should obey the same empty-content guard."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    runner = AgentRunner()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    multimodal = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]
    msgs = [
        {"role": "user", "content": ""},
        {"role": "user", "content": "   "},
        {"role": "user", "content": None},
        {"role": "assistant", "content": "should not be re-injected as user"},
        None,
        {"role": "user", "content": "valid"},
        {"role": "user", "content": multimodal},
    ]

    async def cb():
        return msgs

    spec = make_run_spec(provider,
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=cb,
    )
    result = await runner._drain_injections(spec)
    assert result == [
        {"role": "user", "content": "valid"},
        {"role": "user", "content": multimodal},
    ]


@pytest.mark.asyncio
async def test_drain_injections_skips_objects_with_none_content():
    """Objects exposing content=None should be skipped rather than stringified."""
    from types import SimpleNamespace

    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    runner = AgentRunner()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    async def cb():
        return [
            SimpleNamespace(content=None),
            SimpleNamespace(content=""),
            SimpleNamespace(content="valid"),
        ]

    spec = make_run_spec(provider,
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=cb,
    )
    result = await runner._drain_injections(spec)
    assert result == [{"role": "user", "content": "valid"}]


@pytest.mark.asyncio
async def test_drain_injections_handles_callback_exception():
    """If the callback raises, return empty list (error is logged)."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    runner = AgentRunner()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    async def cb():
        raise RuntimeError("boom")

    spec = make_run_spec(provider,
        initial_messages=[], tools=tools, model="m",
        max_iterations=1, max_tool_result_chars=1000,
        injection_callback=cb,
    )
    result = await runner._drain_injections(spec)
    assert result == []


@pytest.mark.asyncio
async def test_checkpoint1_injects_after_tool_execution():
    """Follow-up messages are injected after tool execution, before next LLM call."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}
    captured_messages = []

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append(list(messages))
        if call_count["n"] == 1:
            return LLMResponse(
                content="using tool",
                tool_calls=[ToolCallRequest(id="c1", name="read_file", arguments={"path": "x"})],
                usage=None,
            )
        return LLMResponse(content="final answer", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    async def execute_tool(*_args, **_kwargs):
        await injection_queue.put(
            InboundMessage(
                channel="cli", sender_id="u", chat_id="c", content="follow-up question"
            )
        )
        return "file content"

    tools.execute = AsyncMock(side_effect=execute_tool)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
async def test_terminal_wait_does_not_block_next_iteration_after_tools():
    """Background waits begin only after a no-tool response is ready to finish."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    second_request_started = asyncio.Event()
    allow_final_response = asyncio.Event()
    terminal_wait_started = asyncio.Event()
    release_terminal_result = asyncio.Event()
    call_count = 0
    terminal_result_delivered = False

    async def chat_stream_with_retry(*, messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content="working",
                tool_calls=[ToolCallRequest(id="c1", name="read_file", arguments={"path": "x"})],
            )
        if call_count == 2:
            second_request_started.set()
            await allow_final_response.wait()
            return LLMResponse(content="main work finished", tool_calls=[])
        return LLMResponse(content="combined final answer", tool_calls=[])

    async def drain_available():
        return []

    async def wait_at_terminal():
        nonlocal terminal_result_delivered
        if terminal_result_delivered:
            return []
        terminal_wait_started.set()
        await release_terminal_result.wait()
        terminal_result_delivered = True
        return [
            InboundMessage(
                channel="system",
                sender_id="subagent",
                chat_id="c",
                content="background result",
            )
        ]

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="file content")

    runner = AgentRunner()
    run_task = asyncio.create_task(runner.run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=drain_available,
        terminal_injection_callback=wait_at_terminal,
    )))

    await asyncio.wait_for(second_request_started.wait(), timeout=1.0)
    assert not terminal_wait_started.is_set()

    allow_final_response.set()
    await asyncio.wait_for(terminal_wait_started.wait(), timeout=1.0)
    assert not run_task.done()

    release_terminal_result.set()
    result = await asyncio.wait_for(run_task, timeout=1.0)

    assert call_count == 3
    assert result.had_injections is True
    assert result.final_content == "combined final answer"


@pytest.mark.asyncio
async def test_goal_continuation_precedes_terminal_wait():
    """An active sustained goal keeps running without joining background work."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="goal checkpoint", tool_calls=[]),
        LLMResponse(content="goal complete", tool_calls=[]),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    continuation_checks = 0
    terminal_waits = 0

    def continue_goal() -> str | None:
        nonlocal continuation_checks
        continuation_checks += 1
        return "Continue the active goal." if continuation_checks == 1 else None

    async def drain_available():
        return []

    async def wait_at_terminal():
        nonlocal terminal_waits
        terminal_waits += 1
        return []

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "complete the goal"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=drain_available,
        terminal_injection_callback=wait_at_terminal,
        continuation_callback=continue_goal,
    ))

    assert provider.chat_stream_with_retry.await_count == 2
    assert terminal_waits == 1
    assert result.final_content == "goal complete"


@pytest.mark.asyncio
async def test_checkpoint2_injects_after_final_response_with_resuming_stream():
    """After final response, if injections exist, stream_end should get resuming=True."""
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunner
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
            await injection_queue.put(
                InboundMessage(
                    channel="cli", sender_id="u", chat_id="c", content="quick follow-up"
                )
            )
            return LLMResponse(content="first answer", tool_calls=[], usage=None)
        return LLMResponse(content="second answer", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
async def test_injected_followup_starts_new_length_recovery_chain():
    """A follow-up gets a fresh recovery budget and no content from the prior answer."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    responses = [
        LLMResponse(content="first-1 ", finish_reason="length"),
        LLMResponse(content="first-2 ", finish_reason="length"),
        LLMResponse(content="first-3 ", finish_reason="length"),
        LLMResponse(content="first-final", finish_reason="stop"),
        LLMResponse(content="follow-up ", finish_reason="length"),
        LLMResponse(content="answer", finish_reason="stop"),
    ]
    tools = MagicMock()
    tools.get_definitions.return_value = []

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)
    call_count = 0

    async def chat_stream_with_retry(**_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 4:
            await injection_queue.put(InboundMessage(
                channel="cli", sender_id="u", chat_id="c", content="follow-up question"
            ))
        return responses[call_count - 1]

    provider.chat_stream_with_retry = chat_stream_with_retry

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "give a long answer"}],
        tools=tools,
        model="test-model",
        max_iterations=8,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    assert result.final_content == "follow-up answer"
    assert call_count == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("max_iterations", [1, 3])
async def test_followup_interrupts_truncated_answer_before_next_request(max_iterations):
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    queue = asyncio.Queue()
    requests = []
    endings = []

    class StreamingHook(AgentHook):
        def wants_streaming(self) -> bool:
            return True

        async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
            endings.append((resuming, context.stream_continues_current_message))

    async def chat_stream_with_retry(*, messages, on_content_delta=None, **kwargs):
        requests.append([dict(message) for message in messages])
        if len(requests) == 1:
            queue.put_nowait({"role": "user", "content": "Never mind. What is 2+2?"})
            if on_content_delta is not None:
                await on_content_delta("Unfinished old answer: ")
            return LLMResponse(content="Unfinished old answer: ", finish_reason="length")
        return LLMResponse(content="4", finish_reason="stop")

    provider.chat_stream_with_retry = chat_stream_with_retry
    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "old question"}],
        tools=tools,
        model="test-model",
        max_iterations=max_iterations,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=StreamingHook(),
        injection_callback=_make_injection_callback(queue),
    ))

    assert result.final_content == "4"
    assert len(requests) == 2
    assert endings[0] == (True, False)
    second_request = "\n".join(str(message.get("content", "")) for message in requests[1])
    assert "Never mind. What is 2+2?" in second_request
    assert "Continue the same response from its exact endpoint" not in second_request


@pytest.mark.asyncio
async def test_checkpoint2_preserves_final_response_in_history_before_followup():
    """A follow-up injected after a final answer must still see that answer in history."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}
    captured_messages = []

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append([dict(message) for message in messages])
        if call_count["n"] == 1:
            await injection_queue.put(
                InboundMessage(
                    channel="cli", sender_id="u", chat_id="c", content="follow-up question"
                )
            )
            return LLMResponse(content="first answer", tool_calls=[], usage=None)
        return LLMResponse(content="second answer", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append(list(messages))
        if call_count["n"] == 1:
            await pending_queue.put(InboundMessage(
                channel="cli",
                sender_id="u",
                chat_id="c",
                content="",
                media=[str(image_path)],
            ))
            return LLMResponse(content="first answer", tool_calls=[], usage=None)
        return LLMResponse(content="second answer", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.tools.get_definitions = MagicMock(return_value=[])

    pending_queue = asyncio.Queue()
    runtime = loop.llm_runtime()
    result = await loop._run_agent_loop(
        TranscriptInput(history=[{"role": "user", "content": "hello"}], current_message=None),
        runtime=runtime,
        request_context=RequestContext(channel="cli", chat_id="c", runtime=runtime),
        pending_queue=pending_queue,
    )

    assert result.final_content == "second answer"
    assert result.had_injections is True
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
async def test_pending_injection_resolves_its_own_runtime_context(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.runtime_context import (
        RUNTIME_CONTEXT_MESSAGE_META,
        RuntimeContextBlock,
        public_history_message,
        wrap_runtime_context_lines,
    )

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="first answer", tool_calls=[], usage=None),
        LLMResponse(content="second answer", tool_calls=[], usage=None),
    ])
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    seen_contexts = []

    async def provide_identity(request):
        seen_contexts.append((
            request.channel,
            request.chat_id,
            request.sender_id,
            request.message_id,
            request.session_key,
            request.original_user_text,
            request.metadata["sender_name"],
            request.metadata["thread_id"],
        ))
        return RuntimeContextBlock(
            source="identity",
            content=wrap_runtime_context_lines([
                " | ".join(str(value) for value in seen_contexts[-1]),
            ]),
        )

    loop.register_runtime_context_provider(provide_identity)
    session = loop.sessions.get_or_create("telegram:group-1")
    pending_queue = asyncio.Queue()
    await pending_queue.put(InboundMessage(
        channel="telegram",
        sender_id="user-b",
        chat_id="group-1",
        content="follow-up from the second speaker",
        metadata={
            "message_id": "message-2",
            "sender_name": "Bob",
            "thread_id": "topic-7",
        },
    ))
    await pending_queue.put(InboundMessage(
        channel="telegram",
        sender_id="user-c",
        chat_id="group-1",
        content="another follow-up",
        metadata={
            "message_id": "message-3",
            "sender_name": "Carol",
            "thread_id": "topic-7",
        },
    ))

    runtime = loop.llm_runtime()
    result = await loop._run_agent_loop(
        TranscriptInput(
            history=[{"role": "user", "content": "initial message from user A"}],
            current_message=None,
        ),
        runtime=runtime,
        session=session,
        request_context=RequestContext(
            channel="telegram",
            chat_id="group-1",
            session_key=session.key,
            runtime=runtime,
        ),
        pending_queue=pending_queue,
    )

    assert seen_contexts == [
        (
            "telegram",
            "group-1",
            "user-b",
            "message-2",
            session.key,
            "follow-up from the second speaker",
            "Bob",
            "topic-7",
        ),
        (
            "telegram",
            "group-1",
            "user-c",
            "message-3",
            session.key,
            "another follow-up",
            "Carol",
            "topic-7",
        ),
    ]

    injected = [message for message in result.messages if message.get("role") == "user"][-2:]
    assert str(injected[0]["content"]).startswith("follow-up from the second speaker\n\n")
    assert str(injected[1]["content"]).startswith("another follow-up\n\n")
    model_messages = provider.chat_stream_with_retry.await_args_list[-1].kwargs["messages"]
    assert "telegram | group-1 | user-b | message-2" in str(model_messages)
    assert "Bob | topic-7" in str(model_messages)
    assert "telegram | group-1 | user-c | message-3" in str(model_messages)
    assert "Carol | topic-7" in str(model_messages)
    assert all(
        message["_meta"][RUNTIME_CONTEXT_MESSAGE_META]["sources"] == ["identity"]
        for message in injected
    )

    loop._save_turn(session, result.messages, skip=1)
    persisted = [message for message in session.messages if message.get("role") == "user"][-2:]
    assert "telegram | group-1 | user-b | message-2" in str(persisted[0]["content"])
    assert "telegram | group-1 | user-c | message-3" in str(persisted[1]["content"])
    assert [public_history_message(message)["content"] for message in persisted] == [
        "follow-up from the second speaker",
        "another follow-up",
    ]


@pytest.mark.asyncio
async def test_subagent_pending_injection_is_hidden_history_and_not_merged(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.session.history_visibility import HIDDEN_HISTORY_META

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    call_count = {"n": 0}

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            await pending_queue.put(InboundMessage(
                channel="cli",
                sender_id="user",
                chat_id="c",
                content="visible follow-up",
            ))
            await pending_queue.put(InboundMessage(
                channel="system",
                sender_id="subagent",
                chat_id="cli:c",
                content=payload,
                metadata={"injected_event": "subagent_result", "subagent_task_id": "sub-1"},
            ))
            return LLMResponse(content="first answer", tool_calls=[], usage=None)
        return LLMResponse(content="second answer", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.tools.get_definitions = MagicMock(return_value=[])

    payload = (
        "[Subagent 'x' completed successfully]\n\n"
        "Task: t\n\n"
        "Result:\nr\n\n"
        "Summarize this naturally for the user."
    )
    pending_queue = asyncio.Queue()

    runtime = loop.llm_runtime()
    result = await loop._run_agent_loop(
        TranscriptInput(history=[{"role": "user", "content": "hello"}], current_message=None),
        runtime=runtime,
        request_context=RequestContext(channel="cli", chat_id="c", runtime=runtime),
        pending_queue=pending_queue,
    )

    assert result.final_content == "second answer"
    assert result.had_injections is True
    assert call_count["n"] == 2
    injected_users = [message for message in result.messages if message.get("role") == "user"][-2:]
    assert [message["content"] for message in injected_users] == ["visible follow-up", payload]
    assert injected_users[1][HIDDEN_HISTORY_META] == {
        "kind": "subagent_result",
        "subagent_task_id": "sub-1",
    }
    assert injected_users[1]["injected_event"] == "subagent_result"


@pytest.mark.asyncio
async def test_model_request_merges_injected_user_messages_without_losing_media():
    """The model copy may merge follow-ups while the raw transcript keeps each event."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    call_count = {"n": 0}
    captured_messages = []

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append([dict(message) for message in messages])
        if call_count["n"] == 1:
            return LLMResponse(content="first answer", tool_calls=[], usage=None)
        return LLMResponse(content="second answer", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
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

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
    assert [message["content"] for message in result.messages[-3:-1]] == [
        [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "text", "text": "look at this"},
        ],
        "and answer briefly",
    ]


def test_runner_append_keeps_recovery_followups_separate() -> None:
    """Each raw follow-up keeps its own recovery identity."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.session.recovery import PENDING_FOLLOWUP_ID_KEY

    messages = [{"role": "user", "content": "first", PENDING_FOLLOWUP_ID_KEY: "one"}]
    AgentRunner._append_injected_messages(
        messages,
        [{"role": "user", "content": "second", PENDING_FOLLOWUP_ID_KEY: "two"}],
    )

    assert [message["content"] for message in messages] == ["first", "second"]
    assert [message[PENDING_FOLLOWUP_ID_KEY] for message in messages] == ["one", "two"]


def test_model_request_merge_preserves_runtime_markers_with_media() -> None:
    from nanobot.agent.context_governance import ContextGovernor
    from nanobot.agent.runner import AgentRunner
    from nanobot.runtime_context import (
        RUNTIME_CONTEXT_HISTORY_META,
        RUNTIME_CONTEXT_MESSAGE_META,
        RuntimeContextBlock,
        append_runtime_context,
        public_history_message,
    )

    first_visible = [
        {"type": "text", "text": "first"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
    ]
    first_content, first_marker = append_runtime_context(
        first_visible,
        [RuntimeContextBlock(source="first", content="private first")],
    )
    second_content, second_marker = append_runtime_context(
        "second",
        [RuntimeContextBlock(source="second", content="private second")],
    )
    messages: list[dict] = []

    AgentRunner._append_injected_messages(messages, [
        {
            "role": "user",
            "content": first_content,
            "_meta": {RUNTIME_CONTEXT_MESSAGE_META: first_marker},
        },
        {
            "role": "user",
            "content": second_content,
            "_meta": {RUNTIME_CONTEXT_MESSAGE_META: second_marker},
        },
    ])

    assert len(messages) == 2
    merged = ContextGovernor._merge_adjacent_user_messages_for_model(messages)[0]
    assert len(messages) == 2
    assert "private first" in str(merged["content"])
    assert "private second" in str(merged["content"])
    persisted = {
        "role": "user",
        "content": merged["content"],
        RUNTIME_CONTEXT_HISTORY_META: merged["_meta"][RUNTIME_CONTEXT_MESSAGE_META],
    }
    assert public_history_message(persisted)["content"] == [
        *first_visible,
        {"type": "text", "text": "second"},
    ]


@pytest.mark.asyncio
async def test_injection_cycles_are_not_stopped_by_an_arbitrary_cap():
    """Every pending snapshot runs until the normal iteration budget is reached."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}
    injection_queue = asyncio.Queue()

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] <= 7:
            await injection_queue.put(InboundMessage(
                channel="cli",
                sender_id="u",
                chat_id="c",
                content=f"msg-{call_count['n']}",
            ))
        return LLMResponse(content=f"answer-{call_count['n']}", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    inject_cb = _make_injection_callback(injection_queue)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "start"}],
        tools=tools,
        model="test-model",
        max_iterations=20,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    assert call_count["n"] == 8


@pytest.mark.asyncio
async def test_no_injections_flag_is_false_by_default():
    """had_injections should be False when no injection callback or no messages."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_stream_with_retry(**kwargs):
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.had_injections is False


@pytest.mark.asyncio
async def test_followup_routed_to_pending_queue(tmp_path):
    """Unified-session follow-ups should route into the active pending queue."""
    from nanobot.bus.events import InboundMessage
    from nanobot.session.keys import UNIFIED_SESSION_KEY

    loop = _make_loop(tmp_path)
    loop._unified_session = True

    pending = asyncio.Queue(maxsize=20)
    loop._pending_queues[UNIFIED_SESSION_KEY] = pending

    run_task = asyncio.create_task(loop.run())
    msg = InboundMessage(channel="discord", sender_id="u", chat_id="c", content="follow-up")
    await loop.bus.publish_inbound(msg)

    queued_msg = await asyncio.wait_for(pending.get(), timeout=2)

    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert loop._active_tasks == {}
    assert queued_msg.content == "follow-up"
    assert queued_msg.session_key == UNIFIED_SESSION_KEY


@pytest.mark.asyncio
async def test_websocket_followup_is_admitted_before_recovery_queue(tmp_path):
    """Recovery admission runs before a newer WebUI message is injected."""
    from nanobot.bus.events import InboundMessage

    admission = MagicMock()
    admission.admit = AsyncMock(return_value=True)
    loop = _make_loop(tmp_path, recovery_admission=admission)

    session_key = "websocket:chat"
    pending = asyncio.Queue(maxsize=20)
    loop._pending_queues[session_key] = pending

    run_task = asyncio.create_task(loop.run())
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat",
        content="new request",
    )
    await loop.bus.publish_inbound(msg)

    queued_msg = await asyncio.wait_for(pending.get(), timeout=2)
    admission.admit.assert_awaited_once_with(msg)
    assert queued_msg.content == msg.content
    assert queued_msg.metadata["_recovery_followup_id"]

    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)


@pytest.mark.asyncio
async def test_unified_websocket_followup_admits_effective_session(tmp_path):
    """Recovery admission and the pending queue must use the same session key."""
    from nanobot.bus.events import InboundMessage
    from nanobot.session.keys import UNIFIED_SESSION_KEY

    admission = MagicMock()
    admission.admit = AsyncMock(return_value=True)
    loop = _make_loop(tmp_path, recovery_admission=admission)
    loop._unified_session = True

    pending = asyncio.Queue(maxsize=20)
    loop._pending_queues[UNIFIED_SESSION_KEY] = pending

    run_task = asyncio.create_task(loop.run())
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat",
        content="new request",
    )
    await loop.bus.publish_inbound(msg)

    queued_msg = await asyncio.wait_for(pending.get(), timeout=2)
    admitted_msg = admission.admit.await_args.args[0]
    assert admitted_msg.session_key == UNIFIED_SESSION_KEY
    assert queued_msg.session_key == UNIFIED_SESSION_KEY

    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)


@pytest.mark.asyncio
async def test_mid_turn_subagent_result_does_not_resolve_a_new_turn_route(tmp_path):
    """Injected results stay inside the active turn instead of opening a side turn."""
    from nanobot.bus.events import InboundMessage

    loop = _make_loop(tmp_path)
    route_policy = MagicMock(side_effect=lambda _msg, _key, route: route)
    loop.turn_delivery_factory.route_policy = route_policy

    session_key = "websocket:chat-1"
    pending = asyncio.Queue(maxsize=20)
    loop._pending_queues[session_key] = pending

    run_task = asyncio.create_task(loop.run())
    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id=session_key,
        content="background result",
        metadata={
            "injected_event": "subagent_result",
            "subagent_task_id": "sub-1",
        },
        session_key_override=session_key,
    )
    await loop.bus.publish_inbound(msg)

    queued_msg = await asyncio.wait_for(pending.get(), timeout=2)

    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert queued_msg is msg
    assert loop._active_tasks == {}
    route_policy.assert_not_called()


@pytest.mark.asyncio
async def test_pending_queue_batches_full_snapshot_before_first_model_call(tmp_path):
    """All messages waiting at the checkpoint enter one model request in order."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    captured_messages: list[list[dict]] = []
    call_count = {"n": 0}

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append([dict(message) for message in messages])
        return LLMResponse(content=f"answer-{call_count['n']}", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.tools.get_definitions = MagicMock(return_value=[])

    pending_queue = asyncio.Queue()
    total_followups = 8
    for idx in range(total_followups):
        await pending_queue.put(InboundMessage(
            channel="cli",
            sender_id="u",
            chat_id="c",
            content=f"follow-up-{idx}",
        ))

    runtime = loop.llm_runtime()
    result = await loop._run_agent_loop(
        TranscriptInput(history=[{"role": "user", "content": "hello"}], current_message=None),
        runtime=runtime,
        request_context=RequestContext(channel="cli", chat_id="c", runtime=runtime),
        pending_queue=pending_queue,
    )

    assert result.final_content == "answer-1"
    assert result.had_injections is True
    assert call_count["n"] == 1
    flattened_user_content = "\n".join(
        message["content"]
        for message in captured_messages[-1]
        if message.get("role") == "user" and isinstance(message.get("content"), str)
    )
    for idx in range(total_followups):
        assert f"follow-up-{idx}" in flattened_user_content
    raw_followups = [
        message["content"]
        for message in result.messages
        if message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and message["content"].startswith("follow-up-")
    ]
    assert raw_followups == [f"follow-up-{idx}" for idx in range(total_followups)]
    assert pending_queue.empty()


@pytest.mark.asyncio
async def test_pending_queue_snapshot_excludes_messages_arriving_during_conversion(tmp_path):
    """A checkpoint is a finite snapshot even when message conversion awaits."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    captured_messages: list[list[dict]] = []

    async def chat_stream_with_retry(*, messages, **kwargs):
        captured_messages.append([dict(message) for message in messages])
        return LLMResponse(
            content=f"answer-{len(captured_messages)}",
            tool_calls=[],
            usage=None,
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    conversion_started = asyncio.Event()
    release_conversion = asyncio.Event()

    async def block_first_conversion(request):
        if request.original_user_text == "first snapshot":
            conversion_started.set()
            await release_conversion.wait()
        return None

    loop.register_runtime_context_provider(block_first_conversion)
    pending_queue = asyncio.Queue()
    pending_queue.put_nowait(InboundMessage(
        channel="cli",
        sender_id="u",
        chat_id="c",
        content="first snapshot",
    ))

    runtime = loop.llm_runtime()
    run_task = asyncio.create_task(loop._run_agent_loop(
        TranscriptInput(history=[{"role": "user", "content": "hello"}], current_message=None),
        runtime=runtime,
        request_context=RequestContext(channel="cli", chat_id="c", runtime=runtime),
        pending_queue=pending_queue,
    ))
    await asyncio.wait_for(conversion_started.wait(), timeout=2)
    pending_queue.put_nowait(InboundMessage(
        channel="cli",
        sender_id="u",
        chat_id="c",
        content="next snapshot",
    ))
    release_conversion.set()

    result = await asyncio.wait_for(run_task, timeout=2)

    assert result.final_content == "answer-2"
    assert len(captured_messages) == 2
    first_request = "\n".join(str(message.get("content", "")) for message in captured_messages[0])
    second_request = "\n".join(str(message.get("content", "")) for message in captured_messages[1])
    assert "first snapshot" in first_request
    assert "next snapshot" not in first_request
    assert "next snapshot" in second_request


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_conversion", [False, True])
async def test_pending_snapshot_rolls_back_before_later_arrivals(tmp_path, cancel_conversion):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="answer"))
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    loop.tools.get_definitions = MagicMock(return_value=[])
    pending = asyncio.Queue()
    contents = ["before", "bad", "after"]
    for content in contents:
        pending.put_nowait(InboundMessage(
            channel="cli", sender_id="u", chat_id="c", content=content,
        ))
    failed = False

    async def context_provider(request):
        nonlocal failed
        if request.original_user_text == "bad" and not failed:
            failed = True
            pending.put_nowait(InboundMessage(
                channel="cli", sender_id="u", chat_id="c", content="later arrival",
            ))
            if cancel_conversion:
                raise asyncio.CancelledError
            raise RuntimeError("context lookup temporarily unavailable")
        return None

    loop.register_runtime_context_provider(context_provider)
    runtime = loop.llm_runtime()
    try:
        run = loop._run_agent_loop(
            TranscriptInput(history=[{"role": "user", "content": "root"}], current_message=None),
            runtime=runtime,
            request_context=RequestContext(channel="cli", chat_id="c", runtime=runtime),
            pending_queue=pending,
        )
        if cancel_conversion:
            with pytest.raises(asyncio.CancelledError):
                await run
            assert [pending.get_nowait().content for _ in range(pending.qsize())] == [
                *contents, "later arrival",
            ]
        else:
            result = await run
            user_content = [
                message["content"] for message in result.messages if message["role"] == "user"
            ]
            assert user_content == ["root", *contents, "later arrival"]
            assert pending.empty()
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_persistent_conversion_error_does_not_drop_later_session_inputs(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.bus.runtime_events import TurnCompleted

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    loop.tools.get_definitions = MagicMock(return_value=[])
    completions = []
    loop.bus.subscribe(completions.append, TurnCompleted)
    calls = 0

    async def chat(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            for content in ["before", "bad", "after"]:
                loop._enqueue_session_message(InboundMessage(
                    channel="cli", sender_id="u", chat_id="c", content=content,
                ))
        return LLMResponse(content="answer", finish_reason="stop")

    async def context_provider(request):
        if request.original_user_text == "bad":
            raise RuntimeError("context unavailable")
        return None

    provider.chat_stream_with_retry = chat
    loop.register_runtime_context_provider(context_provider)
    try:
        await run_session(loop, InboundMessage(
            channel="cli", sender_id="u", chat_id="c", content="root",
        ))
        loop.sessions.invalidate("cli:c")
        history = loop.sessions.get_or_create("cli:c").messages
        assert [message["content"] for message in history if message["role"] == "user"] == [
            "root", "before", "after",
        ]
        assert sum(event.outcome == "failed" for event in completions) == 1
        assert "cli:c" not in loop._pending_queues
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_session_inbox_is_installed_before_worker_start(tmp_path):
    """A preloaded burst has one FIFO path before the worker can be scheduled."""
    from nanobot.bus.events import InboundMessage, OutboundMessage

    loop = _make_loop(tmp_path)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    all_processed = asyncio.Event()
    processed: list[str] = []
    followups = [f"follow-up-{index}" for index in range(40)]

    async def _process_message(msg, **_kwargs):
        processed.append(msg.content)
        if msg.content == "initial":
            first_started.set()
            await release_first.wait()
        if len(processed) == len(followups) + 1:
            all_processed.set()
        return OutboundMessage(channel="cli", chat_id="c", content=msg.content)

    loop._process_message = _process_message  # type: ignore[method-assign]
    await loop.bus.publish_inbound(
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="initial")
    )
    for content in followups:
        await loop.bus.publish_inbound(
            InboundMessage(channel="cli", sender_id="u", chat_id="c", content=content)
        )

    run_task = asyncio.create_task(loop.run())
    await asyncio.wait_for(first_started.wait(), timeout=2)

    session_key = "cli:c"
    for _ in range(200):
        pending = loop._pending_queues.get(session_key)
        if pending is not None and pending.qsize() == len(followups):
            break
        await asyncio.sleep(0.01)
    assert len(loop._active_tasks[session_key]) == 1
    assert loop._pending_queues[session_key].qsize() == len(followups)

    release_first.set()
    await asyncio.wait_for(all_processed.wait(), timeout=5)
    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert processed == ["initial", *followups]


@pytest.mark.asyncio
@pytest.mark.parametrize("log_content", [True, False])
async def test_busy_session_burst_reaches_next_model_call_as_one_ordered_batch(
    tmp_path, request, log_content,
):
    """Messages accumulated during a model call share its next request snapshot."""
    from loguru import logger

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.session.manager import SessionPolicy

    records = []
    sink = logger.add(lambda message: records.append(message.record))
    request.addfinalizer(lambda: logger.remove(sink))

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    first_request_started = asyncio.Event()
    release_first_request = asyncio.Event()
    second_request_started = asyncio.Event()
    captured_messages: list[list[dict]] = []

    async def chat_stream_with_retry(*, messages, **kwargs):
        captured_messages.append([dict(message) for message in messages])
        if len(captured_messages) == 1:
            first_request_started.set()
            await release_first_request.wait()
            return LLMResponse(content="first answer", tool_calls=[], usage=None)
        second_request_started.set()
        return LLMResponse(content="batch answer", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.sessions.get_or_create("cli:c").policy = SessionPolicy(log_content=log_content)
    followups = [f"follow-up-{index:02}" for index in range(12)]

    run_task = asyncio.create_task(loop.run())
    await loop.bus.publish_inbound(InboundMessage(
        channel="cli",
        sender_id="u",
        chat_id="c",
        content="initial",
    ))
    await asyncio.wait_for(first_request_started.wait(), timeout=2)
    for content in followups:
        await loop.bus.publish_inbound(InboundMessage(
            channel="cli",
            sender_id="u",
            chat_id="c",
            content=content,
        ))
    for _ in range(200):
        pending = loop._pending_queues.get("cli:c")
        if pending is not None and pending.qsize() == len(followups):
            break
        await asyncio.sleep(0.01)
    assert loop._pending_queues["cli:c"].qsize() == len(followups)

    release_first_request.set()
    await asyncio.wait_for(second_request_started.wait(), timeout=2)
    for _ in range(200):
        if "cli:c" not in loop._pending_queues:
            break
        await asyncio.sleep(0.01)
    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert len(captured_messages) == 2
    second_request = "\n".join(
        str(message.get("content", "")) for message in captured_messages[1]
    )
    positions = [second_request.index(content) for content in followups]
    assert positions == sorted(positions)
    assert loop.bus.inbound_size == 0

    injections = [r for r in records if r["message"].startswith("Injected ")]
    assert len(injections) == 1
    record = injections[0]
    preview = "\n\n".join(followups)[:80] + "..." if log_content else "[content hidden]"
    assert record["message"] == (
        f"Injected {len(followups)} follow-up message(s) after final response (snapshot 1): {preview}"
    )
    assert record["level"].name == "INFO"
    assert record["extra"]["session_key"] == "cli:c"
    assert record["extra"]["turn_id"]


@pytest.mark.asyncio
async def test_session_worker_processes_leftovers_without_republishing(tmp_path):
    """Messages left by one turn stay on the same FIFO worker."""
    from nanobot.bus.events import InboundMessage, OutboundMessage

    loop = _make_loop(tmp_path)
    session_key = "cli:c"
    pending = asyncio.Queue()
    processed: list[str] = []

    async def _process_message(msg, **_kwargs):
        processed.append(msg.content)
        return OutboundMessage(channel="cli", chat_id="c", content=msg.content)

    loop._process_message = _process_message  # type: ignore[method-assign]
    for content in ("first", "leftover-1", "leftover-2"):
        pending.put_nowait(InboundMessage(
            channel="cli",
            sender_id="u",
            chat_id="c",
            content=content,
        ))
    loop._pending_queues[session_key] = pending

    await loop._run_session_queue(session_key, pending)

    assert processed == ["first", "leftover-1", "leftover-2"]
    assert session_key not in loop._pending_queues
    assert loop.bus.inbound_size == 0


@pytest.mark.asyncio
async def test_drain_injections_after_recoverable_tool_error():
    """A tool error and injected follow-up continue in the same runner conversation."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="stale prefix ",
                finish_reason="length",
                usage=None,
            )
        if call_count["n"] == 2:
            return LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="c1", name="exec", arguments={"cmd": "bad"})],
                usage=None,
            )
        # Third call: respond normally to the injected follow-up.
        return LLMResponse(content="reply to follow-up", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(side_effect=RuntimeError("tool exploded"))

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    await injection_queue.put(
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="follow-up after error")
    )

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    assert result.final_content == "reply to follow-up"
    assert call_count["n"] == 3
    # The injection should be in the messages history
    injected = [
        m for m in result.messages
        if m.get("role") == "user" and m.get("content") == "follow-up after error"
    ]
    assert len(injected) == 1


@pytest.mark.asyncio
async def test_drain_injections_on_llm_error():
    """A follow-up after an error stays raw and reaches the next model request."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}
    requests: list[list[dict]] = []

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        requests.append(messages)
        if call_count["n"] == 1:
            await injection_queue.put(
                InboundMessage(
                    channel="cli",
                    sender_id="u",
                    chat_id="c",
                    content="follow-up after LLM error",
                )
            )
            return LLMResponse(
                content=None,
                tool_calls=[],
                finish_reason="error",
                usage=None,
            )
        # Second call: respond normally to the injected follow-up
        return LLMResponse(content="recovered answer", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=None,
        transcript_input=TranscriptInput(
            history=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "previous response"},
                {"role": "user", "content": "trigger error"},
            ],
            current_message=None,
        ),
        transcript_builder=lambda transcript: [
            {"role": "system", "content": "system"},
            *transcript.history,
        ],
        consolidate_history=AsyncMock(return_value=None),
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
    ))

    assert result.had_injections is True
    assert result.final_content == "recovered answer"
    assert "follow-up after LLM error" in str(requests[1])
    assert [
        message["content"]
        for message in result.messages
        if message.get("role") == "user"
    ][-2:] == [
        "trigger error",
        "follow-up after LLM error",
    ]


@pytest.mark.asyncio
async def test_drain_injections_on_empty_final_response():
    """Pending injections should be drained when the runner exits due to empty response."""
    from nanobot.agent.runner import _MAX_EMPTY_RETRIES, AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] <= _MAX_EMPTY_RETRIES + 1:
            if call_count["n"] == _MAX_EMPTY_RETRIES + 1:
                await injection_queue.put(InboundMessage(
                    channel="cli",
                    sender_id="u",
                    chat_id="c",
                    content="follow-up after empty",
                ))
            return LLMResponse(content="", tool_calls=[], usage=None)
        # After retries exhausted + injection drain, respond normally
        return LLMResponse(content="answer after empty", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
async def test_max_iterations_without_finalization_keeps_late_injection_queued():
    """Never consume a user message when no later model request can observe it."""
    from nanobot.agent.hook import AgentHook
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        return LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id=f"c{call_count['n']}", name="read_file", arguments={"path": "x"})],
            usage=None,
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="file content")

    injection_queue = asyncio.Queue()
    inject_cb = _make_injection_callback(injection_queue)

    class InjectAfterLastIterationHook(AgentHook):
        async def after_iteration(self, context) -> None:
            if context.iteration == 1:
                await injection_queue.put(InboundMessage(
                    channel="cli",
                    sender_id="u",
                    chat_id="c",
                    content="follow-up after max iters",
                ))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        injection_callback=inject_cb,
        hook=InjectAfterLastIterationHook(),
        finalize_on_max_iterations=False,
    ))

    assert result.stop_reason == "max_iterations"
    assert result.had_injections is False
    assert injection_queue.qsize() == 1
    assert (await injection_queue.get()).content == "follow-up after max iters"


@pytest.mark.asyncio
async def test_max_iterations_finalization_consumes_late_injection():
    """The finalization model request receives the snapshot after the last iteration."""
    from nanobot.agent.hook import AgentHook
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}
    captured_messages: list[list[dict]] = []

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append([dict(message) for message in messages])
        return LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id=f"c{call_count['n']}", name="read_file", arguments={"path": "x"})],
            usage=None,
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
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

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
    assert call_count["n"] == 3
    finalization_request = "\n".join(
        str(message.get("content", "")) for message in captured_messages[-1]
    )
    assert "late follow-up after max iters" in finalization_request
    injected = [
        m for m in result.messages
        if m.get("role") == "user" and m.get("content") == "late follow-up after max iters"
    ]
    assert len(injected) == 1


@pytest.mark.asyncio
async def test_error_path_is_not_stopped_by_an_arbitrary_injection_cap():
    """Error recovery consumes every arrived snapshot until no follow-up remains."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.bus.events import InboundMessage

    provider = MagicMock()
    call_count = {"n": 0}
    injection_queue = asyncio.Queue()

    async def chat_stream_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] <= 7:
            await injection_queue.put(InboundMessage(
                channel="cli",
                sender_id="u",
                chat_id="c",
                content=f"msg-{call_count['n']}",
            ))
        return LLMResponse(
            content=None,
            tool_calls=[],
            finish_reason="error",
            usage=None,
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    inject_cb = _make_injection_callback(injection_queue)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
    assert call_count["n"] == 8
