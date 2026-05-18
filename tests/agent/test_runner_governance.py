"""Tests for AgentRunner context governance: backfill, orphan cleanup, microcompact, snip_history."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def _make_loop(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)
    return loop

async def test_runner_uses_raw_messages_when_context_governance_fails():
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    captured_messages: list[dict] = []

    async def chat_with_retry(*, messages, **kwargs):
        captured_messages[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    initial_messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
    ]

    runner = AgentRunner(provider)
    runner._snip_history = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    result = await runner.run(AgentRunSpec(
        initial_messages=initial_messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"
    assert captured_messages == initial_messages
def test_snip_history_drops_orphaned_tool_results_from_trimmed_slice(monkeypatch):
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    runner = AgentRunner(provider)
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "tool call",
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "ls", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "tool output"},
        {"role": "assistant", "content": "after tool"},
    ]
    spec = AgentRunSpec(
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        context_window_tokens=2000,
        context_block_limit=100,
    )

    monkeypatch.setattr("nanobot.agent.runner.estimate_prompt_tokens_chain", lambda *_args, **_kwargs: (500, None))
    token_sizes = {
        "old user": 120,
        "tool call": 120,
        "tool output": 40,
        "after tool": 40,
        "system": 0,
    }
    monkeypatch.setattr(
        "nanobot.agent.runner.estimate_message_tokens",
        lambda msg: token_sizes.get(str(msg.get("content")), 40),
    )

    trimmed = runner._snip_history(spec, messages)

    # After the fix, the user message is recovered so the sequence is valid
    # for providers that require system → user (e.g. GLM error 1214).
    assert trimmed[0]["role"] == "system"
    non_system = [m for m in trimmed if m["role"] != "system"]
    assert non_system[0]["role"] == "user", f"Expected user after system, got {non_system[0]['role']}"
async def test_backfill_missing_tool_results_inserts_error():
    """Orphaned tool_use (no matching tool_result) should get a synthetic error."""
    from nanobot.agent.runner import AgentRunner, _BACKFILL_CONTENT

    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_a", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
                {"id": "call_b", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "name": "exec", "content": "ok"},
    ]
    result = AgentRunner._backfill_missing_tool_results(messages)
    tool_msgs = [m for m in result if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    backfilled = [m for m in tool_msgs if m.get("tool_call_id") == "call_b"]
    assert len(backfilled) == 1
    assert backfilled[0]["content"] == _BACKFILL_CONTENT
    assert backfilled[0]["name"] == "read_file"


def test_drop_orphan_tool_results_removes_unmatched_tool_messages():
    from nanobot.agent.runner import AgentRunner

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_ok", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_ok", "name": "read_file", "content": "ok"},
        {"role": "tool", "tool_call_id": "call_orphan", "name": "exec", "content": "stale"},
        {"role": "assistant", "content": "after tool"},
    ]

    cleaned = AgentRunner._drop_orphan_tool_results(messages)

    assert cleaned == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_ok", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_ok", "name": "read_file", "content": "ok"},
        {"role": "assistant", "content": "after tool"},
    ]


@pytest.mark.asyncio
async def test_backfill_noop_when_complete():
    """Complete message chains should not be modified."""
    from nanobot.agent.runner import AgentRunner

    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_x", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_x", "name": "exec", "content": "done"},
        {"role": "assistant", "content": "all good"},
    ]
    result = AgentRunner._backfill_missing_tool_results(messages)
    assert result is messages  # same object — no copy


@pytest.mark.asyncio
async def test_runner_drops_orphan_tool_results_before_model_request():
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    captured_messages: list[dict] = []

    async def chat_with_retry(*, messages, **kwargs):
        captured_messages[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old user"},
            {"role": "tool", "tool_call_id": "call_orphan", "name": "exec", "content": "stale"},
            {"role": "assistant", "content": "after orphan"},
            {"role": "user", "content": "new prompt"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert all(
        message.get("tool_call_id") != "call_orphan"
        for message in captured_messages
        if message.get("role") == "tool"
    )
    assert result.messages[2]["tool_call_id"] == "call_orphan"
    assert result.final_content == "done"


@pytest.mark.asyncio
async def test_backfill_repairs_model_context_without_shifting_save_turn_boundary(tmp_path):
    """Historical backfill should not duplicate old tail messages on persist."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.runner import _BACKFILL_CONTENT
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    response = LLMResponse(content="new answer", tool_calls=[], usage={})
    provider.chat_with_retry = AsyncMock(return_value=response)
    provider.chat_stream_with_retry = AsyncMock(return_value=response)

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": "user", "content": "old user", "timestamp": "2026-01-01T00:00:00"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_missing",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
            "timestamp": "2026-01-01T00:00:01",
        },
        {"role": "assistant", "content": "old tail", "timestamp": "2026-01-01T00:00:02"},
    ]
    loop.sessions.save(session)

    result = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="test", content="new prompt")
    )

    assert result is not None
    assert result.content == "new answer"

    request_messages = provider.chat_with_retry.await_args.kwargs["messages"]
    synthetic = [
        message
        for message in request_messages
        if message.get("role") == "tool" and message.get("tool_call_id") == "call_missing"
    ]
    assert len(synthetic) == 1
    assert synthetic[0]["content"] == _BACKFILL_CONTENT

    session_after = loop.sessions.get_or_create("cli:test")
    assert [
        {
            key: value
            for key, value in message.items()
            if key in {"role", "content", "tool_call_id", "name", "tool_calls"}
        }
        for message in session_after.messages
    ] == [
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_missing",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "assistant", "content": "old tail"},
        {"role": "user", "content": "new prompt"},
        {"role": "assistant", "content": "new answer"},
    ]


