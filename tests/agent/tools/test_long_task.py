"""Tests for Long Task Tool: HandoffTool, CompleteTool, LongTaskTool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.long_task import (
    _IMPLICIT_HANDOFF_TAG,
    CompleteTool,
    HandoffState,
    HandoffTool,
    LongTaskTool,
    _build_system_prompt,
    _build_user_message,
    _cumulative_block_for_step,
    _extract_file_changes,
    _extract_handoff_from_messages,
    _strip_redundant_tail_block,
)
from nanobot.bus.events import OUTBOUND_META_AGENT_UI

_COMPLETION_PREFIX = (
    "The task is complete. This is the final answer — "
    "present it to the user directly without calling additional "
    "tools or reading files.\n\n"
)


def _wrapped_completion(summary: str) -> str:
    """Matches LongTaskTool return shape after successful validation."""
    return f"{_COMPLETION_PREFIX}{summary}"


# ---------------------------------------------------------------------------
# Signal tool tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handoff_tool_stores_structured_signal():
    store = HandoffState()
    tool = HandoffTool(store)
    result = await tool.execute(
        message="Processed items 1-8. Results in out.md.",
        files_created=["out.md", "report.md"],
        files_modified=["main.py"],
        next_step_hint="Continue with item 9.",
        verification="Tests passed",
    )
    assert result == "Progress recorded. The next step will continue from here."
    assert store.signal_type == "handoff"
    assert store.message == "Processed items 1-8. Results in out.md."
    assert store.files_created == ["out.md", "report.md"]
    assert store.files_modified == ["main.py"]
    assert store.next_step_hint == "Continue with item 9."
    assert store.verification == "Tests passed"


@pytest.mark.asyncio
async def test_handoff_tool_defaults_optional_fields():
    store = HandoffState()
    tool = HandoffTool(store)
    await tool.execute(message="Done.")
    assert store.files_created == []
    assert store.files_modified == []
    assert store.next_step_hint == ""
    assert store.verification == ""


@pytest.mark.asyncio
async def test_complete_tool_stores_signal():
    store = HandoffState()
    tool = CompleteTool(store)
    result = await tool.execute(summary="All 100 items processed. Summary in report.md")
    assert result == "Task marked as complete. Awaiting validation."
    assert store.signal_type == "complete"
    assert store.message == "All 100 items processed. Summary in report.md"


@pytest.mark.asyncio
async def test_signal_tools_overwrite_on_multiple_calls():
    """Last call wins — the orchestrator only reads the final signal."""
    store = HandoffState()
    handoff = HandoffTool(store)
    complete = CompleteTool(store)
    await handoff.execute(message="first progress")
    assert store.message == "first progress"
    await complete.execute(summary="done early")
    assert store.signal_type == "complete"
    assert store.message == "done early"


# ---------------------------------------------------------------------------
# Helper: minimal SubagentManager stub
# ---------------------------------------------------------------------------


def _make_manager_stub():
    """Create a minimal SubagentManager stub with a mockable run_step."""
    mgr = MagicMock()
    mgr.run_step = AsyncMock()
    return mgr


def _step_result(**overrides):
    """Create a minimal AgentRunResult-like namespace."""
    defaults = dict(
        final_content="step done",
        messages=[],
        tool_events=[],
        stop_reason="completed",
        tools_used=[],
        usage={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# LongTaskTool orchestrator tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_task_publishes_agent_ui_on_bus_metadata():
    """Structured UI rides on OutboundMessage.metadata for any channel to forward."""
    from nanobot.agent.tools.context import RequestContext

    mgr = _make_manager_stub()
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="All done. Report in summary.md")
            return _step_result(
                final_content="All done.",
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Validated")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr, bus=bus)
    tool.set_context(RequestContext(channel="websocket", chat_id="chat-1", metadata={}))
    await tool.execute(goal="Audit all issues.")
    published = [call.args[0] for call in bus.publish_outbound.await_args_list]
    with_ui = [m for m in published if m.metadata.get(OUTBOUND_META_AGENT_UI)]
    assert with_ui, "expected at least one outbound with agent UI metadata"
    first = with_ui[0].metadata[OUTBOUND_META_AGENT_UI]
    assert first["kind"] == "long_task"
    assert first["data"]["event"] == "task_start"
    assert first["data"]["run_id"]
    events = {m.metadata[OUTBOUND_META_AGENT_UI]["data"]["event"] for m in with_ui}
    assert "task_complete" in events


@pytest.mark.asyncio
async def test_long_task_completes_in_one_step():
    """Subagent calls complete() immediately, validation passes."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="All done. Report in summary.md")
            return _step_result(
                final_content="All done.",
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        else:
            # Validation round
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Validated")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Audit all issues.")
    assert result == _wrapped_completion("All done. Report in summary.md")
    assert call_count == 2  # main step + validation


