import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from blackcat.agent.context import ContextBuilder
from blackcat.agent.loop import AgentLoop
from blackcat.bus.events import InboundMessage
from blackcat.bus.queue import MessageBus
from blackcat.cron.session_turns import CRON_HISTORY_META, CRON_TRIGGER_META
from blackcat.providers.base import LLMResponse
from blackcat.session.goal_state import GOAL_STATE_KEY
from blackcat.session.manager import Session, SessionManager
from blackcat.session.turn_continuation import (
    INTERNAL_CONTINUATION_META,
    INTERNAL_CONTINUATION_RUN_STARTED_AT_META,
)
from blackcat.session.webui_turns import (
    TITLE_GENERATION_MAX_TOKENS,
    TITLE_GENERATION_REASONING_EFFORT,
    WEBUI_SESSION_METADATA_KEY,
    WEBUI_TITLE_METADATA_KEY,
    WebuiTurnCoordinator,
    clean_generated_title,
    maybe_generate_webui_title,
)
from blackcat.utils.llm_runtime import LLMRuntime


def _mk_loop() -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    from blackcat.config.schema import AgentDefaults

    loop.max_tool_result_chars = AgentDefaults().max_tool_result_chars
    return loop


def _make_full_loop(tmp_path: Path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Test title"))
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    WebuiTurnCoordinator(
        bus=loop.bus,
        sessions=loop.sessions,
        schedule_background=lambda coro: loop._schedule_background(coro),
    ).subscribe(loop.runtime_events)
    return loop


def test_agent_loop_llm_runtime_reflects_current_provider_and_model(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    runtime = loop.llm_runtime()

    assert runtime.provider is loop.provider
    assert runtime.model == "test-model"

    next_provider = MagicMock()
    loop.provider = next_provider
    loop.model = "next-model"
    runtime = loop.llm_runtime()

    assert runtime.provider is next_provider
    assert runtime.model == "next-model"


def test_persist_cron_turn_uses_distinct_history_marker(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    session = loop.sessions.get_or_create("websocket:auto")
    prompt_ref = {"id": "cron.agent_turn.reminder", "version": 1, "sha256": "abc"}

    persisted = loop._persist_user_message_early(
        InboundMessage(
            channel="websocket",
            sender_id="cron",
            chat_id="auto",
            content="Cron job: internal prompt",
            metadata={
                CRON_TRIGGER_META: {
                    "job_id": "job-1",
                    "job_name": "Daily check",
                    "run_id": "job-1:1",
                    "prompt_ref": prompt_ref,
                    "persist_content": "Scheduled cron job triggered: Daily check",
                }
            },
        ),
        session,
    )

    assert persisted is True
    message = session.messages[-1]
    assert message["content"] == "Scheduled cron job triggered: Daily check"
    assert message[CRON_HISTORY_META] is True
    assert CRON_TRIGGER_META not in message
    assert message["cron_job_id"] == "job-1"
    assert message["cron_job_name"] == "Daily check"
    assert message["cron_run_id"] == "job-1:1"
    assert message["cron_prompt_ref"] == prompt_ref


def test_clean_generated_title_strips_reasoning_tags() -> None:
    assert clean_generated_title("<think>reasoning</think> WebUI polish") == "WebUI polish"
    assert clean_generated_title("Title: <think> The user said hello") == ""


@pytest.mark.asyncio
async def test_generate_webui_title_only_for_marked_webui_sessions(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content='"优化 WebUI 侧边栏。"', finish_reason="stop")
    )
    session = loop.sessions.get_or_create("websocket:chat-title")
    session.metadata[WEBUI_SESSION_METADATA_KEY] = True
    session.add_message("user", "帮我优化一下 webui 的 sidebar")
    session.add_message("assistant", "可以，我会先调整布局和视觉层级。")
    loop.sessions.save(session)

    generated = await maybe_generate_webui_title(
        sessions=loop.sessions,
        session_key="websocket:chat-title",
        provider=loop.provider,
        model=loop.model,
    )

    assert generated is True
    assert session.metadata[WEBUI_TITLE_METADATA_KEY] == "优化 WebUI 侧边栏"
    loop.provider.chat_with_retry.assert_awaited_once()
    assert loop.provider.chat_with_retry.await_args.kwargs["max_tokens"] == TITLE_GENERATION_MAX_TOKENS
    assert (
        loop.provider.chat_with_retry.await_args.kwargs["reasoning_effort"]
        == TITLE_GENERATION_REASONING_EFFORT
    )


@pytest.mark.asyncio
async def test_generate_webui_title_skips_plain_websocket_sessions(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="Plain websocket title", finish_reason="stop")
    )
    session = loop.sessions.get_or_create("websocket:custom-client")
    session.add_message("user", "hello from a custom websocket client")
    loop.sessions.save(session)

    generated = await maybe_generate_webui_title(
        sessions=loop.sessions,
        session_key="websocket:custom-client",
        provider=loop.provider,
        model=loop.model,
    )

    assert generated is False
    assert WEBUI_TITLE_METADATA_KEY not in session.metadata
    loop.provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_webui_title_ignores_command_only_sessions(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    session = loop.sessions.get_or_create("websocket:command-title")
    session.metadata[WEBUI_SESSION_METADATA_KEY] = True
    session.add_message("user", "/model deep", _command=True)
    session.add_message(
        "assistant",
        "Switched model preset to `deep`.\n- Model: `deepseek-v4-pro`",
        _command=True,
    )
    loop.sessions.save(session)

    generated = await maybe_generate_webui_title(
        sessions=loop.sessions,
        session_key="websocket:command-title",
        provider=loop.provider,
        model=loop.model,
    )

    assert generated is False
    assert WEBUI_TITLE_METADATA_KEY not in session.metadata
    loop.provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_webui_title_ignores_cron_internal_turns(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    session = loop.sessions.get_or_create("websocket:cron-title")
    session.metadata[WEBUI_SESSION_METADATA_KEY] = True
    session.add_message(
        "user",
        "Scheduled cron job triggered: 30s-test\n\nInternal reminder prompt",
        **{CRON_HISTORY_META: True},
    )
    session.add_message("assistant", "提醒已经到期。")
    loop.sessions.save(session)

    generated = await maybe_generate_webui_title(
        sessions=loop.sessions,
        session_key="websocket:cron-title",
        provider=loop.provider,
        model=loop.model,
    )

    assert generated is False
    assert WEBUI_TITLE_METADATA_KEY not in session.metadata
    loop.provider.chat_with_retry.assert_not_awaited()


def test_webui_title_update_uses_captured_llm_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MessageBus()
    sessions = SessionManager(tmp_path)
    scheduled: list[object] = []
    captured: dict[str, object] = {}

    async def fake_title_after_turn(**kwargs: object) -> bool:
        captured.update(kwargs)
        return False

    monkeypatch.setattr(
        "blackcat.session.webui_turns.maybe_generate_webui_title_after_turn",
        fake_title_after_turn,
    )
    coordinator = WebuiTurnCoordinator(
        bus=bus,
        sessions=sessions,
        schedule_background=lambda coro: scheduled.append(coro),
    )
    provider = MagicMock()
    msg = InboundMessage(
        channel="websocket",
        sender_id="u1",
        chat_id="chat1",
        content="say hello",
        metadata={"webui": True},
    )

    coordinator.capture_title_context(
        "websocket:chat1",
        msg,
        LLMRuntime(provider, "turn-model"),
    )
    asyncio.run(coordinator.handle_turn_end(
        msg,
        session_key="websocket:chat1",
        latency_ms=None,
    ))

    assert len(scheduled) == 1
    asyncio.run(scheduled[0])  # type: ignore[arg-type]

    assert captured["provider"] is provider
    assert captured["model"] == "turn-model"


def test_save_turn_skips_multimodal_user_when_only_runtime_context() -> None:
    loop = _mk_loop()
    session = Session(key="test:runtime-only")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{"role": "user", "content": [{"type": "text", "text": runtime}]}],
        skip=0,
    )
    assert session.messages == []


def test_save_turn_keeps_image_placeholder_with_path_after_runtime_strip() -> None:
    loop = _mk_loop()
    session = Session(key="test:image")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}, "_meta": {"path": "/media/feishu/photo.jpg"}},
                {"type": "text", "text": runtime},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image: /media/feishu/photo.jpg]"}]