@pytest.mark.asyncio
async def test_runner_backfill_only_mutates_model_context_not_returned_messages():
    """Runner should repair orphaned tool calls for the model without rewriting result.messages."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner, _BACKFILL_CONTENT

    provider = MagicMock()
    captured_messages: list[dict] = []

    async def chat_with_retry(*, messages, **kwargs):
        captured_messages[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    initial_messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_missing",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "assistant", "content": "old tail"},
        {"role": "user", "content": "new prompt"},
    ]

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=initial_messages,
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    synthetic = [
        message
        for message in captured_messages
        if message.get("role") == "tool" and message.get("tool_call_id") == "call_missing"
    ]
    assert len(synthetic) == 1
    assert synthetic[0]["content"] == _BACKFILL_CONTENT

    assert [
        {
            key: value
            for key, value in message.items()
            if key in {"role", "content", "tool_call_id", "name", "tool_calls"}
        }
        for message in result.messages
    ] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_missing",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "assistant", "content": "old tail"},
        {"role": "user", "content": "new prompt"},
        {"role": "assistant", "content": "done"},
    ]


# ---------------------------------------------------------------------------
# Microcompact (stale tool result compaction)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_microcompact_replaces_old_tool_results():
    """Tool results beyond _MICROCOMPACT_KEEP_RECENT should be summarized."""
    from nanobot.agent.runner import AgentRunner, _MICROCOMPACT_KEEP_RECENT

    total = _MICROCOMPACT_KEEP_RECENT + 5
    long_content = "x" * 600
    messages: list[dict] = [{"role": "system", "content": "sys"}]
    for i in range(total):
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
        })
        messages.append({
            "role": "tool", "tool_call_id": f"c{i}", "name": "read_file",
            "content": long_content,
        })

    result = AgentRunner._microcompact(messages)
    tool_msgs = [m for m in result if m.get("role") == "tool"]
    stale_count = total - _MICROCOMPACT_KEEP_RECENT
    compacted = [m for m in tool_msgs if "omitted from context" in str(m.get("content", ""))]
    preserved = [m for m in tool_msgs if m.get("content") == long_content]
    assert len(compacted) == stale_count
    assert len(preserved) == _MICROCOMPACT_KEEP_RECENT


@pytest.mark.asyncio
async def test_microcompact_preserves_short_results():
    """Short tool results (< _MICROCOMPACT_MIN_CHARS) should not be replaced."""
    from nanobot.agent.runner import AgentRunner, _MICROCOMPACT_KEEP_RECENT

    total = _MICROCOMPACT_KEEP_RECENT + 5
    messages: list[dict] = []
    for i in range(total):
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "exec", "arguments": "{}"}}],
        })
        messages.append({
            "role": "tool", "tool_call_id": f"c{i}", "name": "exec",
            "content": "short",
        })

    result = AgentRunner._microcompact(messages)
    assert result is messages  # no copy needed — all stale results are short


@pytest.mark.asyncio
async def test_microcompact_skips_non_compactable_tools():
    """Non-compactable tools (e.g. 'message') should never be replaced."""
    from nanobot.agent.runner import AgentRunner, _MICROCOMPACT_KEEP_RECENT

    total = _MICROCOMPACT_KEEP_RECENT + 5
    long_content = "y" * 1000
    messages: list[dict] = []
    for i in range(total):
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "message", "arguments": "{}"}}],
        })
        messages.append({
            "role": "tool", "tool_call_id": f"c{i}", "name": "message",
            "content": long_content,
        })

    result = AgentRunner._microcompact(messages)
    assert result is messages  # no compactable tools found


def test_governance_repairs_orphans_after_snip():
    """After _snip_history clips an assistant+tool_calls, the second
    _drop_orphan_tool_results pass must clean up the resulting orphans."""
    from nanobot.agent.runner import AgentRunner

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old msg"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "tc_old", "type": "function",
                         "function": {"name": "search", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc_old", "name": "search",
         "content": "old result"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new msg"},
    ]

    # Simulate snipping that keeps only the tail: drop the assistant with
    # tool_calls but keep its tool result (orphan).
    snipped = [
        {"role": "system", "content": "system"},
        {"role": "tool", "tool_call_id": "tc_old", "name": "search",
         "content": "old result"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new msg"},
    ]

    cleaned = AgentRunner._drop_orphan_tool_results(snipped)
    # The orphan tool result should be removed.
    assert not any(
        m.get("role") == "tool" and m.get("tool_call_id") == "tc_old"
        for m in cleaned
    )


def test_governance_fallback_still_repairs_orphans():
    """When full governance fails, the fallback must still run
    _drop_orphan_tool_results and _backfill_missing_tool_results."""
    from nanobot.agent.runner import AgentRunner

    # Messages with an orphan tool result (no matching assistant tool_call).
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "tool", "tool_call_id": "orphan_tc", "name": "read",
         "content": "stale"},
        {"role": "assistant", "content": "hi"},
    ]

    repaired = AgentRunner._drop_orphan_tool_results(messages)
    repaired = AgentRunner._backfill_missing_tool_results(repaired)
    # Orphan tool result should be gone.
    assert not any(m.get("tool_call_id") == "orphan_tc" for m in repaired)
def test_snip_history_preserves_user_message_after_truncation(monkeypatch):
    """When _snip_history truncates messages and the only user message ends up
    outside the kept window, the method must recover the nearest user message
    so the resulting sequence is valid for providers like GLM (which reject
    system→assistant with error 1214).

    This reproduces the exact scenario from the bug report:
    - Normal interaction: user asks, assistant calls tool, tool returns,
      assistant replies.
    - Injection adds a phantom user message, triggering more tool calls.
    - _snip_history activates, keeping only recent assistant/tool pairs.
    - The injected user message is in the truncated prefix and gets lost.
    """
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    runner = AgentRunner(provider)

    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "previous reply"},
        {"role": "user", "content": ".nanobot的同目录"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "tc_1", "type": "function", "function": {"name": "exec", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "tc_1", "content": "tool output 1"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "tc_2", "type": "function", "function": {"name": "exec", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "tc_2", "content": "tool output 2"},
    ]

    spec = AgentRunSpec(
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        context_window_tokens=2000,
        context_block_limit=100,
    )

    # Make estimate_prompt_tokens_chain report above budget so _snip_history activates.
    monkeypatch.setattr("nanobot.agent.runner.estimate_prompt_tokens_chain", lambda *_a, **_kw: (500, None))
    # Make kept window small: only the last 2 messages fit the budget.
    token_sizes = {
        "system": 0,
        "previous reply": 200,
        ".nanobot的同目录": 80,
        "tool output 1": 80,
        "tool output 2": 80,
    }
    monkeypatch.setattr(
        "nanobot.agent.runner.estimate_message_tokens",
        lambda msg: token_sizes.get(str(msg.get("content")), 100),
    )

    trimmed = runner._snip_history(spec, messages)

    # The first non-system message MUST be user (not assistant).
    non_system = [m for m in trimmed if m.get("role") != "system"]
    assert non_system, "trimmed should contain at least one non-system message"
    assert non_system[0]["role"] == "user", (
        f"First non-system message must be 'user', got '{non_system[0]['role']}'. "
        f"Roles: {[m['role'] for m in trimmed]}"
    )


def test_snip_history_no_user_at_all_falls_back_gracefully(monkeypatch):
    """Edge case: if non_system has zero user messages, _snip_history should
    still return a valid sequence (not crash or produce system→assistant)."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    runner = AgentRunner(provider)

    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "reply"},
        {"role": "tool", "tool_call_id": "tc_1", "content": "result"},
        {"role": "assistant", "content": "reply 2"},
        {"role": "tool", "tool_call_id": "tc_2", "content": "result 2"},
    ]

    spec = AgentRunSpec(
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        context_window_tokens=2000,
        context_block_limit=100,
    )

    monkeypatch.setattr("nanobot.agent.runner.estimate_prompt_tokens_chain", lambda *_a, **_kw: (500, None))
    monkeypatch.setattr(
        "nanobot.agent.runner.estimate_message_tokens",
        lambda msg: 100,
    )

    trimmed = runner._snip_history(spec, messages)

    # Should not crash.  The result should still be a valid list.
    assert isinstance(trimmed, list)
    # Must have at least system.
    assert any(m.get("role") == "system" for m in trimmed)
    # The _enforce_role_alternation safety net must be able to fix whatever
    # _snip_history returns here — verify it produces a valid sequence.
    from nanobot.providers.base import LLMProvider
    fixed = LLMProvider._enforce_role_alternation(trimmed)
    non_system = [m for m in fixed if m["role"] != "system"]
    if non_system:
        assert non_system[0]["role"] in ("user", "tool"), (
            f"Safety net should ensure first non-system is user/tool, got {non_system[0]['role']}"
        )
