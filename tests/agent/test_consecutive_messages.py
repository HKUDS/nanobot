from pathlib import Path

import pytest

from nanobot.agent.context import ContextBuilder


@pytest.fixture
def context_builder(tmp_path: Path) -> ContextBuilder:
    """Create a context builder with temporary workspace."""
    return ContextBuilder(workspace=tmp_path)


def test_build_messages_prevents_consecutive_assistant_roles(context_builder):
    """Test that consecutive assistant messages are prevented."""
    history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]

    # Subagent result comes in with role="assistant"
    messages = context_builder.build_messages(
        history=history,
        current_message="Subagent completed the task",
        current_role="assistant",
    )

    # Should merge or convert to user role to avoid consecutive assistant messages
    roles = [m["role"] for m in messages if m["role"] != "system"]

    # Check that there are no consecutive assistant messages
    for i in range(len(roles) - 1):
        assert not (roles[i] == "assistant" and roles[i + 1] == "assistant"), \
            f"Found consecutive assistant messages at positions {i} and {i+1}"


def test_build_messages_merges_consecutive_assistant_content(context_builder):
    """Test that consecutive assistant messages with string content are merged."""
    history = [
        {"role": "user", "content": "Do task"},
        {"role": "assistant", "content": "Working on it..."},
    ]

    messages = context_builder.build_messages(
        history=history,
        current_message="Task completed",
        current_role="assistant",
    )

    # Find the last assistant message
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1, "Should merge into single assistant message"

    # Content should be merged
    assert "Working on it..." in assistant_msgs[0]["content"]
    assert "Task completed" in assistant_msgs[0]["content"]


def test_build_messages_allows_alternating_roles(context_builder):
    """Test that alternating roles are preserved."""
    history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
    ]

    messages = context_builder.build_messages(
        history=history,
        current_message="How are you?",
        current_role="user",
    )

    roles = [m["role"] for m in messages if m["role"] != "system"]
    assert roles == ["user", "assistant", "user"]


def test_build_messages_handles_tool_calls_in_history(context_builder):
    """Test that messages with tool calls don't cause issues."""
    history = [
        {"role": "user", "content": "Read a file"},
        {
            "role": "assistant",
            "content": "Let me read that",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]
        },
        {"role": "tool", "tool_call_id": "1", "name": "read_file", "content": "file content"},
    ]

    messages = context_builder.build_messages(
        history=history,
        current_message="Subagent result",
        current_role="assistant",
    )

    # Tool message is not assistant, so new assistant message is OK
    roles = [m["role"] for m in messages if m["role"] != "system"]
    assert roles[-2] == "tool"
    assert roles[-1] in ["assistant", "user"]  # Either role is acceptable after tool