def test_save_turn_keeps_image_placeholder_without_meta() -> None:
    loop = _mk_loop()
    session = Session(key="test:image-no-meta")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                {"type": "text", "text": runtime},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image]"}]


def test_save_turn_strips_runtime_context_suffix_from_string() -> None:
    loop = _mk_loop()
    session = Session(key="test:suffix-strip")
    runtime = (
        ContextBuilder._RUNTIME_CONTEXT_TAG
        + "\nCurrent Time: now\n"
        + ContextBuilder._RUNTIME_CONTEXT_END
    )

    loop._save_turn(
        session,
        [{"role": "user", "content": f"hello world\n\n{runtime}"}],
        skip=0,
    )
    assert session.messages[0]["content"] == "hello world"


def test_save_turn_skips_string_user_when_only_runtime_context_suffix() -> None:
    loop = _mk_loop()
    session = Session(key="test:suffix-only")
    runtime = (
        ContextBuilder._RUNTIME_CONTEXT_TAG
        + "\nCurrent Time: now\n"
        + ContextBuilder._RUNTIME_CONTEXT_END
    )

    loop._save_turn(
        session,
        [{"role": "user", "content": runtime}],
        skip=0,
    )
    assert session.messages == []


def test_save_turn_keeps_tool_results_under_16k() -> None:
    loop = _mk_loop()
    session = Session(key="test:tool-result")
    content = "x" * 12_000

    loop._save_turn(
        session,
        [{"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": content}],
        skip=0,
    )

    assert session.messages[0]["content"] == content


def test_save_turn_stamps_latency_on_last_assistant() -> None:
    loop = _mk_loop()
    session = Session(key="test:latency")

    loop._save_turn(
        session,
        [
            {"role": "assistant", "content": "hello", "tool_calls": [{"id": "c1"}]},
            {"role": "assistant", "content": "final answer"},
        ],
        skip=0,
        turn_latency_ms=12345,
    )

    assert session.messages[-1]["role"] == "assistant"
    assert session.messages[-1]["content"] == "final answer"
    assert session.messages[-1]["latency_ms"] == 12345


