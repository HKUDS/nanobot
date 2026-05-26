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
    assert tool_message["content"] == "tool result"
