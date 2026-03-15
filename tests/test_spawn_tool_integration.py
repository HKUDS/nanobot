import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.session.manager import SessionManager


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def session_manager(workspace):
    return SessionManager(workspace)


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock()
    return provider


@pytest.fixture
def message_bus():
    return MessageBus()


@pytest.mark.asyncio
async def test_spawn_tool_integration(workspace, session_manager, mock_provider, message_bus):
    # 1. Prepare Mock Responses
    # Main Agent response: calling the spawn tool
    spawn_tool_call = MagicMock()
    spawn_tool_call.id = "spawn_1"
    spawn_tool_call.name = "spawn"
    spawn_tool_call.arguments = {"task": "Write 'done' to out.txt", "label": "Writer Task"}
    spawn_tool_call.to_openai_tool_call.return_value = {
        "id": "spawn_1",
        "type": "function",
        "function": {"name": "spawn", "arguments": '{"task": "Write \'done\' to out.txt", "label": "Writer Task"}'}
    }

    resp_main = MagicMock()
    resp_main.has_tool_calls = True
    resp_main.tool_calls = [spawn_tool_call]
    resp_main.content = "Starting a subagent to write to a file."
    resp_main.finish_reason = "tool_calls"
    resp_main.reasoning_content = "I will spawn a subagent."
    resp_main.thinking_blocks = []

    # Subagent turn 1: calling the write_file tool
    write_tool_call = MagicMock()
    write_tool_call.id = "write_1"
    write_tool_call.name = "write_file"
    write_tool_call.arguments = {"path": "out.txt", "content": "done"}
    write_tool_call.to_openai_tool_call.return_value = {
        "id": "write_1",
        "type": "function",
        "function": {"name": "write_file", "arguments": '{"path": "out.txt", "content": "done"}'}
    }

    resp_sub_1 = MagicMock()
    resp_sub_1.has_tool_calls = True
    resp_sub_1.tool_calls = [write_tool_call]
    resp_sub_1.content = "I will write 'done' to out.txt."
    resp_sub_1.finish_reason = "tool_calls"
    resp_sub_1.reasoning_content = "Writing file."
    resp_sub_1.thinking_blocks = []

    # Subagent turn 2: completing the task
    resp_sub_2 = MagicMock()
    resp_sub_2.has_tool_calls = False
    resp_sub_2.content = "I have written 'done' to out.txt."
    resp_sub_2.finish_reason = "stop"
    resp_sub_2.reasoning_content = "Done."
    resp_sub_2.thinking_blocks = []

    # Main Agent handling the subagent's result announcement
    resp_announce = MagicMock()
    resp_announce.has_tool_calls = False
    resp_announce.content = "Subagent has finished writing to the file."
    resp_announce.finish_reason = "stop"
    resp_announce.reasoning_content = "Announcing result."
    resp_announce.thinking_blocks = []

    mock_provider.chat_with_retry.side_effect = [resp_main, resp_sub_1, resp_sub_2, resp_announce]

    # 2. Initialize AgentLoop
    loop = AgentLoop(
        bus=message_bus,
        provider=mock_provider,
        workspace=workspace,
        session_manager=session_manager,
        restrict_to_workspace=True
    )

    # 3. Send message to trigger Spawn
    msg = InboundMessage(
        channel="cli",
        sender_id="user",
        chat_id="direct",
        content="Please write 'done' to out.txt using a subagent"
    )
    
    # Run dispatch to process the main message
    await loop._dispatch(msg)

    # Wait for the subagent to start and finish
    while loop.subagents.get_running_count() > 0:
        await asyncio.sleep(0.1)

    # 4. Verify results
    # Check if the spawn call was recorded in the main session
    main_session = session_manager.get_or_create("cli:direct")
    assert any(m.get("tool_calls") and m["tool_calls"][0]["function"]["name"] == "spawn" 
               for m in main_session.messages)

    # Check if the subagent session exists
    sessions = session_manager.list_sessions()
    subagent_sessions = [s for s in sessions if s["key"].startswith("subagent:")]
    assert len(subagent_sessions) == 1
    
    sub_session = session_manager.get_or_create(subagent_sessions[0]["key"])
    assert sub_session.metadata["parent_session"] == "cli:direct"
    assert sub_session.metadata["label"] == "Writer Task"
    
    # Verify the subagent actually wrote the file
    assert (workspace / "out.txt").exists()
    assert (workspace / "out.txt").read_text() == "done"