def test_restore_runtime_checkpoint_rehydrates_completed_and_pending_tools() -> None:
    loop = _mk_loop()
    session = Session(
        key="test:checkpoint",
        metadata={
            AgentLoop._RUNTIME_CHECKPOINT_KEY: {
                "assistant_message": {
                    "role": "assistant",
                    "content": "working",
                    "tool_calls": [
                        {
                            "id": "call_done",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        },
                        {
                            "id": "call_pending",
                            "type": "function",
                            "function": {"name": "exec", "arguments": "{}"},
                        },
                    ],
                },
                "completed_tool_results": [
                    {
                        "role": "tool",
                        "tool_call_id": "call_done",
                        "name": "read_file",
                        "content": "ok",
                    }
                ],
                "pending_tool_calls": [
                    {
                        "id": "call_pending",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    }
                ],
            }
        },
    )

    restored = loop._restore_runtime_checkpoint(session)

    assert restored is True
    assert session.metadata.get(AgentLoop._RUNTIME_CHECKPOINT_KEY) is None
    assert session.messages[0]["role"] == "assistant"
    assert session.messages[1]["tool_call_id"] == "call_done"
    assert session.messages[2]["tool_call_id"] == "call_pending"
    assert "interrupted before this tool finished" in session.messages[2]["content"].lower()


def test_restore_runtime_checkpoint_dedupes_overlapping_tail() -> None:
    loop = _mk_loop()
    session = Session(
        key="test:checkpoint-overlap",
        messages=[
            {
                "role": "assistant",
                "content": "working",
                "tool_calls": [
                    {
                        "id": "call_done",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    },
                    {
                        "id": "call_pending",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_done",
                "name": "read_file",
                "content": "ok",
            },
        ],
        metadata={
            AgentLoop._RUNTIME_CHECKPOINT_KEY: {
                "assistant_message": {
                    "role": "assistant",
                    "content": "working",
                    "tool_calls": [
                        {
                            "id": "call_done",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        },
                        {
                            "id": "call_pending",
                            "type": "function",
                            "function": {"name": "exec", "arguments": "{}"},
                        },
                    ],
                },
                "completed_tool_results": [
                    {
                        "role": "tool",
                        "tool_call_id": "call_done",
                        "name": "read_file",
                        "content": "ok",
                    }
                ],
                "pending_tool_calls": [
                    {
                        "id": "call_pending",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    }
                ],
            }
        },
    )

    restored = loop._restore_runtime_checkpoint(session)

    assert restored is True
    assert session.metadata.get(AgentLoop._RUNTIME_CHECKPOINT_KEY) is None
    assert len(session.messages) == 3
    assert session.messages[0]["role"] == "assistant"
    assert session.messages[1]["tool_call_id"] == "call_done"
    assert session.messages[2]["tool_call_id"] == "call_pending"


@pytest.mark.asyncio
async def test_process_message_persists_user_message_before_turn_completes(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop._run_agent_loop = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

    msg = InboundMessage(channel="feishu", sender_id="u1", chat_id="c1", content="persist me")
    with pytest.raises(RuntimeError, match="boom"):
        await loop._process_message(msg)

    loop.sessions.invalidate("feishu:c1")
    persisted = loop.sessions.get_or_create("feishu:c1")
    assert [m["role"] for m in persisted.messages] == ["user"]
    assert persisted.messages[0]["content"] == "persist me"
    assert persisted.metadata.get(AgentLoop._PENDING_USER_TURN_KEY) is True
    assert persisted.updated_at >= persisted.created_at


# 1x1 PNG used by the media-persistence tests. ``extract_documents`` runs
# at the top of ``_process_message`` and filters ``msg.media`` down to
# paths that magic-byte-sniff as images, so the test fixture needs real
# bytes on disk (not just placeholder paths).
_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x00\x00\x02\x00\x01"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_process_message_persists_media_paths_on_user_turn(tmp_path: Path) -> None:
    """User turns that attach images must record the media paths alongside
    the text so the webui can rehydrate previews on session replay.

    This is the producer half of the signed-media-URL round-trip: paths are
    stored here, then :meth:`WebSocketChannel._augment_media_urls` maps them
    onto signed URLs on the way out.
    """
    img_a = tmp_path / "uuid-1.png"
    img_a.write_bytes(_PNG_1X1)
    img_b = tmp_path / "uuid-2.png"
    img_b.write_bytes(_PNG_1X1)

    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop._run_agent_loop = AsyncMock(side_effect=RuntimeError("interrupt"))  # type: ignore[method-assign]

    msg = InboundMessage(
        channel="websocket",
        sender_id="u1",
        chat_id="c-media",
        content="look",
        media=[str(img_a), str(img_b)],
    )
    with pytest.raises(RuntimeError, match="interrupt"):
        await loop._process_message(msg)

    loop.sessions.invalidate("websocket:c-media")
    persisted = loop.sessions.get_or_create("websocket:c-media")
    assert [m["role"] for m in persisted.messages] == ["user"]
    assert persisted.messages[0]["content"] == "look"
    assert persisted.messages[0]["media"] == [str(img_a), str(img_b)]


@pytest.mark.asyncio
async def test_process_message_persists_media_only_turn_without_text(tmp_path: Path) -> None:
    """A turn with images but no text still persists (previously silent-dropped).

    The old early-persist gate skipped messages without text, leaving pure
    image turns un-checkpointed. They now materialise as an empty-content
    user row with ``media`` attached.
    """
    img = tmp_path / "only.png"
    img.write_bytes(_PNG_1X1)

    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop._run_agent_loop = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

    msg = InboundMessage(
        channel="websocket",
        sender_id="u1",
        chat_id="c-images-only",
        content="",
        media=[str(img)],
    )
    with pytest.raises(RuntimeError):
        await loop._process_message(msg)

    loop.sessions.invalidate("websocket:c-images-only")
    persisted = loop.sessions.get_or_create("websocket:c-images-only")
    assert len(persisted.messages) == 1
    assert persisted.messages[0]["role"] == "user"
    assert persisted.messages[0]["content"] == ""
    assert persisted.messages[0]["media"] == [str(img)]


@pytest.mark.asyncio
async def test_process_message_does_not_duplicate_early_persisted_user_message(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop._run_agent_loop = AsyncMock(return_value=(
        "done",
        None,
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "done"},
        ],
        "stop",
        False,
    ))  # type: ignore[method-assign]

    result = await loop._process_message(
        InboundMessage(channel="feishu", sender_id="u1", chat_id="c2", content="hello")
    )

    assert result is not None
    assert result.content == "done"
    session = loop.sessions.get_or_create("feishu:c2")
    assert [
        {k: v for k, v in m.items() if k in {"role", "content"}}
        for m in session.messages
    ] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "done"},
    ]
    assert AgentLoop._PENDING_USER_TURN_KEY not in session.metadata


