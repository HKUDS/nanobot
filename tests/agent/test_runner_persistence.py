"""Tests for tool result persistence: large results, pruning, temp files, cleanup."""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, LLMUsage, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.parametrize("invalid_block", [42, ["nested"], {}, {"type": "text", "text": 42}])
def test_unrecognized_result_list_is_not_partially_offloaded(tmp_path, invalid_block):
    from nanobot.agent.context_governance import ContextGovernanceConfig, ContextGovernor
    from nanobot.agent.tools.registry import ToolRegistry

    result = [{"type": "text", "text": "x" * 20_000}, invalid_block]
    config = ContextGovernanceConfig(
        provider=MagicMock(), model="test", tools=ToolRegistry(), workspace=tmp_path,
        session_key="invalid", max_tool_result_chars=2048,
    )
    assert ContextGovernor.normalize_tool_result(config, "call", "custom", result) is result
    assert list(tmp_path.iterdir()) == []


async def test_runner_persists_large_tool_results_for_follow_up_calls(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.runner import AgentRunner
    from nanobot.session.manager import Session

    provider = MagicMock()
    captured_second_call: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="working",
                tool_calls=[ToolCallRequest(id="call_big", name="list_dir", arguments={"path": "."})],
                usage=LLMUsage.reported(input_tokens=5, output_tokens=3),
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="x" * 20_000)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
    assert len(tool_message["content"]) <= 2048
    assert "[tool output persisted]" in tool_message["content"]
    assert "Result truncated. Read the saved file" in tool_message["content"]
    assert "tool-results" in tool_message["content"]
    persisted_path = tmp_path / ".nanobot" / "tool-results" / "test_runner" / "call_big.txt"
    assert persisted_path.read_text(encoding="utf-8") == "x" * 20_000

    from nanobot.agent.tools.filesystem import ReadFileTool

    readback = await ReadFileTool(workspace=tmp_path).execute(
        path=".nanobot/tool-results/test_runner/call_big.txt"
    )
    assert "x" * 20_000 in readback

    loop = AgentLoop.__new__(AgentLoop)
    loop.max_tool_result_chars = 2048
    session = Session(key="test:runner")
    loop._save_turn(session, result.messages, skip=1)
    persisted_tool = next(message for message in session.messages if message.get("role") == "tool")
    assert persisted_tool["content"] == tool_message["content"]

    replay_provider = MagicMock()
    replay_provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="replayed", tool_calls=[], usage=None)
    )
    replay_tools = MagicMock()
    replay_tools.get_definitions.return_value = []
    replay_result = await AgentRunner().run(make_run_spec(replay_provider,
        initial_messages=[
            *session.get_history(),
            {"role": "user", "content": "continue"},
        ],
        tools=replay_tools,
        model="test-model",
        max_iterations=1,
        workspace=tmp_path,
        session_key="test:runner",
        max_tool_result_chars=2048,
    ))
    replay_tool = next(
        message
        for message in replay_provider.chat_with_retry.await_args.kwargs["messages"]
        if message.get("role") == "tool"
    )
    assert replay_result.final_content == "replayed"
    assert replay_tool["content"] == tool_message["content"]


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

    assert "truncated" in persisted
    assert ".nanobot" in persisted
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

    assert "truncated" in persisted
    assert ".nanobot" in persisted
    assert warnings and "Failed to clean stale tool result buckets" in warnings[0]


async def test_read_file_result_is_not_offloaded(tmp_path):
    """read_file must not trigger generic offloading (prevents persist->read->persist loops)."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    captured_second_call: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="reading",
                tool_calls=[ToolCallRequest(id="call_rf", name="read_file", arguments={"path": "big.txt"})],
                usage=LLMUsage.reported(input_tokens=5, output_tokens=3),
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="x" * 20_000)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "read big file"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        workspace=tmp_path,
        session_key="test:runner",
        max_tool_result_chars=2048,
    ))

    assert result.final_content == "done"
    tool_message = next(msg for msg in captured_second_call if msg.get("role") == "tool")
    # read_file result must NOT be offloaded to a file
    assert "[tool output persisted]" not in tool_message["content"]
    # read_file manages its own size; generic truncation must NOT apply
    assert len(tool_message["content"]) == 20_000
    # no file should have been written for this read_file call
    offload_dir = tmp_path / ".nanobot" / "tool-results"
    assert not any(offload_dir.rglob("call_rf.txt")) if offload_dir.exists() else True


async def test_processed_tool_result_is_stable_for_persistence_and_replay(tmp_path):
    """The content sent after a tool call must survive the session round trip unchanged."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.runner import AgentRunner
    from nanobot.session.manager import Session

    raw_result = "start-" + ("x" * 20_000) + "-end-marker"
    first_provider = MagicMock()
    first_tools = MagicMock()
    first_tools.get_definitions.return_value = []
    first_tools.execute = AsyncMock(return_value=raw_result)

    first_provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="working",
            tool_calls=[ToolCallRequest(
                id="call_replay",
                name="read_file",
                arguments={"path": "large.txt"},
            )],
            usage=None,
        ),
        LLMResponse(content="done", tool_calls=[], usage=None),
    ])
    result = await AgentRunner().run(make_run_spec(first_provider,
        initial_messages=[{"role": "user", "content": "read large file"}],
        tools=first_tools,
        model="test-model",
        max_iterations=2,
        workspace=tmp_path,
        session_key="test:replay",
        max_tool_result_chars=2048,
    ))
    request_tool = next(
        message for message in first_provider.chat_with_retry.await_args_list[1].kwargs["messages"]
        if message.get("role") == "tool"
    )

    loop = AgentLoop.__new__(AgentLoop)
    loop.max_tool_result_chars = 2048
    session = Session(key="test:replay")
    loop._save_turn(session, result.messages, skip=1)
    persisted_tool = next(message for message in session.messages if message.get("role") == "tool")

    assert request_tool["content"] == raw_result
    assert persisted_tool["content"] == request_tool["content"]

    replay_provider = MagicMock()
    replay_provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="replayed", tool_calls=[], usage=None)
    )
    replay_tools = MagicMock()
    replay_tools.get_definitions.return_value = []
    replay_result = await AgentRunner().run(make_run_spec(replay_provider,
        initial_messages=[
            *session.get_history(),
            {"role": "user", "content": "continue"},
        ],
        tools=replay_tools,
        model="test-model",
        max_iterations=1,
        workspace=tmp_path,
        session_key="test:replay",
        max_tool_result_chars=2048,
    ))
    replay_request_tool = next(
        message for message in replay_provider.chat_with_retry.await_args.kwargs["messages"]
        if message.get("role") == "tool"
    )

    assert replay_result.final_content == "replayed"
    assert replay_request_tool["content"] == request_tool["content"]