@pytest.mark.asyncio
async def test_long_task_completes_after_multiple_handoffs():
    """Subagent calls handoff() twice then complete(), validation passes."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            for t in extra_tools:
                if t.name == "handoff":
                    await t.execute(message="Processed 1-8.")
            return _step_result(
                tools_used=["handoff"],
                tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
            )
        elif call_count == 2:
            assert "Processed 1-8." in user_message
            assert "Step 2 of 20" in user_message
            assert "Previous Progress" in user_message
            # Last handoff is only under Previous Progress — not duplicated in run history.
            assert "Run history" not in user_message
            assert "#### Step 1" not in user_message
            for t in extra_tools:
                if t.name == "handoff":
                    await t.execute(message="Processed 9-16.")
            return _step_result(
                tools_used=["handoff"],
                tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
            )
        elif call_count == 3:
            assert "Run history" in user_message
            assert "#### Step 1" in user_message
            assert "#### Step 2" not in user_message
            assert "Processed 1-8." in user_message
            assert "Processed 9-16." in user_message
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="All 16 items audited.")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        else:
            # Validation round
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Validated")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Audit 16 issues.")
    assert result == _wrapped_completion("All 16 items audited.")
    assert call_count == 4  # 3 main steps + validation


@pytest.mark.asyncio
async def test_long_task_uses_last_signal_when_multiple_signals_called():
    """If a step calls handoff() then complete(), complete() should win."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            for t in extra_tools:
                if t.name == "handoff":
                    await t.execute(message="Partial progress.")
                elif t.name == "complete":
                    await t.execute(summary="Actually complete.")
            return _step_result(
                tools_used=["handoff", "complete"],
                tool_events=[
                    {"name": "handoff", "status": "ok", "detail": ""},
                    {"name": "complete", "status": "ok", "detail": ""},
                ],
            )

        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Validated")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Do something.", max_steps=1)
    assert result == _wrapped_completion("Actually complete.")
    assert call_count == 2  # main step + validation


@pytest.mark.asyncio
async def test_long_task_validation_falls_back_to_handoff():
    """Subagent claims complete but validation fails — task continues."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First step claims complete
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Done.")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        elif call_count == 2:
            # Validation round fails (handoff called)
            for t in extra_tools:
                if t.name == "handoff":
                    await t.execute(message="Not actually done. Need more work.")
            return _step_result(
                tools_used=["handoff"],
                tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
            )
        elif call_count == 3:
            # Continue and complete for real
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Really done.")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        else:
            # Second validation passes
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Validated")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Do something.", max_steps=5)
    assert result == _wrapped_completion("Really done.")
    assert call_count == 4


@pytest.mark.asyncio
async def test_long_task_fallback_when_no_signal_called():
    """Subagent doesn't call handoff/complete — extract progress from messages."""
    mgr = _make_manager_stub()

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        return _step_result(
            final_content="Tool budget exhausted.",
            messages=[
                {"role": "system", "content": "..."},
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "I processed items 1-5. Results in out.md."},
                {"role": "tool", "content": "ok"},
                {"role": "assistant", "content": "Tool budget exhausted. Call handoff() earlier next time."},
            ],
            stop_reason="max_iterations",
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Do something.", max_steps=2)
    # Should reach max_steps and return the fallback extracted from messages
    assert "max steps (2)" in result
    assert "I processed items 1-5" in result


@pytest.mark.asyncio
async def test_long_task_auto_extracts_on_natural_end():
    """Subagent finishes naturally (stop_reason=completed) without calling signal."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _step_result(
                final_content="I processed items 1-5. Results in out.md.",
                stop_reason="completed",
            )
        elif call_count == 2:
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="All done.")
            return _step_result(
                final_content="All done.",
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        else:
            # Validation
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Validated")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Process items.", max_steps=5)
    assert result == _wrapped_completion("All done.")
    assert call_count == 3


@pytest.mark.asyncio
async def test_long_task_retries_on_crash():
    """A step that crashes once should be retried."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated crash")
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Recovered.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Test retry.")
    assert result == _wrapped_completion("Recovered.")
    assert call_count == 3  # main step + retry + validation


@pytest.mark.asyncio
async def test_long_task_fails_after_two_crashes():
    """A step that crashes twice should terminate the task."""
    mgr = _make_manager_stub()

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        raise RuntimeError("Persistent crash")

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Test failure.", max_steps=3)
    assert "failed at step 1/3" in result
    assert tool.status == "error"