@pytest.mark.asyncio
async def test_internal_continuation_queues_turn_without_fake_user_history(
    tmp_path: Path,
) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    session = loop.sessions.get_or_create("feishu:c-auto")
    session.metadata[GOAL_STATE_KEY] = {
        "status": "active",
        "objective": "Finish the long goal.",
    }
    loop.sessions.save(session)

    calls: list[dict] = []

    async def fake_run_agent_loop(initial_messages, *, metadata=None, **_kwargs):
        calls.append({"initial_messages": initial_messages, "metadata": metadata})
        if len(calls) == 1:
            return (
                "paused",
                [],
                [*initial_messages, {"role": "assistant", "content": "paused"}],
                    "max_iterations",
                    False,
                )
        return (
            "done",
            [],
            [*initial_messages, {"role": "assistant", "content": "done"}],
                "completed",
                False,
            )

    loop._run_agent_loop = fake_run_agent_loop  # type: ignore[method-assign]
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue()

    first = await loop._process_message(
        InboundMessage(
            channel="feishu",
            sender_id="u1",
            chat_id="c-auto",
            content="start the goal",
        ),
        pending_queue=pending,
    )

    assert first is None
    queued = pending.get_nowait()
    assert queued.sender_id == "system:continuation"
    assert queued.metadata[INTERNAL_CONTINUATION_META] is True
    assert "Finish the long goal." in queued.content

    session = loop.sessions.get_or_create("feishu:c-auto")
    assert [
        {k: v for k, v in m.items() if k in {"role", "content"}}
        for m in session.messages
    ] == [{"role": "user", "content": "start the goal"}]

    second = await loop._process_message(queued, pending_queue=asyncio.Queue())

    assert second is not None
    assert second.content == "done"
    session = loop.sessions.get_or_create("feishu:c-auto")
    assert [
        {k: v for k, v in m.items() if k in {"role", "content"}}
        for m in session.messages
    ] == [
        {"role": "user", "content": "start the goal"},
        {"role": "assistant", "content": "done"},
    ]


