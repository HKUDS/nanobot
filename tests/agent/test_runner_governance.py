"""Tests for AgentRunner context governance: backfill, orphan cleanup, microcompact, snip_history."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.context_governance import (
    BACKFILL_CONTENT,
    MICROCOMPACT_KEEP_RECENT,
    ContextGovernanceConfig,
    ContextGovernor,
)
from nanobot.agent.runner import AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def _governance_config(
    provider,
    tools,
    spec: AgentRunSpec,
    *,
    inflight_start_index: int = 0,
) -> ContextGovernanceConfig:
    return ContextGovernanceConfig(
        provider=provider,
        model=spec.runtime.model,
        tools=tools,
        workspace=spec.workspace,
        session_key=spec.session_key,
        max_tool_result_chars=spec.max_tool_result_chars,
        context_window_tokens=spec.runtime.context_window_tokens,
        context_block_limit=spec.context_block_limit,
        max_tokens=spec.runtime.generation.max_tokens,
        inflight_start_index=inflight_start_index,
    )


def _make_loop(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr:
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)
    return loop


async def test_runner_uses_raw_messages_when_context_governance_fails():
    from nanobot.agent.runner import AgentRunner

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

    runner = AgentRunner()
    runner.context_governor.prepare_for_model = MagicMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("boom")
    )
    result = await runner.run(make_run_spec(provider,
        initial_messages=initial_messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"
    assert captured_messages == initial_messages


def test_snip_history_drops_orphaned_tool_results_from_trimmed_slice(monkeypatch):
    provider = MagicMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
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
    spec = make_run_spec(provider,
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        context_window_tokens=2000,
        context_block_limit=100,
    )

    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (500, None),
    )
    token_sizes = {
        "old user": 120,
        "tool call": 120,
        "tool output": 40,
        "after tool": 40,
        "system": 0,
    }
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_message_tokens",
        lambda msg: token_sizes.get(str(msg.get("content")), 40),
    )

    trimmed = ContextGovernor().snip_history(_governance_config(provider, tools, spec), messages)

    # After the fix, the user message is recovered so the sequence is valid
    # for providers that require system → user (e.g. GLM error 1214).
    assert trimmed[0]["role"] == "system"
    non_system = [m for m in trimmed if m["role"] != "system"]
    assert non_system[0]["role"] == "user", f"Expected user after system, got {non_system[0]['role']}"


def test_snip_history_reserves_budget_for_tool_definitions(monkeypatch):
    provider = MagicMock()
    tools = MagicMock()
    tools.get_definitions.return_value = [{"type": "function", "function": {"name": "large_tool"}}]
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old user"},
        {"role": "assistant", "content": "old assistant"},
        {"role": "user", "content": "recent one"},
        {"role": "assistant", "content": "recent answer"},
        {"role": "user", "content": "recent two"},
    ]
    spec = make_run_spec(provider,
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        context_window_tokens=2000,
        context_block_limit=500,
    )

    def _estimate(_provider, _model, estimate_messages, estimate_tools):
        if estimate_messages == messages:
            return 1000, None
        assert estimate_messages == [{"role": "system", "content": "system"}]
        assert estimate_tools == tools.get_definitions.return_value
        return 350, None

    monkeypatch.setattr("nanobot.agent.context_governance.estimate_prompt_tokens_chain", _estimate)
    token_sizes = {
        "system": 50,
        "old user": 200,
        "old assistant": 200,
        "recent one": 200,
        "recent answer": 200,
        "recent two": 200,
    }
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_message_tokens",
        lambda msg: token_sizes.get(str(msg.get("content")), 40),
    )

    trimmed = ContextGovernor().snip_history(_governance_config(provider, tools, spec), messages)

    contents = [message.get("content") for message in trimmed]
    assert contents == ["system", "recent two"]


async def test_backfill_missing_tool_results_inserts_error():
    """Orphaned tool_use (no matching tool_result) should get a synthetic error."""

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
    result = ContextGovernor.backfill_missing_tool_results(messages)
    tool_msgs = [m for m in result if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    backfilled = [m for m in tool_msgs if m.get("tool_call_id") == "call_b"]
    assert len(backfilled) == 1
    assert backfilled[0]["content"] == BACKFILL_CONTENT
    assert backfilled[0]["name"] == "read_file"


def test_drop_orphan_tool_results_removes_unmatched_tool_messages():
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

    cleaned = ContextGovernor.drop_orphan_tool_results(messages)

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


def test_apply_tool_replay_window_keeps_10_summarizes_50_removes_rest():
    messages = [{"role": "user", "content": "run many commands"}]
    for idx in range(65):
        messages.extend([
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_{idx}",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": f'{{"command":"cmd {idx}"}}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": f"call_{idx}",
                "name": "exec",
                "content": f"output {idx} " + ("x" * 300),
            },
        ])

    compacted = ContextGovernor().apply_tool_replay_window(messages)

    tool_messages = [msg for msg in compacted if msg.get("role") == "tool"]
    tool_ids = [msg["tool_call_id"] for msg in tool_messages]
    assert tool_ids == [f"call_{idx}" for idx in range(5, 65)]
    assert all(
        "result summarized for context" in str(msg.get("content"))
        for msg in tool_messages[:50]
    )
    assert all(
        str(msg.get("content")).startswith(f"output {idx}")
        for idx, msg in zip(range(55, 65), tool_messages[50:])
    )
    assistant_call_ids = [
        call["id"]
        for msg in compacted
        for call in msg.get("tool_calls") or []
    ]
    assert assistant_call_ids == [f"call_{idx}" for idx in range(5, 65)]
    assert compacted[0] is messages[0]
    assert messages[2]["tool_call_id"] == "call_0"  # original history is untouched


def test_apply_tool_replay_window_leaves_latest_10_unchanged():
    messages = [{"role": "user", "content": "run commands"}]
    for idx in range(10):
        messages.extend([
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": f"call_{idx}", "type": "function", "function": {"name": "exec"}},
                ],
            },
            {"role": "tool", "tool_call_id": f"call_{idx}", "name": "exec", "content": "ok"},
        ])

    assert ContextGovernor().apply_tool_replay_window(messages) is messages


@pytest.mark.asyncio
async def test_backfill_noop_when_complete():
    """Complete message chains should not be modified."""
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
    result = ContextGovernor.backfill_missing_tool_results(messages)
    assert result is messages  # same object — no copy


@pytest.mark.asyncio
async def test_runner_drops_orphan_tool_results_before_model_request():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    captured_messages: list[dict] = []

    async def chat_with_retry(*, messages, **kwargs):
        captured_messages[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
    assert synthetic[0]["content"] == BACKFILL_CONTENT

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
    from nanobot.agent.runner import AgentRunner

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

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
    assert synthetic[0]["content"] == BACKFILL_CONTENT

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


def _microcompact_messages(*, total: int, tool_name: str, content: str) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": "sys"}]
    for i in range(total):
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": f"c{i}",
                "type": "function",
                "function": {"name": tool_name, "arguments": "{}"},
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": f"c{i}",
            "name": tool_name,
            "content": content,
        })
    return messages


def test_microcompact_skips_when_prompt_under_hard_budget(monkeypatch):
    """Cache-friendly path: in-flight tool results stay stable while prompt fits."""
    provider = MagicMock()
    provider.generation = SimpleNamespace(max_tokens=0)
    tools = MagicMock()
    tools.get_definitions.return_value = []

    total = MICROCOMPACT_KEEP_RECENT + 5
    long_content = "x" * 600
    messages = _microcompact_messages(total=total, tool_name="read_file", content=long_content)
    spec = make_run_spec(provider,
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        max_tokens=0,
        context_window_tokens=20_000,
    )

    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (1000, "test"),
    )

    result = ContextGovernor().compact_inflight_overflow(
        _governance_config(provider, tools, spec),
        messages,
        set(),
    )

    assert result is messages


def test_microcompact_overflow_compacts_to_low_watermark(monkeypatch):
    """Overflow path: compact in-flight stale results with headroom for later calls."""
    provider = MagicMock()
    provider.generation = SimpleNamespace(max_tokens=0)
    tools = MagicMock()
    tools.get_definitions.return_value = []

    total = MICROCOMPACT_KEEP_RECENT + 8
    long_content = "x" * 600
    messages = _microcompact_messages(total=total, tool_name="read_file", content=long_content)
    spec = make_run_spec(provider,
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        max_tokens=0,
        context_window_tokens=2224,  # input budget 1200, low target 1020
    )

    def estimate(_provider, _model, msgs, _tools):
        return sum(
            100 if (content := msg.get("content")) == long_content
            else 1 if isinstance(content, str) and "compacted to fit context" in content
            else 0
            for msg in msgs
            if msg.get("role") == "tool"
        ), "test"

    monkeypatch.setattr("nanobot.agent.context_governance.estimate_prompt_tokens_chain", estimate)

    result = ContextGovernor().compact_inflight_overflow(
        _governance_config(provider, tools, spec),
        messages,
        set(),
    )
    tool_msgs = [m for m in result if m.get("role") == "tool"]
    compacted = [m for m in tool_msgs if "compacted to fit context" in str(m.get("content", ""))]
    preserved = [m for m in tool_msgs if m.get("content") == long_content]

    assert len(compacted) == 8
    assert len(preserved) == total - 8
    assert [m["tool_call_id"] for m in compacted] == [f"c{i}" for i in range(8)]


def test_microcompact_compacts_newest_when_it_alone_overflows(monkeypatch):
    """The newest result is preserved only while the request can still fit."""
    provider = MagicMock()
    provider.generation = SimpleNamespace(max_tokens=0)
    tools = MagicMock()
    tools.get_definitions.return_value = []

    long_content = "x" * 600
    messages = _microcompact_messages(total=1, tool_name="read_file", content=long_content)
    spec = make_run_spec(provider,
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        max_tokens=0,
        context_window_tokens=2000,
        context_block_limit=500,
    )

    def estimate(_provider, _model, msgs, _tools):
        return sum(
            1000 if msg.get("content") == long_content else 1
            for msg in msgs
            if msg.get("role") == "tool"
        ), "test"

    monkeypatch.setattr("nanobot.agent.context_governance.estimate_prompt_tokens_chain", estimate)

    compacted_tool_call_ids: set[str] = set()
    result = ContextGovernor().compact_inflight_overflow(
        _governance_config(provider, tools, spec),
        messages,
        compacted_tool_call_ids,
    )

    tool_msg = next(m for m in result if m.get("role") == "tool")
    assert "compacted to fit context" in tool_msg["content"]
    assert compacted_tool_call_ids == {"c0"}


def test_context_governor_keeps_compaction_boundary_stable(monkeypatch):
    provider = MagicMock()
    provider.generation = SimpleNamespace(max_tokens=0)
    tools = MagicMock()
    tools.get_definitions.return_value = []

    total = MICROCOMPACT_KEEP_RECENT + 8
    long_content = "x" * 600
    messages = _microcompact_messages(total=total, tool_name="read_file", content=long_content)
    spec = make_run_spec(provider,
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        max_tokens=0,
        context_window_tokens=2224,
    )

    def estimate(_provider, _model, msgs, _tools):
        return sum(
            100 if msg.get("content") == long_content else 1
            for msg in msgs
            if msg.get("role") == "tool"
        ), "test"

    monkeypatch.setattr("nanobot.agent.context_governance.estimate_prompt_tokens_chain", estimate)

    governor = ContextGovernor()
    compacted_tool_call_ids: set[str] = set()
    config = _governance_config(provider, tools, spec, inflight_start_index=0)
    first = governor.compact_inflight_overflow(config, messages, compacted_tool_call_ids)
    first_ids = set(compacted_tool_call_ids)

    second = governor.compact_inflight_overflow(config, messages, compacted_tool_call_ids)

    assert compacted_tool_call_ids == first_ids
    assert [m.get("content") for m in second] == [m.get("content") for m in first]


def test_microcompact_preserves_short_results(monkeypatch):
    """Short tool results below the compaction threshold should not be replaced."""
    provider = MagicMock()
    provider.generation = SimpleNamespace(max_tokens=0)
    tools = MagicMock()
    tools.get_definitions.return_value = []

    total = MICROCOMPACT_KEEP_RECENT + 5
    messages = _microcompact_messages(total=total, tool_name="exec", content="short")
    spec = make_run_spec(provider,
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        max_tokens=0,
        context_window_tokens=2024,
    )

    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (2000, "test"),
    )

    result = ContextGovernor().compact_inflight_overflow(
        _governance_config(provider, tools, spec),
        messages,
        set(),
    )
    assert result is messages  # no copy needed — all stale results are short


def test_microcompact_skips_non_compactable_tools(monkeypatch):
    """Non-compactable tools (e.g. 'message') should never be replaced."""
    provider = MagicMock()
    provider.generation = SimpleNamespace(max_tokens=0)
    tools = MagicMock()
    tools.get_definitions.return_value = []

    total = MICROCOMPACT_KEEP_RECENT + 5
    long_content = "y" * 1000
    messages = _microcompact_messages(total=total, tool_name="message", content=long_content)
    spec = make_run_spec(provider,
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        max_tokens=0,
        context_window_tokens=2024,
    )

    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (2000, "test"),
    )

    result = ContextGovernor().compact_inflight_overflow(
        _governance_config(provider, tools, spec),
        messages,
        set(),
    )
    assert result is messages  # no compactable tools found


def test_governance_repairs_orphans_after_snip():
    """After snipping clips an assistant+tool_calls, orphan repair cleans up the tail."""
    # Simulate snipping that keeps only the tail: drop the assistant with
    # tool_calls but keep its tool result (orphan).
    snipped = [
        {"role": "system", "content": "system"},
        {"role": "tool", "tool_call_id": "tc_old", "name": "search",
         "content": "old result"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new msg"},
    ]

    cleaned = ContextGovernor.drop_orphan_tool_results(snipped)
    # The orphan tool result should be removed.
    assert not any(
        m.get("role") == "tool" and m.get("tool_call_id") == "tc_old"
        for m in cleaned
    )


def test_governance_fallback_still_repairs_orphans():
    """When full governance fails, the fallback must still repair orphans."""
    # Messages with an orphan tool result (no matching assistant tool_call).
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "tool", "tool_call_id": "orphan_tc", "name": "read",
         "content": "stale"},
        {"role": "assistant", "content": "hi"},
    ]

    repaired = ContextGovernor.drop_orphan_tool_results(messages)
    repaired = ContextGovernor.backfill_missing_tool_results(repaired)
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
    provider = MagicMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []

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

    spec = make_run_spec(provider,
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        context_window_tokens=2000,
        context_block_limit=100,
    )

    # Make estimate_prompt_tokens_chain report above budget so _snip_history activates.
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_a, **_kw: (500, None),
    )
    # Make kept window small: only the last 2 messages fit the budget.
    token_sizes = {
        "system": 0,
        "previous reply": 200,
        ".nanobot的同目录": 80,
        "tool output 1": 80,
        "tool output 2": 80,
    }
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_message_tokens",
        lambda msg: token_sizes.get(str(msg.get("content")), 100),
    )

    trimmed = ContextGovernor().snip_history(_governance_config(provider, tools, spec), messages)

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
    provider = MagicMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "reply"},
        {"role": "tool", "tool_call_id": "tc_1", "content": "result"},
        {"role": "assistant", "content": "reply 2"},
        {"role": "tool", "tool_call_id": "tc_2", "content": "result 2"},
    ]

    spec = make_run_spec(provider,
        initial_messages=messages,
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        context_window_tokens=2000,
        context_block_limit=100,
    )

    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_a, **_kw: (500, None),
    )
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_message_tokens",
        lambda msg: 100,
    )

    trimmed = ContextGovernor().snip_history(_governance_config(provider, tools, spec), messages)

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


# ---------------------------------------------------------------------------
# Malformed tool_call name guard (missing/non-string name wedges the session
# upstream: messages.content.N.tool_use.name: Input should be a valid string)
# ---------------------------------------------------------------------------


def test_drop_malformed_tool_calls_trims_response():
    """LLM response tool_calls with a missing/empty name are dropped in place."""
    from nanobot.agent.runner import AgentRunner

    response = LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(id="1", name=None, arguments={}),
            ToolCallRequest(id="2", name="", arguments={}),
            ToolCallRequest(id="3", name="read_file", arguments={}),
        ],
        finish_reason="tool_calls",
    )
    dropped, all_dropped, orig = AgentRunner._drop_malformed_tool_calls(response)
    assert [tc.name for tc in response.tool_calls] == ["read_file"]
    assert response.finish_reason == "tool_calls"
    assert response.should_execute_tools is True
    assert dropped == 2
    assert all_dropped is False
    assert orig == "tool_calls"


def test_drop_malformed_tool_calls_all_bad_disables_execution():
    """If every tool call is malformed, execution is disabled (no empty exec)."""
    from nanobot.agent.runner import AgentRunner

    response = LLMResponse(
        content="some text",
        tool_calls=[ToolCallRequest(id="1", name=None, arguments={})],
        finish_reason="tool_calls",
    )
    dropped, all_dropped, orig = AgentRunner._drop_malformed_tool_calls(response)
    assert response.tool_calls == []
    assert response.finish_reason == "stop"
    assert response.should_execute_tools is False
    assert dropped == 1
    assert all_dropped is True
    assert orig == "tool_calls"


def test_drop_malformed_returns_tuple_no_calls():
    """No tool calls returns (0, False, current_finish_reason)."""
    from nanobot.agent.runner import AgentRunner

    response = LLMResponse(content="hi", finish_reason="stop")
    dropped, all_dropped, orig = AgentRunner._drop_malformed_tool_calls(response)
    assert dropped == 0
    assert all_dropped is False
    assert orig == "stop"


def test_strip_malformed_tool_calls_keeps_valid_calls_in_history():
    """A mixed assistant turn keeps only its valid tool_calls."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "bad", "type": "function", "function": {"name": None, "arguments": "{}"}},
                {"id": "ok", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "ok", "name": "exec", "content": "done"},
    ]
    result = ContextGovernor.strip_malformed_tool_calls(messages)
    assert result is not messages  # copied, original untouched
    assert len(messages[1]["tool_calls"]) == 2  # original preserved
    kept = result[1]["tool_calls"]
    assert [tc["function"]["name"] for tc in kept] == ["exec"]


