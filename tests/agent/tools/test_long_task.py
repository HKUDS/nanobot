"""Tests for Long Task Tool: HandoffTool, CompleteTool, LongTaskTool."""

import pytest
from types import SimpleNamespace

from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_handoff_tool_stores_signal():
    from nanobot.agent.tools.long_task import HandoffTool

    store: dict[str, str] = {}
    tool = HandoffTool(store)
    result = await tool.execute(message="Processed items 1-8. Results in out.md. Continue with item 9.")
    assert result == "Progress recorded. The next step will continue from here."
    assert store["type"] == "handoff"
    assert store["payload"] == "Processed items 1-8. Results in out.md. Continue with item 9."


@pytest.mark.asyncio
async def test_complete_tool_stores_signal():
    from nanobot.agent.tools.long_task import CompleteTool

    store: dict[str, str] = {}
    tool = CompleteTool(store)
    result = await tool.execute(summary="All 100 items processed. Summary in report.md")
    assert result == "Task marked as complete."
    assert store["type"] == "complete"
    assert store["payload"] == "All 100 items processed. Summary in report.md"


@pytest.mark.asyncio
async def test_signal_tools_overwrite_on_multiple_calls():
    """Last call wins -- the orchestrator only reads the final signal."""
    from nanobot.agent.tools.long_task import HandoffTool, CompleteTool

    store: dict[str, str] = {}
    handoff = HandoffTool(store)
    complete = CompleteTool(store)
    await handoff.execute(message="first progress")
    assert store["type"] == "handoff"
    await complete.execute(summary="done early")
    assert store["type"] == "complete"
    assert store["payload"] == "done early"


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
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# LongTaskTool orchestrator tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_task_completes_in_one_step():
    """Subagent calls complete() immediately."""
    from nanobot.agent.tools.long_task import LongTaskTool

    mgr = _make_manager_stub()

    async def fake_run_step(*, system_prompt, user_message, extra_tools):
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="All done. Report in summary.md")
        return _step_result(
            final_content="All done.",
            tools_used=["complete"],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Audit all issues.")
    assert result == "All done. Report in summary.md"


@pytest.mark.asyncio
async def test_long_task_completes_after_multiple_handoffs():
    """Subagent calls handoff() twice then complete()."""
    from nanobot.agent.tools.long_task import LongTaskTool

    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            for t in extra_tools:
                if t.name == "handoff":
                    await t.execute(message="Processed 1-8.")
        elif call_count == 2:
            assert "Processed 1-8." in user_message
            assert "8 tool calls" in user_message
            for t in extra_tools:
                if t.name == "handoff":
                    await t.execute(message="Processed 9-16.")
        else:
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="All 16 items audited.")
        return _step_result(tools_used=["handoff"])

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Audit 16 issues.")
    assert result == "All 16 items audited."
    assert call_count == 3


@pytest.mark.asyncio
async def test_long_task_fallback_when_no_signal_called():
    """Subagent doesn't call handoff/complete — extract progress from messages."""
    from nanobot.agent.tools.long_task import LongTaskTool

    mgr = _make_manager_stub()

    async def fake_run_step(*, system_prompt, user_message, extra_tools):
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
    from nanobot.agent.tools.long_task import LongTaskTool

    mgr = _make_manager_stub()
    steps = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools):
        nonlocal steps
        steps += 1
        if steps == 1:
            return _step_result(
                final_content="I processed items 1-5. Results in out.md.",
                stop_reason="completed",
            )
        # Second step: subagent calls complete
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="All done.")
        return _step_result(
            final_content="All done.",
            tools_used=["complete"],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Process items.", max_steps=5)
    assert "All done." == result
    assert steps == 2


@pytest.mark.asyncio
async def test_long_task_goal_appears_in_system_prompt():
    """Verify every step's system_prompt contains the long task system prompt."""
    from nanobot.agent.tools.long_task import LongTaskTool

    mgr = _make_manager_stub()
    captured_prompts = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools):
        captured_prompts.append(system_prompt)
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="done")
        return _step_result(final_content="done")

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    await tool.execute(goal="Audit everything.")
    assert len(captured_prompts) == 1
    assert "handoff()" in captured_prompts[0]
    assert "complete()" in captured_prompts[0]
    assert "filesystem" in captured_prompts[0]


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_build_user_message_step_0():
    from nanobot.agent.tools.long_task import _build_user_message

    msg = _build_user_message("Audit all issues.", step=0, handoff="")
    assert msg.startswith("Audit all issues.")
    assert "Step 1" in msg
    assert "8 tool calls" in msg
    assert "Previous Progress" not in msg


def test_build_user_message_later_step():
    from nanobot.agent.tools.long_task import _build_user_message

    msg = _build_user_message("Audit all issues.", step=3, handoff="Did 1-10.")
    assert "Audit all issues." in msg
    assert "Previous Progress" in msg
    assert "Did 1-10." in msg
    assert "Step 4" in msg
    assert "8 tool calls" in msg


def test_extract_handoff_from_messages():
    from nanobot.agent.tools.long_task import _extract_handoff_from_messages

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": ""},
        {"role": "tool", "content": "result"},
        {"role": "assistant", "content": "I processed items 1-3."},
    ]
    assert _extract_handoff_from_messages(messages) == "I processed items 1-3."


def test_extract_handoff_skips_budget_message():
    from nanobot.agent.tools.long_task import _extract_handoff_from_messages

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
    from nanobot.agent.tools.long_task import _extract_handoff_from_messages

    assert _extract_handoff_from_messages([]) == ""
    assert _extract_handoff_from_messages([{"role": "system", "content": "sys"}]) == ""


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
