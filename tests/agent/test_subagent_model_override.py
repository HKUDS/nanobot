"""Tests for SubagentManager model-tier override.

Verifies that reasoning_effort / max_tokens passed at construction time
propagate into AgentRunSpec when a subagent task is executed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.subagent import SubagentManager


def _mk_manager(
    *,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> SubagentManager:
    provider = MagicMock()
    provider.get_default_model.return_value = "main-model"
    bus = MagicMock()
    return SubagentManager(
        provider=provider,
        workspace=Path("/root/workspace/tmp/_subagent_model_test"),
        bus=bus,
        max_tool_result_chars=1024,
        model=model,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
    )


def test_default_none_reasoning_and_max_tokens():
    mgr = _mk_manager()
    assert mgr.reasoning_effort is None
    assert mgr.max_tokens is None


def test_accepts_reasoning_effort():
    mgr = _mk_manager(reasoning_effort="low")
    assert mgr.reasoning_effort == "low"


def test_accepts_max_tokens():
    mgr = _mk_manager(max_tokens=4096)
    assert mgr.max_tokens == 4096


@pytest.mark.asyncio
async def test_run_spec_includes_reasoning_and_max_tokens(tmp_path, monkeypatch):
    """关键集成点：config 字段 → SubagentManager → AgentRunSpec。"""
    mgr = _mk_manager(
        reasoning_effort="low",
        max_tokens=4096,
        model="subagent-model",
    )
    mgr.workspace = tmp_path

    captured: dict = {}

    async def _fake_run(spec):
        captured["spec"] = spec
        # 模拟 AgentRunResult 最小字段
        result = MagicMock()
        result.stop_reason = "completed"
        result.final_content = "done"
        result.tool_events = []
        result.error = None
        return result

    mgr.runner.run = _fake_run  # type: ignore[assignment]
    mgr._announce_result = AsyncMock()  # 避免 bus.publish_inbound 调用

    await mgr._run_subagent(
        task_id="t1",
        task="do something",
        label="t1",
        origin={"channel": "cli", "chat_id": "direct"},
    )

    spec = captured["spec"]
    assert spec.model == "subagent-model"
    assert spec.reasoning_effort == "low"
    assert spec.max_tokens == 4096