@pytest.mark.asyncio
async def test_internal_continuation_preserves_streaming_route_metadata(
    tmp_path: Path,
) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    session = loop.sessions.get_or_create("feishu:c-stream")
    session.metadata[GOAL_STATE_KEY] = {
        "status": "active",
        "objective": "Finish the streamed long goal.",
    }
    loop.sessions.save(session)

    calls = 0

    async def fake_run_agent_loop(initial_messages, *, on_stream=None, on_stream_end=None, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return (
                "paused",
                [],
                [*initial_messages, {"role": "assistant", "content": "paused"}],
                    "max_iterations",
                    False,
                )
        assert on_stream is not None
        assert on_stream_end is not None
        await on_stream("done")
        await on_stream_end(resuming=False)
        return (
            "done",
            [],
            [*initial_messages, {"role": "assistant", "content": "done"}],
            "completed",
            False,
        )

    loop._run_agent_loop = fake_run_agent_loop  # type: ignore[method-assign]

    await loop._dispatch(InboundMessage(
        channel="feishu",
        sender_id="u1",
        chat_id="c-stream",
        content="start the goal",
        metadata={
            "_wants_stream": True,
            "message_id": "om_001",
            "origin_message_id": "root_001",
            "_stream_id": "old-stream",
        },
    ))

    assert loop.bus.outbound_size == 0
    queued = await asyncio.wait_for(loop.bus.consume_inbound(), timeout=0.5)
    assert queued.metadata[INTERNAL_CONTINUATION_META] is True
    assert queued.metadata["_wants_stream"] is True
    assert queued.metadata["message_id"] == "om_001"
    assert queued.metadata["origin_message_id"] == "root_001"
    assert "_stream_id" not in queued.metadata

    await loop._dispatch(queued)

    outbound = []
    while loop.bus.outbound_size:
        outbound.append(await loop.bus.consume_outbound())
    deltas = [m for m in outbound if m.metadata.get("_stream_delta")]
    ends = [m for m in outbound if m.metadata.get("_stream_end")]
    streamed_markers = [m for m in outbound if m.metadata.get("_streamed")]

    assert [m.content for m in deltas] == ["done"]
    assert len(ends) == 1
    assert ends[0].metadata["_resuming"] is False
    assert ends[0].metadata["message_id"] == "om_001"
    assert ends[0].metadata["origin_message_id"] == "root_001"
    assert isinstance(ends[0].metadata.get("_stream_id"), str)
    assert streamed_markers and streamed_markers[-1].content == "done"


@pytest.mark.asyncio
async def test_websocket_internal_continuation_keeps_single_visible_run(
    tmp_path: Path,
) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    session = loop.sessions.get_or_create("websocket:c-auto")
    session.metadata[GOAL_STATE_KEY] = {
        "status": "active",
        "objective": "Finish the long goal.",
    }
    loop.sessions.save(session)

    calls = 0

    async def fake_run_agent_loop(initial_messages, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return (
                "paused",
                [],
                [*initial_messages, {"role": "assistant", "content": "paused"}],
                    "max_iterations",
                    False,
                )
        return (
            "done",
            [],
            [*initial_messages, {"role": "assistant", "content": "done"}],
            "completed",
            False,
        )

    loop._run_agent_loop = fake_run_agent_loop  # type: ignore[method-assign]

    await loop._dispatch(InboundMessage(
        channel="websocket",
        sender_id="u1",
        chat_id="c-auto",
        content="start the goal",
        metadata={"webui": True},
    ))

    first_outbound = []
    while loop.bus.outbound_size:
        first_outbound.append(await loop.bus.consume_outbound())
    first_statuses = [m.metadata for m in first_outbound if m.metadata.get("_goal_status")]
    assert [m["goal_status"] for m in first_statuses] == ["running"]
    assert not [m for m in first_outbound if m.metadata.get("_turn_end")]
    started_at = first_statuses[0]["started_at"]

    queued = await asyncio.wait_for(loop.bus.consume_inbound(), timeout=0.5)
    assert queued.metadata[INTERNAL_CONTINUATION_META] is True
    assert queued.metadata[INTERNAL_CONTINUATION_RUN_STARTED_AT_META] == started_at

    await loop._dispatch(queued)

    second_outbound = []
    while loop.bus.outbound_size:
        second_outbound.append(await loop.bus.consume_outbound())
    second_statuses = [m.metadata for m in second_outbound if m.metadata.get("_goal_status")]
    assert [m["goal_status"] for m in second_statuses] == ["running", "idle"]
    assert second_statuses[0]["started_at"] == started_at
    turn_end = [m for m in second_outbound if m.metadata.get("_turn_end")]
    assert len(turn_end) == 1
    assert isinstance(turn_end[0].metadata.get("latency_ms"), int)


@pytest.mark.asyncio
async def test_process_message_uses_context_chat_id_for_runtime_prompt(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop.context.build_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "runtime + hello"},
        ]
    )
    loop._run_agent_loop = AsyncMock(return_value=(  # type: ignore[method-assign]
        "done",
        [],
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "runtime + hello"},
            {"role": "assistant", "content": "done"},
        ],
        "stop",
        False,
    ))

    result = await loop._process_message(
        InboundMessage(
            channel="discord",
            sender_id="u1",
            chat_id="thread-777",
            content="hello",
            metadata={"context_chat_id": "parent-456"},
            session_key_override="discord:parent-456:thread:thread-777",
        )
    )

    assert result is not None
    assert result.chat_id == "thread-777"
    assert loop.context.build_messages.call_args.kwargs["chat_id"] == "parent-456"
    assert loop._run_agent_loop.call_args.kwargs["chat_id"] == "thread-777"


