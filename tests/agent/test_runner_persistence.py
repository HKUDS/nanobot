"""Tests for tool result persistence: large results, pruning, temp files, cleanup."""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars

async def test_runner_persists_large_tool_results_for_follow_up_calls(tmp_path):
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    captured_second_call: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="working",
                tool_calls=[ToolCallRequest(id="call_big", name="list_dir", arguments={"path": "."})],
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="x" * 20_000)

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        workspace=tmp_path,
        session_key="test:runner",
        max_tool_result_chars=2048,
    ))

    assert result.final_content == "done"
    tool_message = next(msg for msg in captured_second_call if msg.get("role") == "tool")
    assert "[tool output persisted]" in tool_message["content"]
    assert "tool-results" in tool_message["content"]
    assert (tmp_path / ".nanobot" / "tool-results" / "test_runner" / "call_big.txt").exists()


def test_persist_tool_result_prunes_old_session_buckets(tmp_path):
    from nanobot.utils.helpers import maybe_persist_tool_result

    root = tmp_path / ".nanobot" / "tool-results"
    old_bucket = root / "old_session"
    recent_bucket = root / "recent_session"
    old_bucket.mkdir(parents=True)
    recent_bucket.mkdir(parents=True)
    (old_bucket / "old.txt").write_text("old", encoding="utf-8")
    (recent_bucket / "recent.txt").write_text("recent", encoding="utf-8")

    stale = time.time() - (8 * 24 * 60 * 60)
    os.utime(old_bucket, (stale, stale))
    os.utime(old_bucket / "old.txt", (stale, stale))

    persisted = maybe_persist_tool_result(
        tmp_path,
        "current:session",
        "call_big",
        "x" * 5000,
        max_chars=64,
    )

    assert "[tool output persisted]" in persisted
    assert not old_bucket.exists()
    assert recent_bucket.exists()
    assert (root / "current_session" / "call_big.txt").exists()


def test_persist_tool_result_leaves_no_temp_files(tmp_path):
    from nanobot.utils.helpers import maybe_persist_tool_result

    root = tmp_path / ".nanobot" / "tool-results"
    maybe_persist_tool_result(
        tmp_path,
        "current:session",
        "call_big",
        "x" * 5000,
        max_chars=64,
    )

    assert (root / "current_session" / "call_big.txt").exists()
    assert list((root / "current_session").glob("*.tmp")) == []


def test_persist_tool_result_logs_cleanup_failures(monkeypatch, tmp_path):
    from nanobot.utils.helpers import maybe_persist_tool_result

    warnings: list[str] = []

    monkeypatch.setattr(
        "nanobot.utils.helpers._cleanup_tool_result_buckets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("busy")),
    )
    monkeypatch.setattr(
        "nanobot.utils.helpers.logger.exception",
        lambda message, *args: warnings.append(message.format(*args)),
    )

    persisted = maybe_persist_tool_result(
        tmp_path,
        "current:session",
        "call_big",
        "x" * 5000,
        max_chars=64,
    )

    assert "[tool output persisted]" in persisted
    assert warnings and "Failed to clean stale tool result buckets" in warnings[0]
async def test_runner_keeps_going_when_tool_result_persistence_fails():
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    captured_second_call: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="working",
                tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")

    runner = AgentRunner(provider)
    with patch("nanobot.agent.runner.maybe_persist_tool_result", side_effect=RuntimeError("disk full")):
        result = await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "do task"}],
            tools=tools,
            model="test-model",
            max_iterations=2,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        ))

    assert result.final_content == "done"
    tool_message = next(msg for msg in captured_second_call if msg.get("role") == "tool")


def test_is_path_in_tool_results_detects_tool_results_dir(tmp_path):
    """_is_path_in_tool_result recognises paths inside .nanobot/tool-results/."""
    from nanobot.agent.runner import AgentRunner

    tool_results_dir = tmp_path / ".nanobot" / "tool-results" / "sess1"
    tool_results_dir.mkdir(parents=True)
    persisted_file = tool_results_dir / "call_abc.txt"
    persisted_file.write_text("some large content", encoding="utf-8")

    assert AgentRunner._is_path_in_tool_results(str(persisted_file), tmp_path) is True


def test_is_path_in_tool_results_rejects_normal_file(tmp_path):
    """_is_path_in_tool_result returns False for normal files outside tool-results."""
    from nanobot.agent.runner import AgentRunner

    normal_file = tmp_path / "regular.txt"
    normal_file.write_text("hello", encoding="utf-8")

    assert AgentRunner._is_path_in_tool_results(str(normal_file), tmp_path) is False
    assert AgentRunner._is_path_in_tool_results(None, tmp_path) is False


async def test_runner_skips_offload_for_persisted_tool_result_recovery(tmp_path):
    """read_file reading from tool-results directory should not be offloaded again."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    # Set up a persisted tool result file
    tool_results_dir = tmp_path / ".nanobot" / "tool-results" / "test_runner"
    tool_results_dir.mkdir(parents=True)
    persisted_file = tool_results_dir / "call_big.txt"
    large_content = "x" * 50_000
    persisted_file.write_text(large_content, encoding="utf-8")

    # This is what read_file would return when reading the persisted file
    # (it's a normal read, not exceeding read_file's own 128K limit)
    read_result = (
        f"1| {large_content}\n"
        "\n(End of file — 1 lines total)"
    )

    provider = MagicMock()
    captured_messages: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: agent decides to read a big file
            return LLMResponse(
                content="reading",
                tool_calls=[ToolCallRequest(
                    id="call_read",
                    name="read_file",
                    arguments={"path": "/some/big/file.txt"},
                )],
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            )
        elif call_count["n"] == 2:
            # Second call: agent sees the persisted reference, tries to read it
            captured_messages[:] = messages
            return LLMResponse(
                content="reading persisted",
                tool_calls=[ToolCallRequest(
                    id="call_read_persisted",
                    name="read_file",
                    arguments={"path": str(persisted_file)},
                )],
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            )
        # Third call: agent has the content
        captured_messages[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    # First call returns a big result (will be persisted)
    # Second call returns reading the persisted file (should NOT be persisted again)
    # Third call returns final answer
    first_result = "x" * 20_000  # > max_tool_result_chars, will be persisted
    call_results = [first_result, read_result, "done"]

    async def execute(tool_name, params, **kwargs):
        idx = call_count["n"] - 1
        return call_results[idx] if idx < len(call_results) else "done"

    tools.execute = execute

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "read the big file"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        workspace=tmp_path,
        session_key="test:runner",
        max_tool_result_chars=1024,  # Low threshold to trigger offloading
    ))

    # Find the tool message for the persisted file read
    persisted_read_msg = None
    for msg in captured_messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id") == "call_read_persisted":
            persisted_read_msg = msg
            break

    assert persisted_read_msg is not None, "Should have a tool message for the persisted file read"
    # The key assertion: the persisted file read should NOT be offloaded again
    assert "[tool output persisted]" not in persisted_read_msg["content"]
    assert "x" * 100 in persisted_read_msg["content"]  # Actual content preserved