async def test_runner_keeps_going_when_tool_result_persistence_fails():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    captured_second_call: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="working",
                tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
                usage=LLMUsage.reported(input_tokens=5, output_tokens=3),
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")

    runner = AgentRunner()
    with patch(
        "nanobot.agent.context_governance.maybe_persist_tool_result",
        side_effect=RuntimeError("disk full"),
    ):
        result = await runner.run(make_run_spec(provider,
            initial_messages=[{"role": "user", "content": "do task"}],
            tools=tools,
            model="test-model",
            max_iterations=2,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        ))

    assert result.final_content == "done"
    tool_message = next(msg for msg in captured_second_call if msg.get("role") == "tool")
    assert tool_message["content"] == "tool result"


async def test_mixed_tool_text_survives_model_save_replay(tmp_path):
    from nanobot.agent.context_governance import ContextGovernanceConfig, ContextGovernor
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.filesystem import ReadFileTool
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.session.manager import Session

    tools = ToolRegistry()
    reader = ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path)
    tools.register(reader)
    config = ContextGovernanceConfig(
        provider=MagicMock(), model="test", tools=tools, workspace=tmp_path,
        session_key="mixed", max_tool_result_chars=2048,
    )
    raw = "start-" + "x" * 20_000 + "-end"
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}}
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "mixed", "type": "function",
            "function": {"name": "custom_image_tool", "arguments": "{}"},
        }]},
        {"role": "tool", "name": "custom_image_tool", "tool_call_id": "mixed",
         "content": [{"type": "text", "text": raw}, image]},
    ]
    governor = ContextGovernor()
    live = governor.prepare_messages_for_model(config, messages)
    reference = live[-1]["content"][0]["text"]
    assert len(reference) <= 2048
    assert live[-1]["content"][1] == image
    loop = AgentLoop.__new__(AgentLoop)
    session = Session(key="mixed")
    loop._save_turn(session, live, skip=0)
    replay = governor.prepare_messages_for_model(config, session.get_history())
    assert replay[-1]["content"][0]["text"] == reference
    assert "data:image" not in str(replay[-1]["content"])
    readback = await reader.execute(path=".nanobot/tool-results/mixed/mixed_text_0.txt")
    assert raw in readback
    assert messages[-1]["content"][0]["text"] == raw


async def test_tiny_budget_keeps_complete_readable_reference(tmp_path):
    from nanobot.agent.context_governance import ContextGovernanceConfig, ContextGovernor
    from nanobot.agent.tools.filesystem import ReadFileTool
    from nanobot.agent.tools.registry import ToolRegistry

    tools = ToolRegistry()
    reader = ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path)
    tools.register(reader)
    session_key = "review-session-0123456789-0123456789"
    call_id = "call_012345678901234567890123456789"
    config = ContextGovernanceConfig(
        provider=MagicMock(), model="test", tools=tools, workspace=tmp_path,
        session_key=session_key, max_tool_result_chars=64,
    )
    raw = "y" * 20_000
    reference = ContextGovernor.normalize_tool_result(config, call_id, "exec", raw)
    assert reference.startswith("[truncated: ") and reference.endswith("]")
    path = reference.removeprefix("[truncated: ").removesuffix("]")
    assert raw in await reader.execute(path=path)
    assert ContextGovernor.normalize_tool_result(config, call_id, "exec", reference) == reference
    assert (tmp_path / path).read_text(encoding="utf-8") == raw


async def test_result_reference_survives_workspace_switch_without_bypassing_restriction(tmp_path):
    import re

    from nanobot.agent.tools.filesystem import ReadFileTool
    from nanobot.security.workspace_access import (
        bind_workspace_scope,
        build_workspace_scope,
        reset_workspace_scope,
    )
    from nanobot.utils.helpers import maybe_persist_tool_result

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    raw = "x" * 20_000
    reference = maybe_persist_tool_result(first, "session", "call", raw, max_chars=2048)
    match = re.search(r"workspace path: (.+)", reference)
    assert match is not None
    reader = ReadFileTool(workspace=first)
    for mode, expected in [("full", raw), ("restricted", "Error")]:
        token = bind_workspace_scope(build_workspace_scope(second, mode))
        try:
            result = await reader.execute(path=match[1], force=True)
            assert expected in result
        finally:
            reset_workspace_scope(token)