@pytest.mark.asyncio
async def test_process_message_uses_explicit_session_metadata_for_goal_context(
    tmp_path: Path,
) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    chat_session = loop.sessions.get_or_create("websocket:chat-with-goal")
    chat_session.metadata[GOAL_STATE_KEY] = {
        "status": "active",
        "objective": "This chat goal must not leak into system.",
    }
    loop.sessions.save(chat_session)
    system_session = loop.sessions.get_or_create("system")
    system_session.metadata = {}
    loop.sessions.save(system_session)

    loop.context.build_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "runtime + system"},
        ]
    )
    loop._run_agent_loop = AsyncMock(return_value=(  # type: ignore[method-assign]
        "ok",
        [],
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "runtime + system"},
            {"role": "assistant", "content": "ok"},
        ],
        "stop",
        False,
    ))

    result = await loop._process_message(
        InboundMessage(
            channel="websocket",
            sender_id="system",
            chat_id="chat-with-goal",
            content="system work",
        ),
        session_key="system",
    )

    assert result is not None
    assert result.content == "ok"
    kwargs = loop.context.build_messages.call_args.kwargs
    assert kwargs["chat_id"] == "chat-with-goal"
    assert kwargs["session_metadata"] is system_session.metadata
    assert GOAL_STATE_KEY not in kwargs["session_metadata"]


def test_set_tool_context_uses_effective_key_for_spawn_tool(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    spawn_tool = loop.tools.get("spawn")
    assert spawn_tool is not None

    loop._set_tool_context(
        "discord",
        "thread-777",
        session_key="discord:parent-456:thread:thread-777",
    )

    assert spawn_tool._origin_channel.get() == "discord"  # type: ignore[attr-defined]
    assert spawn_tool._origin_chat_id.get() == "thread-777"  # type: ignore[attr-defined]
    assert spawn_tool._session_key.get() == "discord:parent-456:thread:thread-777"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_next_turn_after_crash_closes_pending_user_turn_before_new_input(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop.provider.chat_with_retry = AsyncMock(return_value=MagicMock())  # unused because _run_agent_loop is stubbed

    session = loop.sessions.get_or_create("feishu:c3")
    session.add_message("user", "old question")
    session.metadata[AgentLoop._PENDING_USER_TURN_KEY] = True
    loop.sessions.save(session)

    loop._run_agent_loop = AsyncMock(return_value=(
        "new answer",
        None,
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "Error: Task interrupted before a response was generated."},
            {"role": "user", "content": "new question"},
            {"role": "assistant", "content": "new answer"},
        ],
        "stop",
        False,
    ))  # type: ignore[method-assign]

    result = await loop._process_message(
        InboundMessage(channel="feishu", sender_id="u1", chat_id="c3", content="new question")
    )

    assert result is not None
    assert result.content == "new answer"
    session = loop.sessions.get_or_create("feishu:c3")
    assert [
        {k: v for k, v in m.items() if k in {"role", "content"}}
        for m in session.messages
    ] == [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "Error: Task interrupted before a response was generated."},
        {"role": "user", "content": "new question"},
        {"role": "assistant", "content": "new answer"},
    ]
    assert AgentLoop._PENDING_USER_TURN_KEY not in session.metadata


@pytest.mark.asyncio
async def test_stop_preserves_runtime_checkpoint_for_next_turn(tmp_path: Path) -> None:
    from blackcat.command.builtin import cmd_stop
    from blackcat.command.router import CommandContext

    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    checkpoint_saved = asyncio.Event()

    async def interrupted_run_agent_loop(_initial_messages, *, session=None, **_kwargs):
        assert session is not None
        loop._set_runtime_checkpoint(
            session,
            {
                "assistant_message": {
                    "role": "assistant",
                    "content": "working",
                    "tool_calls": [
                        {
                            "id": "call_done",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        },
                        {
                            "id": "call_pending",
                            "type": "function",
                            "function": {"name": "exec", "arguments": "{}"},
                        },
                    ],
                },
                "completed_tool_results": [
                    {
                        "role": "tool",
                        "tool_call_id": "call_done",
                        "name": "read_file",
                        "content": "ok",
                    }
                ],
                "pending_tool_calls": [
                    {
                        "id": "call_pending",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    }
                ],
            },
        )
        checkpoint_saved.set()
        await asyncio.Event().wait()

    loop._run_agent_loop = interrupted_run_agent_loop  # type: ignore[method-assign]

    first_msg = InboundMessage(channel="feishu", sender_id="u1", chat_id="c4", content="keep progress")
    task = asyncio.create_task(loop._process_message(first_msg))
    loop._active_tasks[first_msg.session_key] = [task]
    await asyncio.wait_for(checkpoint_saved.wait(), timeout=1.0)

    stop_msg = InboundMessage(channel="feishu", sender_id="u1", chat_id="c4", content="/stop")
    stop_ctx = CommandContext(msg=stop_msg, session=None, key=stop_msg.session_key, raw="/stop", loop=loop)
    stop_result = await cmd_stop(stop_ctx)

    assert "Stopped 1 task" in stop_result.content
    assert task.done()

    loop.sessions.invalidate("feishu:c4")
    interrupted = loop.sessions.get_or_create("feishu:c4")
    assert interrupted.metadata.get(AgentLoop._PENDING_USER_TURN_KEY) is True
    assert interrupted.metadata.get(AgentLoop._RUNTIME_CHECKPOINT_KEY) is not None

    async def resumed_run_agent_loop(initial_messages, **_kwargs):
        return (
            "next answer",
            None,
            [*initial_messages, {"role": "assistant", "content": "next answer"}],
            "stop",
            False,
        )

    loop._run_agent_loop = resumed_run_agent_loop  # type: ignore[method-assign]
    result = await loop._process_message(
        InboundMessage(channel="feishu", sender_id="u1", chat_id="c4", content="continue here")
    )

    assert result is not None
    assert result.content == "next answer"

    session = loop.sessions.get_or_create("feishu:c4")
    assert [
        {k: v for k, v in m.items() if k in {"role", "content", "tool_call_id", "name"}}
        for m in session.messages
    ] == [
        {"role": "user", "content": "keep progress"},
        {"role": "assistant", "content": "working"},
        {"role": "tool", "tool_call_id": "call_done", "name": "read_file", "content": "ok"},
        {
            "role": "tool",
            "tool_call_id": "call_pending",
            "name": "exec",
            "content": "Error: Task interrupted before this tool finished.",
        },
        {"role": "user", "content": "continue here"},
        {"role": "assistant", "content": "next answer"},
    ]
    assert AgentLoop._PENDING_USER_TURN_KEY not in session.metadata
    assert AgentLoop._RUNTIME_CHECKPOINT_KEY not in session.metadata


