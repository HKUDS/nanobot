"""Tests for in-process subagent delegation (plan3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.compactor import ContextCompactor
from nanobot.agent.delegation import (
    ContextIsolator,
    DelegationPlan,
    FileScope,
    ScopedDelegationRunner,
    SubagentOrchestrator,
    SubagentResult,
    SubagentStatus,
    SubagentTask,
)
from nanobot.agent.memory import MemoryStore
from nanobot.config.schema import ExecToolConfig, WebToolsConfig
from nanobot.providers.base import LLMResponse


def test_file_scope_fnmatch() -> None:
    scope = FileScope(readable=["src/**/*.py"], writable=["src/a.py"])
    assert scope.can_read("src/foo/bar.py")
    assert not scope.can_read("docs/x.md")
    assert scope.can_write("src/a.py")
    assert not scope.can_write("src/b.py")


def test_subagent_task_id_autogen() -> None:
    t = SubagentTask(objective="hello world")
    assert t.id.startswith("sub_")


def test_context_isolator_contains_objective() -> None:
    task = SubagentTask(
        id="t1",
        objective="Fix the bug",
        file_contents={"a.py": "x = 1"},
        scope=FileScope(readable=["*.py"], writable=["*.py"]),
    )
    ctx = ContextIsolator.build_context(task)
    assert "Fix the bug" in ctx
    assert "<files>" in ctx


def test_plan_delegation_groups_by_directory(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    compactor = ContextCompactor(store, budget=50_000)
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    orch = SubagentOrchestrator(
        provider,
        compactor,
        tmp_path,
        model="test-model",
        exec_config=ExecToolConfig(enable=False),
        web_config=WebToolsConfig(enable=False),
    )
    files = {
        "src/a.py": "a",
        "src/b.py": "b",
        "README.md": "r",
    }
    plan = orch.plan_delegation("Implement feature", files)
    assert plan.task_count() >= 2
    assert "directory" in plan.rationale.lower() or plan.task_count() >= 1


def test_merge_results_detects_conflict(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    compactor = ContextCompactor(store, budget=50_000)
    provider = MagicMock()
    provider.get_default_model.return_value = "m"
    orch = SubagentOrchestrator(
        provider,
        compactor,
        tmp_path,
        exec_config=ExecToolConfig(enable=False),
        web_config=WebToolsConfig(enable=False),
    )
    r1 = SubagentResult(
        task_id="a",
        status=SubagentStatus.COMPLETED,
        summary="ok",
        file_changes={"x.py": "v1"},
    )
    r2 = SubagentResult(
        task_id="b",
        status=SubagentStatus.COMPLETED,
        summary="ok2",
        file_changes={"x.py": "v2"},
    )
    report = orch.merge_results([r1, r2])
    assert "x.py" in report.file_changes
    assert any("CONFLICT" in c for c in report.conflicts)
    assert report.success is False


def test_merge_results_all_ok(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    compactor = ContextCompactor(store, budget=50_000)
    provider = MagicMock()
    provider.get_default_model.return_value = "m"
    orch = SubagentOrchestrator(
        provider,
        compactor,
        tmp_path,
        exec_config=ExecToolConfig(enable=False),
        web_config=WebToolsConfig(enable=False),
    )
    r1 = SubagentResult(
        task_id="a",
        status=SubagentStatus.COMPLETED,
        summary="ok",
        file_changes={"a.py": "1"},
    )
    r2 = SubagentResult(
        task_id="b",
        status=SubagentStatus.COMPLETED,
        summary="ok2",
        file_changes={"b.py": "2"},
    )
    report = orch.merge_results([r1, r2])
    assert report.success is True
    assert len(report.file_changes) == 2


@pytest.mark.asyncio
async def test_scoped_runner_single_turn_no_tools(tmp_path) -> None:
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(
            content="Summary: task finished.",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        ),
    )
    runner = ScopedDelegationRunner(
        provider,
        tmp_path,
        "test-model",
        exec_config=ExecToolConfig(enable=False),
        web_config=WebToolsConfig(enable=False),
    )
    task = SubagentTask(
        objective="Say hello",
        scope=FileScope(readable=["**/*"], writable=[]),
    )
    result = await runner.run(task)
    assert result.status == SubagentStatus.COMPLETED
    assert "finished" in result.summary.lower() or "Summary" in result.summary


@pytest.mark.asyncio
async def test_orchestrator_execute_invokes_runner_and_compactor(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    compactor = ContextCompactor(store, budget=100_000)
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    orch = SubagentOrchestrator(
        provider,
        compactor,
        tmp_path,
        model="test-model",
        max_concurrent=2,
        exec_config=ExecToolConfig(enable=False),
        web_config=WebToolsConfig(enable=False),
    )
    fake = SubagentResult(
        task_id="sub_t1",
        status=SubagentStatus.COMPLETED,
        summary="done",
    )
    with patch.object(
        orch._runner,
        "run",
        new_callable=AsyncMock,
        return_value=fake,
    ):
        plan = DelegationPlan(
            waves=[
                [
                    SubagentTask(
                        id="sub_t1",
                        objective="task one",
                        scope=FileScope(readable=["*.md"], writable=[]),
                    ),
                ],
            ],
        )
        results = await orch.execute(plan)
    assert len(results) == 1
    assert results[0].task_id == "sub_t1"
    assert compactor.stats()["total_turns"] >= 1
