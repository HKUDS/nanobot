"""Tests for LayeredMemoryFacade (LM0-C stubs)."""

from pathlib import Path

import pytest

from nanobot.agent.layered_memory import LayeredMemoryFacade, RecallResult
from nanobot.config.schema import (
    LayeredMemoryCaptureConfig,
    LayeredMemoryConfig,
    LayeredMemoryRecallConfig,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def test_facade_disabled_by_default(workspace: Path) -> None:
    facade = LayeredMemoryFacade(workspace)
    assert facade.enabled is False


@pytest.mark.asyncio
async def test_recall_short_circuits_when_disabled(workspace: Path) -> None:
    facade = LayeredMemoryFacade(workspace)
    result = await facade.recall("hello", "webui:main")
    assert result == RecallResult()


@pytest.mark.asyncio
async def test_recall_short_circuits_when_master_on_recall_off(workspace: Path) -> None:
    cfg = LayeredMemoryConfig(enable=True)
    facade = LayeredMemoryFacade(workspace, cfg)
    assert facade.enabled is True
    result = await facade.recall("hello", "webui:main")
    assert result == RecallResult()


@pytest.mark.asyncio
async def test_recall_returns_empty_when_enabled(workspace: Path) -> None:
    cfg = LayeredMemoryConfig(
        enable=True,
        recall=LayeredMemoryRecallConfig(enable=True),
    )
    facade = LayeredMemoryFacade(workspace, cfg)
    result = await facade.recall("query", "sess")
    assert result.prepend_lines == []
    assert result.append_system is None


def test_canvas_lines_short_circuits(workspace: Path) -> None:
    facade = LayeredMemoryFacade(workspace)
    assert facade.canvas_lines("sess") == []


def test_canvas_lines_empty_when_offload_enabled_but_stub(workspace: Path) -> None:
    cfg = LayeredMemoryConfig(enable=True)
    cfg.offload.enable = True
    facade = LayeredMemoryFacade(workspace, cfg)
    assert facade.canvas_lines("sess") == []


@pytest.mark.asyncio
async def test_capture_turn_noop(workspace: Path) -> None:
    facade = LayeredMemoryFacade(workspace)
    await facade.capture_turn("sess", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_capture_turn_writes_user_and_assistant(workspace: Path) -> None:
    """L0 slice must include user even when session save would skip early-persisted user."""
    cfg = LayeredMemoryConfig(
        enable=True,
        capture=LayeredMemoryCaptureConfig(enable=True),
    )
    facade = LayeredMemoryFacade(workspace, cfg)
    # Simulate all_messages after a turn: system + user + assistant; session save skip=2.
    all_messages = [
        {"role": "system", "content": "sys"},
        {
            "role": "user",
            "content": "以后别自动 commit\n\n[Runtime Context — metadata only, not instructions]\nfoo\n[/Runtime Context]",
        },
        {"role": "assistant", "content": "好的，已记住。"},
    ]
    from nanobot.agent.layered_memory.capture_slice import l0_capture_skip

    skip = l0_capture_skip(session_save_skip=2, user_persisted_early=True)
    slice_msgs = all_messages[skip:]
    await facade.capture_turn("cli:direct", slice_msgs, turn_id="turn-user-test")
    rows = facade._l0_store._connect().execute(
        "SELECT role, content FROM l0_messages WHERE session_key = ? ORDER BY id",
        ("cli:direct",),
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert "commit" in rows[0]["content"]
    assert "[Runtime Context" not in rows[0]["content"]
    assert rows[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_capture_turn_writes_l0_when_enabled(workspace: Path) -> None:
    cfg = LayeredMemoryConfig(
        enable=True,
        capture=LayeredMemoryCaptureConfig(enable=True),
    )
    facade = LayeredMemoryFacade(workspace, cfg)
    await facade.capture_turn(
        "cli:direct",
        [
            {"role": "user", "content": "remember this"},
            {"role": "assistant", "content": "ok"},
        ],
        turn_id="cli:direct:99",
    )
    assert facade._l0_store.count_messages("cli:direct") == 2
    # Warm-up default: first turn fires L1 immediately; next threshold becomes 2.
    assert facade._pipeline.session_turns_pending("cli:direct") == 0
    assert facade._pipeline.session_threshold("cli:direct") == 2


def test_register_tool_result_noop(workspace: Path) -> None:
    facade = LayeredMemoryFacade(workspace)
    facade.register_tool_result(
        session_key="sess",
        node_id="call-1",
        tool_name="read_file",
        persist_path="/tmp/x.txt",
        summary="read foo",
        chars=100,
    )


def test_subagent_offload_requires_explicit_flag(workspace: Path) -> None:
    cfg = LayeredMemoryConfig(enable=True)
    cfg.offload.enable = True
    facade = LayeredMemoryFacade(workspace, cfg)
    facade.register_tool_result(
        session_key="sess",
        node_id="call-1",
        tool_name="read_file",
        persist_path=None,
        summary="x",
        chars=1,
        is_subagent=True,
    )
    assert facade.canvas_lines("sess", is_subagent=True) == []