@pytest.mark.asyncio
async def test_system_subagent_followup_is_persisted_before_prompt_assembly(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    session.add_message("user", "question")
    session.add_message("assistant", "working")
    loop.sessions.save(session)

    seen: dict[str, list[dict]] = {}

    async def fake_run_agent_loop(initial_messages, **_kwargs):
        seen["initial_messages"] = initial_messages
        return (
            "done",
            [],
            [*initial_messages, {"role": "assistant", "content": "done"}],
            "stop",
            False,
        )

    loop._run_agent_loop = fake_run_agent_loop  # type: ignore[method-assign]

    await loop._process_message(
        InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="cli:test",
            content="subagent result",
            metadata={"subagent_task_id": "sub-1"},
        )
    )

    non_system = [m for m in seen["initial_messages"] if m.get("role") != "system"]
    assert "question" in non_system[0]["content"]
    assert "working" in non_system[1]["content"]
    # User turns carry the timestamp prefix so the model can reason about
    # relative time. Assistant turns do NOT, otherwise the model treats those
    # past replies as in-context examples and starts its own outputs with
    # ``[Message Time: ...]`` (which then leaks back to the user).
    assert "[Message Time:" in non_system[0]["content"]
    assert "[Message Time:" not in non_system[1]["content"]
    assert non_system[2]["content"].count("subagent result") == 1
    assert "Current Time:" in non_system[2]["content"]

    loop.sessions.invalidate("cli:test")
    persisted = loop.sessions.get_or_create("cli:test")
    assert [
        {k: v for k, v in m.items() if k in {"role", "content", "injected_event", "subagent_task_id"}}
        for m in persisted.messages
    ] == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "working"},
        {
            "role": "assistant",
            "content": "subagent result",
            "injected_event": "subagent_result",
            "subagent_task_id": "sub-1",
        },
        {"role": "assistant", "content": "done"},
    ]


@pytest.mark.asyncio
async def test_multiple_subagent_followups_all_persist_as_standalone_history(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    async def fake_run_agent_loop(initial_messages, **_kwargs):
        return (
            "ack",
            [],
            [*initial_messages, {"role": "assistant", "content": "ack"}],
            "stop",
            False,
        )

    loop._run_agent_loop = fake_run_agent_loop  # type: ignore[method-assign]

    for idx in range(3):
        await loop._process_message(
            InboundMessage(
                channel="system",
                sender_id="subagent",
                chat_id="cli:multi",
                content=f"subagent result {idx}",
                metadata={"subagent_task_id": f"sub-{idx}"},
            )
        )

    loop.sessions.invalidate("cli:multi")
    persisted = loop.sessions.get_or_create("cli:multi")
    followups = [m for m in persisted.messages if m.get("injected_event") == "subagent_result"]
    assert [m["content"] for m in followups] == [
        "subagent result 0",
        "subagent result 1",
        "subagent result 2",
    ]


def test_prompt_merge_does_not_replace_standalone_subagent_history_entry(tmp_path: Path) -> None:
    loop = _mk_loop()
    session = Session(key="cli:merge")
    session.add_message("assistant", "previous assistant")

    inserted = loop._persist_subagent_followup(
        session,
        InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="cli:merge",
            content="subagent result",
            metadata={"subagent_task_id": "sub-1"},
        ),
    )

    assert inserted is True

    builder = ContextBuilder(tmp_path)
    projected = builder.build_messages(
        history=session.get_history(max_messages=0),
        current_message="",
        current_role="assistant",
        channel="cli",
        chat_id="merge",
    )

    non_system = [m for m in projected if m.get("role") != "system"]
    assert len(non_system) == 2
    assert "subagent result" in non_system[-1]["content"]
    assert session.messages[-1]["content"] == "subagent result"
    assert session.messages[-1]["injected_event"] == "subagent_result"


def test_subagent_followup_dedupes_by_task_id() -> None:
    loop = _mk_loop()
    session = Session(key="cli:dedupe")
    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="cli:dedupe",
        content="subagent result",
        metadata={"subagent_task_id": "sub-1"},
    )

    assert loop._persist_subagent_followup(session, msg) is True
    assert loop._persist_subagent_followup(session, msg) is False
    assert len(session.messages) == 1


