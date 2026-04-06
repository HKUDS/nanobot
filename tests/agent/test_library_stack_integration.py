"""
End-to-end style smoke: plan1 memory + plan2 compactor + plan3 delegation wiring.

Uses mocks for LLM-backed delegation runs; exercises real MemoryStore and
ContextCompactor together with SubagentOrchestrator.execute.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.compactor import ContextCompactor
from nanobot.agent.delegation import (
    ScopedDelegationRunner,
    SubagentOrchestrator,
    SubagentResult,
    SubagentStatus,
    SubagentTask,
)
from nanobot.agent.delegation import FileScope as DelegationFileScope
from nanobot.agent.memory import MemoryStore
from nanobot.config.schema import ExecToolConfig, WebToolsConfig
from nanobot.providers.base import LLMResponse


def test_nanobot_agent_exports_memory_compactor_delegation() -> None:
    """Public API surface for plan1–3 features."""
    from nanobot.agent import (
        ContextCompactor,
        FileScope,
        MemoryEntry,
        MemoryStore,
        SubagentOrchestrator,
        SubagentResult,
        SubagentTask,
        estimate_tokens,
    )

    assert estimate_tokens("abc") >= 1
    assert MemoryEntry is not None
    assert ContextCompactor is not None
    assert FileScope is DelegationFileScope


@pytest.mark.asyncio
async def test_memory_compactor_delegation_chain(tmp_path) -> None:
    """Memory index + compactor layers + orchestration push + meta."""
    store = MemoryStore(tmp_path)
    store.write_memory("# project\n- note")
    store.bump_session_count()
    store.remember("persisted fact", category="project", topic="facts")

    compactor = ContextCompactor(store, budget=80_000)
    compactor.push("system", "Parent system", protected=True)
    compactor.push("user", "Do something")
    rendered = compactor.render()
    assert "<memory_index>" in rendered
    assert "<recent_conversation>" in rendered

    provider = MagicMock()
    provider.get_default_model.return_value = "integration-model"
    orch = SubagentOrchestrator(
        provider,
        compactor,
        tmp_path,
        model="integration-model",
        max_concurrent=2,
        exec_config=ExecToolConfig(enable=False),
        web_config=WebToolsConfig(enable=False),
    )

    fake = SubagentResult(
        task_id="sub_wave",
        status=SubagentStatus.COMPLETED,
        summary="Wave completed.",
    )
    with patch.object(orch._runner, "run", new_callable=AsyncMock, return_value=fake):
        plan = orch.plan_delegation(
            "Refactor modules",
            {"src/a.py": "x = 1", "src/b.py": "y = 2"},
        )
        assert plan.task_count() >= 1
        results = await orch.execute(plan)

    assert len(results) == 1
    assert results[0].summary == "Wave completed."
    assert compactor.stats()["total_turns"] >= 3
    assert "topics_count" in store.stats()


@pytest.mark.asyncio
async def test_scoped_runner_with_mock_llm_round_trip(tmp_path) -> None:
    """Single delegated task completes via AgentRunner + mock provider."""
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(
            content="Observation: done.\nSummary: finished.",
            tool_calls=[],
            usage={"prompt_tokens": 3, "completion_tokens": 2},
        ),
    )
    runner = ScopedDelegationRunner(
        provider,
        tmp_path,
        "integration-model",
        exec_config=ExecToolConfig(enable=False),
        web_config=WebToolsConfig(enable=False),
    )
    task = SubagentTask(
        objective="Verify integration",
        scope=DelegationFileScope(readable=["**/*"], writable=[]),
    )
    result = await runner.run(task)
    assert result.status == SubagentStatus.COMPLETED
    assert result.task_id
