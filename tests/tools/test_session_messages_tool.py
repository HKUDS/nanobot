import asyncio
import json
from pathlib import Path
from typing import Callable

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.session_messages import (
    ListSessionsTool,
    SendSessionMessageTool,
    SessionMessageError,
)
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import session_handle_for_key
from nanobot.session.session_messages import (
    SESSION_MESSAGE_METADATA_KEY,
    session_message_envelope,
)


def _persist(manager: SessionManager, *keys: str) -> None:
    for key in keys:
        manager.save(manager.get_or_create(key))


class _Timer:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class _Scheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[float, _Timer]] = []

    def __call__(self, delay: float, callback: Callable[[], None]) -> _Timer:
        timer = _Timer(callback)
        self.calls.append((delay, timer))
        return timer


def test_config_and_tool_schema_keep_only_the_basic_reply_contract(
    tmp_path: Path,
) -> None:
    tool = SendSessionMessageTool(
        sessions=SessionManager(tmp_path),
        bus=MessageBus(),
    )

    assert ToolsConfig().max_session_messages_per_minute == 6
    assert tool.parameters["required"] == ["to", "content", "expect_reply"]
    timeout = tool.parameters["properties"]["reply_timeout_seconds"]
    assert (timeout["minimum"], timeout["maximum"]) == (5, 60)


@pytest.mark.asyncio
async def test_list_sessions_includes_all_persisted_channels_except_current(
    tmp_path: Path,
) -> None:
    sessions = SessionManager(tmp_path)
    _persist(sessions, "websocket:current", "telegram:other", "slack:team")
    tool = ListSessionsTool(sessions)

    with request_context(RequestContext(
        channel="websocket",
        chat_id="current",
        session_key="websocket:current",
    )):
        result = json.loads(await tool.execute())

    assert set(result) == {
        f"@{session_handle_for_key('telegram:other').name}",
        f"@{session_handle_for_key('slack:team').name}",
    }


@pytest.mark.asyncio
async def test_send_publishes_user_input_to_the_existing_target(
    tmp_path: Path,
) -> None:
    sessions = SessionManager(tmp_path)
    _persist(sessions, "websocket:source", "telegram:target")
    bus = MessageBus()
    tool = SendSessionMessageTool(sessions=sessions, bus=bus)
    target = session_handle_for_key("telegram:target")

    sent_to = await tool.enqueue(
        source_session_key="websocket:source",
        target_handle=f"@{target.name}",
        content="Please review this.",
        expect_reply=False,
    )
    inbound = await bus.consume_inbound()
    envelope = session_message_envelope(inbound.metadata)

    assert sent_to == f"@{target.name}"
    assert inbound.channel == "system"
    assert inbound.chat_id == "telegram:target"
    assert inbound.session_key_override == "telegram:target"
    assert inbound.is_user_input
    assert inbound.content == "Please review this."
    assert envelope is not None
    assert envelope["source_session_key"] == "websocket:source"
    assert envelope["target_session_key"] == "telegram:target"
    assert inbound.metadata == {SESSION_MESSAGE_METADATA_KEY: envelope}


@pytest.mark.asyncio
async def test_send_fails_when_target_does_not_exist(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    _persist(sessions, "websocket:source")
    bus = MessageBus()
    tool = SendSessionMessageTool(sessions=sessions, bus=bus)

    with pytest.raises(SessionMessageError, match="was not found"):
        await tool.enqueue(
            source_session_key="websocket:source",
            target_handle="@missing-0000000000",
            content="Hello",
            expect_reply=False,
        )

    assert bus.inbound.empty()


@pytest.mark.asyncio
async def test_rate_limit_is_per_source_session_and_uses_a_rolling_minute(
    tmp_path: Path,
) -> None:
    sessions = SessionManager(tmp_path)
    _persist(sessions, "websocket:a", "websocket:b", "websocket:target")
    now = 0.0
    tool = SendSessionMessageTool(
        sessions=sessions,
        bus=MessageBus(),
        max_messages_per_minute=1,
        clock=lambda: now,
    )
    target = session_handle_for_key("websocket:target").name

    await tool.enqueue(
        source_session_key="websocket:a",
        target_handle=target,
        content="A1",
        expect_reply=False,
    )
    await tool.enqueue(
        source_session_key="websocket:b",
        target_handle=target,
        content="B1",
        expect_reply=False,
    )
    with pytest.raises(SessionMessageError, match="rate limit"):
        await tool.enqueue(
            source_session_key="websocket:a",
            target_handle=target,
            content="A2",
            expect_reply=False,
        )

    now = 61.0
    await tool.enqueue(
        source_session_key="websocket:a",
        target_handle=target,
        content="A3",
        expect_reply=False,
    )


@pytest.mark.asyncio
async def test_reply_timeout_injects_a_user_input_back_into_the_source(
    tmp_path: Path,
) -> None:
    sessions = SessionManager(tmp_path)
    _persist(sessions, "websocket:source", "websocket:target")
    bus = MessageBus()
    scheduler = _Scheduler()
    tool = SendSessionMessageTool(
        sessions=sessions,
        bus=bus,
        schedule_later=scheduler,
    )
    target = session_handle_for_key("websocket:target")

    await tool.enqueue(
        source_session_key="websocket:source",
        target_handle=target.name,
        content="Question",
        expect_reply=True,
        reply_timeout_seconds=5,
    )
    await bus.consume_inbound()
    delay, timer = scheduler.calls[0]

    assert delay == 5
    timer.fire()
    await asyncio.sleep(0)
    timeout = await bus.consume_inbound()
    assert timeout.chat_id == "websocket:source"
    assert timeout.is_user_input
    assert timeout.content == f"No reply from @{target.name} after 5 seconds."


@pytest.mark.asyncio
async def test_reverse_message_cancels_the_pending_reply_timeout(
    tmp_path: Path,
) -> None:
    sessions = SessionManager(tmp_path)
    _persist(sessions, "websocket:source", "websocket:target")
    bus = MessageBus()
    scheduler = _Scheduler()
    tool = SendSessionMessageTool(
        sessions=sessions,
        bus=bus,
        schedule_later=scheduler,
    )
    source = session_handle_for_key("websocket:source")
    target = session_handle_for_key("websocket:target")

    await tool.enqueue(
        source_session_key=source.session_key,
        target_handle=target.name,
        content="Question",
        expect_reply=True,
        reply_timeout_seconds=5,
    )
    await tool.enqueue(
        source_session_key=target.session_key,
        target_handle=source.name,
        content="Answer",
        expect_reply=False,
    )

    assert scheduler.calls[0][1].cancelled