def test_subagent_followup_skips_empty_content() -> None:
    loop = _mk_loop()
    session = Session(key="cli:empty")
    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="cli:empty",
        content="",
        metadata={"subagent_task_id": "sub-empty"},
    )

    assert loop._persist_subagent_followup(session, msg) is False
    assert session.messages == []


def test_set_tool_context_passes_thread_session_key_to_spawn(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)

    loop._set_tool_context(
        "slack",
        "C123",
        message_id="msg-123",
        metadata={"slack": {"thread_ts": "1700.42", "channel_type": "channel"}},
        session_key="slack:C123:1700.42",
    )

    spawn_tool = loop.tools.get("spawn")
    assert spawn_tool is not None
    assert spawn_tool._session_key.get() == "slack:C123:1700.42"
    assert spawn_tool._origin_message_id.get() == "msg-123"


@pytest.mark.asyncio
async def test_system_subagent_followup_uses_thread_session_and_slack_metadata(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    thread_session = loop.sessions.get_or_create("slack:C123:1700.42")
    thread_session.add_message("user", "thread question")
    loop.sessions.save(thread_session)

    seen: dict[str, list[dict]] = {}

    async def fake_run_agent_loop(initial_messages, **_kwargs):
        seen["initial_messages"] = initial_messages
        return (
            "done",
            [],
            [*initial_messages, {"role": "assistant", "content": "done"}],
            "stop",
            False,
        )

    loop._run_agent_loop = fake_run_agent_loop  # type: ignore[method-assign]

    outbound = await loop._process_message(
        InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="slack:C123",
            content="subagent result",
            session_key_override="slack:C123:1700.42",
            metadata={"subagent_task_id": "sub-1", "origin_message_id": "msg-123"},
        )
    )

    assert outbound is not None
    assert outbound.channel == "slack"
    assert outbound.chat_id == "C123"
    assert outbound.metadata == {
        "slack": {"thread_ts": "1700.42"},
        "origin_message_id": "msg-123",
    }
    assert "thread question" in seen["initial_messages"][1]["content"]

    loop.sessions.invalidate("slack:C123:1700.42")
    persisted = loop.sessions.get_or_create("slack:C123:1700.42")
    assert any(m.get("subagent_task_id") == "sub-1" for m in persisted.messages)


@pytest.mark.asyncio
async def test_turn_after_unanswered_user_keeps_tool_call_pairing(tmp_path: Path) -> None:
    """Regression for #4006: when history ends with a user message,
    ``build_messages`` merges the new user message into it, shrinking the
    prompt prefix by one. The save boundary must follow, or the first
    new-turn assistant message (carrying tool_calls) is cut from
    persistence and its tool results are orphaned."""
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("feishu:c-merge")
    session.add_message("user", "earlier question that never got an answer")
    loop.sessions.save(session)

    async def fake_run_agent_loop(initial_messages, **_kwargs):
        # The merge branch collapsed the current user message into the
        # history tail: the prompt prefix is [system, merged-user].
        assert [m["role"] for m in initial_messages] == ["system", "user"]
        return (
            "done",
            [],
            [
                *initial_messages,
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call_ls",
                        "type": "function",
                        "function": {"name": "exec", "arguments": '{"command": "ls"}'},
                    }],
                },
                {"role": "tool", "tool_call_id": "call_ls", "name": "exec", "content": "file.txt"},
                {"role": "assistant", "content": "done"},
            ],
            "stop",
            False,
        )

    loop._run_agent_loop = fake_run_agent_loop  # type: ignore[method-assign]

    result = await loop._process_message(
        InboundMessage(
            channel="feishu", sender_id="u1", chat_id="c-merge", content="and another thing"
        )
    )

    assert result is not None
    loop.sessions.invalidate("feishu:c-merge")
    persisted = loop.sessions.get_or_create("feishu:c-merge")

    declared: set[str] = set()
    for message in persisted.messages:
        if message.get("role") == "assistant":
            declared.update(
                str(tc["id"]) for tc in message.get("tool_calls") or [] if tc.get("id")
            )
        if message.get("role") == "tool":
            assert str(message.get("tool_call_id")) in declared, (
                f"orphaned tool result {message.get('tool_call_id')!r}: "
                f"{[m.get('role') for m in persisted.messages]}"
            )
    assert [m["role"] for m in persisted.messages] == [
        "user", "user", "assistant", "tool", "assistant",
    ]


def test_save_turn_keeps_placeholder_for_empty_tool_result_blocks() -> None:
    # Dropping the whole tool message would leave the assistant tool_call
    # without a result, which strict APIs reject as firmly as orphans.
    loop = _mk_loop()
    session = Session(key="test:empty-tool-blocks")

    loop._save_turn(
        session,
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_empty",
                    "type": "function",
                    "function": {"name": "exec", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": "call_empty", "name": "exec", "content": []},
        ],
        skip=0,
    )

    assert [m["role"] for m in session.messages] == ["assistant", "tool"]
    assert session.messages[1]["content"] == [
        {"type": "text", "text": "[tool result omitted during persistence]"}
    ]
