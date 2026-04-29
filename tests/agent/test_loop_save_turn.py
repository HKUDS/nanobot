import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.session.manager import Session


def _mk_loop() -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    from nanobot.config.schema import AgentDefaults

    loop.max_tool_result_chars = AgentDefaults().max_tool_result_chars
    return loop


def _make_full_loop(tmp_path: Path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")


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
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}, "_meta": {"path": "/media/feishu/photo.jpg"}},
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
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image]"}]


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
    from nanobot.command.builtin import cmd_stop
    from nanobot.command.router import CommandContext

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
        metadata={"slack": {"thread_ts": "1700.42", "channel_type": "channel"}},
        session_key="slack:C123:1700.42",
    )

    spawn_tool = loop.tools.get("spawn")
    assert spawn_tool is not None
    assert spawn_tool._session_key.get() == "slack:C123:1700.42"


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
            metadata={"subagent_task_id": "sub-1"},
        )
    )

    assert outbound is not None
    assert outbound.channel == "slack"
    assert outbound.chat_id == "C123"
    assert outbound.metadata == {"slack": {"thread_ts": "1700.42"}}
    assert "thread question" in seen["initial_messages"][1]["content"]

    loop.sessions.invalidate("slack:C123:1700.42")
    persisted = loop.sessions.get_or_create("slack:C123:1700.42")
    assert any(m.get("subagent_task_id") == "sub-1" for m in persisted.messages)