def test_strip_malformed_tool_calls_drops_empty_assistant_turn():
    """An assistant turn that is only a malformed call is removed entirely;
    the existing orphan-result cleanup then drops its dangling tool result,
    so a polluted session self-heals."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "bad", "type": "function", "function": {"name": None, "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "bad", "name": "", "content": "r"},
    ]
    stripped = ContextGovernor.strip_malformed_tool_calls(messages)
    assert [m["role"] for m in stripped] == ["user", "tool"]
    healed = ContextGovernor.drop_orphan_tool_results(stripped)
    assert [m["role"] for m in healed] == ["user"]


def test_strip_malformed_tool_calls_noop_when_clean():
    """Clean history is returned unchanged (same object)."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "ok", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "ok", "name": "exec", "content": "done"},
    ]
    assert ContextGovernor.strip_malformed_tool_calls(messages) is messages


def test_strip_placeholder_assistant_messages_removes_omitted():
    """Placeholder assistant messages are removed; real messages kept."""
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "real response"},
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "[Previous assistant message omitted.]"},
        {"role": "user", "content": "?"},
        {"role": "assistant", "content": "[Previous assistant message omitted.]"},
        {"role": "user", "content": "hello"},
    ]
    result = ContextGovernor.strip_placeholder_assistant_messages(messages)
    assert [m["role"] for m in result] == [
        "user", "assistant", "user", "user", "user",
    ]
    assert result[1]["content"] == "real response"


def test_strip_placeholder_noop_when_clean():
    """Clean history is returned unchanged (same object)."""
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello back"},
    ]
    assert ContextGovernor.strip_placeholder_assistant_messages(messages) is messages


def test_strip_placeholder_keeps_assistant_with_tool_calls():
    """A placeholder assistant that also carries tool_calls is kept."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "[Previous assistant message omitted.]",
            "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "1", "name": "exec", "content": "done"},
    ]
    result = ContextGovernor.strip_placeholder_assistant_messages(messages)
    assert result is messages
