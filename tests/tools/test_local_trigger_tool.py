from pathlib import Path
from unittest.mock import MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.agent.tools.local_trigger import LocalTriggerTool
from nanobot.bus.queue import MessageBus
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.triggers.local_store import LocalTriggerStore


def _context(*, session_key: str = "websocket:chat-1") -> RequestContext:
    return RequestContext(
        channel="websocket",
        chat_id="chat-1",
        session_key=session_key,
        sender_id="user-1",
        metadata={"thread": "main"},
    )


def test_local_trigger_tool_only_enabled_with_store(tmp_path: Path) -> None:
    without_store = ToolContext(config=MagicMock(), workspace=str(tmp_path))
    assert LocalTriggerTool.enabled(without_store) is False

    store = LocalTriggerStore(tmp_path)
    with_store = ToolContext(
        config=MagicMock(),
        workspace=str(tmp_path),
        local_trigger_store=store,
    )
    assert LocalTriggerTool.enabled(with_store) is True
    assert isinstance(LocalTriggerTool.create(with_store), LocalTriggerTool)


async def test_local_trigger_tool_creates_and_lists_current_session(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    tool = LocalTriggerTool(store)

    with request_context(_context()):
        created = await tool.execute(action="create", name="release monitor")
        listed = await tool.execute(action="list")

    trigger = store.list_for_session("websocket:chat-1")[0]
    assert trigger.name == "release monitor"
    assert trigger.channel == "websocket"
    assert trigger.chat_id == "chat-1"
    assert trigger.origin_metadata == {"thread": "main"}
    assert f'nanobot trigger {trigger.id} "message"' in created
    assert "does not poll or schedule" in created
    assert trigger.id in listed


async def test_local_trigger_tool_uses_conversation_key_in_unified_mode(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    tool = LocalTriggerTool(store)

    with request_context(_context(session_key=UNIFIED_SESSION_KEY)):
        await tool.execute(action="create", name="unified release monitor")

    trigger = store.list_triggers()[0]
    assert trigger.session_key == "websocket:chat-1"


async def test_local_trigger_tool_lifecycle_is_scoped_to_current_session(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    tool = LocalTriggerTool(store)
    own = store.create(
        name="own",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )
    other = store.create(
        name="other",
        channel="websocket",
        chat_id="chat-2",
        session_key="websocket:chat-2",
    )

    with request_context(_context()):
        disabled = await tool.execute(action="disable", trigger_id=own.id)
        assert store.get(own.id).enabled is False
        enabled = await tool.execute(action="enable", trigger_id=own.id)
        assert store.get(own.id).enabled is True
        hidden = await tool.execute(action="remove", trigger_id=other.id)
        removed = await tool.execute(action="remove", trigger_id=own.id)

    assert "Disabled" in disabled
    assert "Enabled" in enabled
    assert getattr(hidden, "is_error", False) is True
    assert store.get(other.id) is not None
    assert "Removed" in removed
    assert store.get(own.id) is None


async def test_local_trigger_tool_requires_active_chat_context(tmp_path: Path) -> None:
    result = await LocalTriggerTool(LocalTriggerStore(tmp_path)).execute(
        action="create",
        name="release monitor",
    )

    assert getattr(result, "is_error", False) is True
    assert "active chat session" in result


def test_agent_loop_registers_local_trigger_tool(tmp_path: Path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    store = LocalTriggerStore(tmp_path)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        local_trigger_store=store,
    )

    tool = loop.tools.get("local_trigger")
    assert isinstance(tool, LocalTriggerTool)
    assert tool._store is store