@pytest.mark.asyncio
async def test_long_task_uses_dynamic_budget():
    """Final steps should use lower max_iterations."""
    mgr = _make_manager_stub()
    captured_budgets = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        captured_budgets.append(max_iterations)
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Done.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    await tool.execute(goal="Test budget.", max_steps=5)
    # Step 0-2 should use 8, step 3+ should use 4
    # But we complete on step 0, so only one budget captured
    assert captured_budgets[0] == 8


# ---------------------------------------------------------------------------
# Hook and observability tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hooks_receive_events():
    """Registered hooks should be called during execution."""
    mgr = _make_manager_stub()
    events = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Done.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    tool.set_hooks({
        "on_task_start": lambda **kw: events.append(("task_start", kw)),
        "on_step_start": lambda **kw: events.append(("step_start", kw)),
        "on_step_complete": lambda **kw: events.append(("step_complete", kw)),
        "on_validation_started": lambda **kw: events.append(("validation_started", kw)),
        "on_task_complete": lambda **kw: events.append(("task_complete", kw)),
    })
    await tool.execute(goal="Test hooks.")

    assert any(e[0] == "task_start" for e in events)
    assert any(e[0] == "step_start" for e in events)
    assert any(e[0] == "step_complete" for e in events)
    assert any(e[0] == "validation_started" for e in events)
    assert any(e[0] == "task_complete" for e in events)


@pytest.mark.asyncio
async def test_catch_all_hook_receives_events():
    """The on_event catch-all hook should receive all events."""
    mgr = _make_manager_stub()
    events = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Done.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    tool.set_hooks({
        "on_event": lambda ev: events.append(ev.type),
    })
    await tool.execute(goal="Test catch-all.")

    assert "task_start" in events
    assert "step_start" in events
    assert "task_complete" in events


@pytest.mark.asyncio
async def test_state_exposure():
    """Properties should reflect current execution state."""
    mgr = _make_manager_stub()

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        for t in extra_tools:
            if t.name == "handoff":
                await t.execute(message="Progress.")
        return _step_result(
            tools_used=["handoff"],
            tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    assert tool.status == "idle"

    await tool.execute(goal="Test state.", max_steps=3)

    assert tool.goal == "Test state."
    assert tool.total_steps == 3
    assert tool.status == "error"  # max_steps reached
    assert tool.last_handoff.message == "Progress."


@pytest.mark.asyncio
async def test_inject_correction():
    """User correction should appear in the next step's user message."""
    mgr = _make_manager_stub()
    captured_messages = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        captured_messages.append(user_message)
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Done.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    tool.inject_correction("Focus on error handling.")
    await tool.execute(goal="Refactor code.")

    assert any("Focus on error handling" in msg for msg in captured_messages)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_build_system_prompt():
    prompt = _build_system_prompt(budget=8)
    assert "handoff()" in prompt
    assert "complete()" in prompt
    assert "8 tool calls" in prompt


def test_build_user_message_step_0():
    msg = _build_user_message("Audit all issues.", step=0, max_steps=20, handoff=HandoffState())
    assert "Audit all issues." in msg
    assert "Step 1 of 20" in msg
    assert "8 tool calls" in msg
    assert "Previous Progress" not in msg


def test_build_user_message_later_step():
    handoff = HandoffState(message="Did 1-10.", files_created=["a.py"], next_step_hint="Do Y")
    msg = _build_user_message("Audit all issues.", step=3, max_steps=20, handoff=handoff)
    assert "Audit all issues." in msg
    assert "Previous Progress" in msg
    assert "Did 1-10." in msg
    assert "a.py" in msg
    assert "Do Y" in msg
    assert "Step 4 of 20" in msg


def test_build_user_message_includes_cumulative_and_file_union():
    handoff = HandoffState(message="Last step only.")
    msg = _build_user_message(
        "G",
        step=2,
        max_steps=10,
        handoff=handoff,
        cumulative_history="#### Step 1\nearlier summary",
        all_files_created_so_far=["early.py", "new.py"],
        all_files_modified_so_far=["x.py"],
    )
    assert "Run history" in msg
    assert "earlier summary" in msg
    assert "All files touched so far" in msg
    assert "early.py" in msg and "new.py" in msg
    assert "x.py" in msg
    assert "Last step only." in msg


def test_strip_redundant_tail_block_drops_handoff_echo():
    earlier = HandoffState(message="chunk A")
    last = HandoffState(message="chunk B", next_step_hint="do C")
    b0 = _cumulative_block_for_step(0, earlier, body_max_chars=2500)
    b1 = _cumulative_block_for_step(1, last, body_max_chars=2500)
    out = _strip_redundant_tail_block(
        [b0, b1], step=2, handoff=last, body_max_chars=2500
    )
    assert out == [b0]


def test_strip_redundant_tail_block_drops_implicit_echo():
    h = HandoffState(message="implicit done")
    stored = _cumulative_block_for_step(
        0, h, tag=_IMPLICIT_HANDOFF_TAG, body_max_chars=2500
    )
    out = _strip_redundant_tail_block(
        [stored], step=1, handoff=h, body_max_chars=2500
    )
    assert out == []


def test_strip_redundant_tail_block_keeps_non_handoff_tail():
    h = HandoffState(message="continue", next_step_hint="fix tests")
    blocks = [
        "#### Step 2 — validation failed\nCompletion claim was rejected\nClaim summary:\nfoo"
    ]
    out = _strip_redundant_tail_block(blocks, step=3, handoff=h, body_max_chars=2500)
    assert out == blocks


def test_cumulative_block_respects_body_max():
    body = "x" * 200
    block = _cumulative_block_for_step(
        0, HandoffState(message=body), body_max_chars=80
    )
    assert "[... truncated ...]" in block


@pytest.mark.asyncio
async def test_long_task_accepts_cumulative_size_overrides():
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Done")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="ok")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    await tool.execute(
        goal="G",
        max_steps=2,
        cumulative_prompt_max_chars=6000,
        cumulative_step_body_max_chars=900,
    )
    assert tool._cumulative_prompt_max_chars == 6000
    assert tool._cumulative_step_body_max_chars == 900


