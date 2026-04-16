import json
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


def _cross_channel_messages(
    source_channel: str = "websocket",
    source_chat_id: str = "ws-uuid-123",
    target_channel: str = "feishu",
    target_chat_id: str = "ou_abc123",
) -> list[dict]:
    """Build a message list with a cross-channel message tool call."""
    return [
        {"role": "user", "content": "send report to feishu"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_x1",
                    "type": "function",
                    "function": {
                        "name": "message",
                        "arguments": json.dumps({
                            "content": "Report: audit complete",
                            "channel": target_channel,
                            "chat_id": target_chat_id,
                        }),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_x1",
            "name": "message",
            "content": f"Message sent to {target_channel}:{target_chat_id}",
        },
        {"role": "assistant", "content": "Done, sent to feishu."},
    ]


def test_cross_channel_message_persisted_in_target_session(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    source_key = "websocket:ws-uuid-123"
    target_key = "feishu:ou_abc123"

    # Pre-create the target session (simulate an existing feishu conversation)
    target_session = loop.sessions.get_or_create(target_key)
    target_session.add_message("user", "hello from feishu")
    loop.sessions.save(target_session)

    source_session = loop.sessions.get_or_create(source_key)
    msgs = _cross_channel_messages()
    loop._save_turn(source_session, msgs, skip=1)  # skip user message

    # Source session has its own messages
    source_session = loop.sessions.get_or_create(source_key)
    assert len(source_session.messages) >= 2  # assistant + tool + final

    # Target session now has the cross-channel message appended
    loop.sessions.invalidate(target_key)
    target = loop.sessions.get_or_create(target_key)
    cross_msg = [m for m in target.messages if m.get("_cross_channel")]
    assert len(cross_msg) == 1
    assert cross_msg[0]["content"] == "Report: audit complete"
    assert cross_msg[0]["role"] == "assistant"


def test_cross_channel_same_session_not_duplicated(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    key = "feishu:ou_same"

    session = loop.sessions.get_or_create(key)
    # message tool call targeting the same session — should NOT create a duplicate
    msgs = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_s1",
                    "type": "function",
                    "function": {
                        "name": "message",
                        "arguments": json.dumps({
                            "content": "same channel msg",
                            "channel": "feishu",
                            "chat_id": "ou_same",
                        }),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_s1", "name": "message", "content": "ok"},
    ]
    loop._save_turn(session, msgs, skip=1)

    # No _cross_channel entries should exist
    assert all(not m.get("_cross_channel") for m in session.messages)


def test_cross_channel_target_session_not_exist_creates_session(tmp_path: Path) -> None:
    """When the target session does not exist yet, get_or_create will create it
    and the cross-channel message should still be persisted."""
    loop = _make_full_loop(tmp_path)
    source_session = loop.sessions.get_or_create("websocket:ws-xyz")

    msgs = _cross_channel_messages(
        target_channel="feishu", target_chat_id="ou_nonexistent"
    )
    loop._save_turn(source_session, msgs, skip=1)

    # Target session is now auto-created with the cross-channel message
    target = loop.sessions.get_or_create("feishu:ou_nonexistent")
    cross_msgs = [m for m in target.messages if m.get("_cross_channel")]
    assert len(cross_msgs) == 1
    assert cross_msgs[0]["content"] == "Report: audit complete"


def test_cross_channel_persists_media_attachments(tmp_path: Path) -> None:
    """When the message tool call includes media, the cross-channel entry
    should preserve the media paths so the target session has full context."""
    loop = _make_full_loop(tmp_path)
    source_key = "websocket:ws-media"
    target_key = "telegram:tg_user1"

    target_session = loop.sessions.get_or_create(target_key)
    target_session.add_message("user", "waiting for report")
    loop.sessions.save(target_session)

    source_session = loop.sessions.get_or_create(source_key)
    msgs = [
        {"role": "user", "content": "send chart to telegram"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_m1",
                    "type": "function",
                    "function": {
                        "name": "message",
                        "arguments": json.dumps({
                            "content": "Here is the chart",
                            "channel": "telegram",
                            "chat_id": "tg_user1",
                            "media": ["/tmp/chart.png", "/tmp/data.csv"],
                        }),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_m1",
            "name": "message",
            "content": "Message sent to telegram:tg_user1",
        },
    ]
    loop._save_turn(source_session, msgs, skip=1)

    loop.sessions.invalidate(target_key)
    target = loop.sessions.get_or_create(target_key)
    cross_msgs = [m for m in target.messages if m.get("_cross_channel")]
    assert len(cross_msgs) == 1
    assert cross_msgs[0]["content"] == "Here is the chart"
    assert cross_msgs[0]["_media"] == ["/tmp/chart.png", "/tmp/data.csv"]


def test_cross_channel_records_source_session(tmp_path: Path) -> None:
    """Cross-channel entries should include _source_session for traceability."""
    loop = _make_full_loop(tmp_path)
    source_key = "cron:heartbeat"
    target_key = "feishu:ou_trace"

    target_session = loop.sessions.get_or_create(target_key)
    target_session.add_message("user", "hi")
    loop.sessions.save(target_session)

    source_session = loop.sessions.get_or_create(source_key)
    msgs = _cross_channel_messages(
        source_channel="cron", source_chat_id="heartbeat",
        target_channel="feishu", target_chat_id="ou_trace",
    )
    loop._save_turn(source_session, msgs, skip=1)

    loop.sessions.invalidate(target_key)
    target = loop.sessions.get_or_create(target_key)
    cross_msgs = [m for m in target.messages if m.get("_cross_channel")]
    assert len(cross_msgs) == 1
    assert cross_msgs[0]["_source_session"] == "cron:heartbeat"


def test_cross_channel_media_only_no_content(tmp_path: Path) -> None:
    """A message with media but empty content should still be persisted."""
    loop = _make_full_loop(tmp_path)
    target_key = "discord:ch_img"

    target_session = loop.sessions.get_or_create(target_key)
    loop.sessions.save(target_session)

    source_session = loop.sessions.get_or_create("websocket:ws-img")
    msgs = [
        {"role": "user", "content": "send image"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_img",
                    "type": "function",
                    "function": {
                        "name": "message",
                        "arguments": json.dumps({
                            "content": "",
                            "channel": "discord",
                            "chat_id": "ch_img",
                            "media": ["/tmp/photo.jpg"],
                        }),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_img", "name": "message", "content": "ok"},
    ]
    loop._save_turn(source_session, msgs, skip=1)

    loop.sessions.invalidate(target_key)
    target = loop.sessions.get_or_create(target_key)
    cross_msgs = [m for m in target.messages if m.get("_cross_channel")]
    assert len(cross_msgs) == 1
    assert cross_msgs[0]["_media"] == ["/tmp/photo.jpg"]


def test_cross_channel_non_message_tools_ignored(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    source_session = loop.sessions.get_or_create("websocket:ws-abc")
    target_session = loop.sessions.get_or_create("feishu:ou_tgt")
    target_session.add_message("user", "hi")
    loop.sessions.save(target_session)

    msgs = [
        {"role": "user", "content": "do stuff"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_e1",
                    "type": "function",
                    "function": {
                        "name": "exec",
                        "arguments": json.dumps({"command": "echo hi"}),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_e1", "name": "exec", "content": "hi"},
    ]
    loop._save_turn(source_session, msgs, skip=1)

    # exec tool should NOT produce cross-channel entries
    target = loop.sessions.get_or_create("feishu:ou_tgt")
    cross_msgs = [m for m in target.messages if m.get("_cross_channel")]
    assert len(cross_msgs) == 0


def test_cross_channel_get_history_annotates_provenance(tmp_path: Path) -> None:
    """get_history() should prefix cross-channel messages with source info
    so the LLM knows where the message came from."""
    loop = _make_full_loop(tmp_path)
    target_key = "feishu:ou_hist"

    target_session = loop.sessions.get_or_create(target_key)
    target_session.add_message("user", "hello")
    # Simulate a cross-channel entry as _persist_cross_channel_calls would create
    target_session.messages.append({
        "role": "assistant",
        "content": "Daily report ready",
        "_cross_channel": True,
        "_source_session": "cron:daily-report",
    })
    loop.sessions.save(target_session)

    loop.sessions.invalidate(target_key)
    target = loop.sessions.get_or_create(target_key)
    history = target.get_history()

    # Find the annotated message
    annotated = [m for m in history if "cron:daily-report" in m.get("content", "")]
    assert len(annotated) == 1
    assert annotated[0]["content"] == "[Sent from cron:daily-report] Daily report ready"
    # Internal metadata keys should NOT leak into the history output
    assert "_cross_channel" not in annotated[0]
    assert "_source_session" not in annotated[0]