def test_build_user_message_final_step():
    handoff = HandoffState(message="Almost done.")
    msg = _build_user_message("Audit all issues.", step=18, max_steps=20, handoff=handoff)
    assert "FINAL Step" in msg
    assert "4 tool calls" in msg  # final steps use lower budget


def test_build_user_message_with_correction():
    msg = _build_user_message(
        "Audit.", step=0, max_steps=20, handoff=HandoffState(), correction="Skip file A"
    )
    assert "User Correction" in msg
    assert "Skip file A" in msg


def test_extract_handoff_from_messages():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": ""},
        {"role": "tool", "content": "result"},
        {"role": "assistant", "content": "I processed items 1-3."},
    ]
    assert _extract_handoff_from_messages(messages) == "I processed items 1-3."


def test_extract_handoff_skips_budget_message():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": "I processed items 1-3."},
        {"role": "tool", "content": "result"},
        {"role": "assistant", "content": "Tool budget exhausted. Call handoff() earlier."},
    ]
    # Should skip the budget message and find the actual progress
    assert _extract_handoff_from_messages(messages) == "I processed items 1-3."


def test_extract_handoff_from_empty_messages():
    assert _extract_handoff_from_messages([]) == ""
    assert _extract_handoff_from_messages([{"role": "system", "content": "sys"}]) == ""


def test_extract_file_changes_from_tool_events():
    events = [
        {
            "name": "write_file",
            "status": "ok",
            "detail": "Successfully wrote 12 characters to /workspace/a.py",
        },
        {
            "name": "edit_file",
            "status": "ok",
            "detail": "Successfully edited /workspace/b.py",
        },
        {
            "name": "edit_file",
            "status": "ok",
            "detail": "Successfully created /workspace/c.py",
        },
        {"name": "read_file", "status": "ok", "detail": "Read /workspace/c.py"},
        {"name": "write_file", "status": "error", "detail": "Failed"},
    ]
    created, modified = _extract_file_changes(events)
    assert created == ["/workspace/a.py"]
    assert modified == ["/workspace/b.py", "/workspace/c.py"]


def test_extract_file_changes_empty():
    assert _extract_file_changes([]) == ([], [])


# ---------------------------------------------------------------------------
# Boundary and edge-case tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validation_step_crash_continues_task():
    """If the validation round itself crashes, the task should continue, not die."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Claimed done.")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        elif call_count == 2:
            # Validation round crashes
            raise RuntimeError("Validator exploded")
        else:
            # After validation crash, task continues and completes for real
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Actually done.")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Test validation crash.", max_steps=5)
    assert result == _wrapped_completion("Actually done.")
    assert call_count == 4  # main step + validation crash + continue + re-validation


@pytest.mark.asyncio
async def test_hook_exception_does_not_stop_execution():
    """A misbehaving hook must not break the long-task execution."""
    mgr = _make_manager_stub()

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Done.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    tool.set_hooks({
        "on_step_start": lambda **kw: (_ for _ in ()).throw(RuntimeError("bad hook")),
        "on_event": lambda ev: (_ for _ in ()).throw(RuntimeError("bad catch-all")),
    })
    result = await tool.execute(goal="Test hook resilience.")
    assert result == _wrapped_completion("Done.")


@pytest.mark.asyncio
async def test_inject_correction_during_execution():
    """Correction injected while the task is running should reach the next step."""
    import asyncio

    mgr = _make_manager_stub()
    step1_done = asyncio.Event()
    captured_messages = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        captured_messages.append(user_message)
        if len(captured_messages) == 1:
            for t in extra_tools:
                if t.name == "handoff":
                    await t.execute(message="Step 1 done.")
            step1_done.set()
            await asyncio.sleep(0)  # yield so the test coroutine can inject correction
            return _step_result(
                tools_used=["handoff"],
                tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
            )
        else:
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Step 2 done.")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)

    task = asyncio.create_task(tool.execute(goal="Test mid-run correction.", max_steps=5))
    await step1_done.wait()
    tool.inject_correction("Change direction.")
    result = await task

    assert result == _wrapped_completion("Step 2 done.")
    assert any("Change direction." in msg for msg in captured_messages)


@pytest.mark.asyncio
async def test_multiple_corrections_consumed_in_order():
    """Multiple corrections should be consumed FIFO across steps."""
    mgr = _make_manager_stub()
    captured_messages = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        captured_messages.append(user_message)
        for t in extra_tools:
            if t.name == "handoff":
                await t.execute(message=f"Step {len(captured_messages)} done.")
        return _step_result(
            tools_used=["handoff"],
            tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    tool.inject_correction("First correction.")
    tool.inject_correction("Second correction.")
    await tool.execute(goal="Test FIFO.", max_steps=3)

    # Step 0 should see First correction, step 1 should see Second
    assert any("First correction." in msg for msg in captured_messages)
    assert any("Second correction." in msg for msg in captured_messages)
    # Verify ordering: First appears in an earlier index than Second
    first_idx = next(i for i, msg in enumerate(captured_messages) if "First correction." in msg)
    second_idx = next(i for i, msg in enumerate(captured_messages) if "Second correction." in msg)
    assert first_idx < second_idx


@pytest.mark.asyncio
async def test_explicit_file_changes_override_auto_detected():
    """If subagent explicitly reports files_created, auto-detection must not overwrite."""
    mgr = _make_manager_stub()

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        for t in extra_tools:
            if t.name == "handoff":
                await t.execute(
                    message="Done.",
                    files_created=["explicit.py"],
                )
        return _step_result(
            tools_used=["handoff"],
            tool_events=[
                {"name": "handoff", "status": "ok", "detail": ""},
                # Auto-detection would pick this up as "auto.py"
                {
                    "name": "write_file",
                    "status": "ok",
                    "detail": "Successfully wrote 7 characters to auto.py",
                },
            ],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    await tool.execute(goal="Test file merge.", max_steps=2)

    # Explicit report should win over auto-detection
    assert tool.last_handoff.files_created == ["explicit.py"]


@pytest.mark.asyncio
async def test_max_steps_one_uses_final_budget():
    """max_steps=1 should immediately use the final-step budget of 4."""
    mgr = _make_manager_stub()
    captured_budgets = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        captured_budgets.append(max_iterations)
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Done.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    await tool.execute(goal="Test max_steps=1.", max_steps=1)
    assert captured_budgets[0] == 4  # final step budget
    assert captured_budgets[1] == 4  # validation also uses short budget


@pytest.mark.asyncio
async def test_budget_switches_at_correct_step():
    """With max_steps=5, budget should switch from 8 to 4 at step 3 (max_steps - 2)."""
    mgr = _make_manager_stub()
    captured_budgets = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        captured_budgets.append(max_iterations)
        for t in extra_tools:
            if t.name == "handoff":
                await t.execute(message=f"Step {len(captured_budgets)}.")
        return _step_result(
            tools_used=["handoff"],
            tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    await tool.execute(goal="Test budget switch.", max_steps=5)

    # Steps 0,1,2 use 8; steps 3,4 use 4
    assert captured_budgets[0] == 8
    assert captured_budgets[1] == 8
    assert captured_budgets[2] == 8
    assert captured_budgets[3] == 4
    assert captured_budgets[4] == 4


# ---------------------------------------------------------------------------
# Integration: verify LongTaskTool is wired into the main agent loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_task_registered_in_tool_registry(tmp_path):
    """Verify LongTaskTool appears in the main agent's tool registry."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    tool = loop.tools.get("long_task")
    assert tool is not None
    assert tool.name == "long_task"
