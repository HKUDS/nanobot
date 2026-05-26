"""GEPA end-to-end integration: run → proposal → apply_update → git (E4-G3)."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from nanobot.agent.evolution.gepa_dataset import GepaEvalExample
from nanobot.agent.evolution.gepa_optimizer import GepaOptimizeResult
from nanobot.agent.evolution.gepa_runner import GepaRunner
from nanobot.agent.evolution.gepa_skill_module import GepaSkillModule
from nanobot.agent.evolution.git_store import EvolutionGitStore
from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace
from nanobot.agent.evolution.proposals import ProposalStore
from nanobot.agent.evolution.trace_store import TraceStore
from nanobot.config.schema import EvolutionConfig, EvolutionGepaConfig
from nanobot.providers.base import LLMProvider, LLMResponse

_SKILL_MD = """---
name: deploy-k8s
description: Deploy workloads to Kubernetes clusters
---

# Deploy K8s

## Steps
1. kubectl apply -f manifest.yaml
"""

_EVOLVED_BODY = """# Deploy K8s

## Steps
1. kubectl apply -f manifest.yaml
2. kubectl rollout status deploy/nginx
"""


class _DummyProvider(LLMProvider):
    async def chat(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(content="", tool_calls=[])

    def get_default_model(self) -> str:
        return "test-model"


class _MockOptimizer:
    def optimize(
        self,
        skill_module: GepaSkillModule,
        trainset: Sequence[GepaEvalExample],
        valset: Sequence[GepaEvalExample] | None = None,
    ) -> GepaOptimizeResult:
        _ = valset
        skill_module.body = _EVOLVED_BODY
        return GepaOptimizeResult(
            skill_name=skill_module.skill_name,
            skill_md=skill_module.to_skill_md(),
            evaluation_score=0.9,
            baseline_score=0.5,
            improved=True,
            trace_ids=tuple(example.trace_id for example in trainset),
        )


def _seed_skill(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "deploy-k8s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")


def _insert_traces(store: TraceStore, skill_name: str, count: int = 3) -> None:
    for index in range(count):
        store.insert(
            TurnTrace(
                session_key="cli:direct",
                query=f"deploy task {index}",
                trace_id=f"trace-{index}",
                skills_injected=(skill_name,),
                tool_calls=(
                    ToolCallRecord(name="exec", args_summary="kubectl apply -f nginx.yaml"),
                ),
                tool_call_count=3,
                stop_reason="completed",
                outcome="success",
            )
        )


@pytest.fixture
def _patch_evolution_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.agent.evolution.gepa_runner.require_evolution_extra",
        lambda: None,
    )


@pytest.mark.asyncio
async def test_gepa_run_then_apply_update_records_git(
    tmp_path: Path,
    _patch_evolution_extra: None,
) -> None:
    """Mock GEPA run → pending proposal → apply_update → evolve git message."""
    _seed_skill(tmp_path)
    trace_store = TraceStore(tmp_path)
    _insert_traces(trace_store, "deploy-k8s")

    proposals = ProposalStore(tmp_path)
    git = EvolutionGitStore(tmp_path)
    git.init()
    git.commit_create("deploy-k8s")

    evolution = EvolutionConfig(enable=True, gepa=EvolutionGepaConfig(enable=True))
    runner = GepaRunner(
        tmp_path,
        evolution,
        _DummyProvider(),
        optimizer=_MockOptimizer(),
        evaluator=None,
    )
    run_result = await runner.run(skill_name="deploy-k8s", trigger="cli")

    assert run_result.phase == "completed"
    assert len(run_result.proposals_created) == 1
    proposal_id = run_result.proposals_created[0]

    meta = proposals.read_meta(proposal_id)
    assert meta is not None
    assert meta.source == "gepa"
    assert meta.resolved_proposal_kind() == "update"
    assert meta.evaluation_score == pytest.approx(0.9)

    apply_result = proposals.apply_update(proposal_id, git_store=git)

    assert apply_result.ok is True
    active_md = (tmp_path / "skills" / "deploy-k8s" / "SKILL.md").read_text(encoding="utf-8")
    assert "rollout status" in active_md
    assert git.log()[0].message == "evolve: update skill deploy-k8s (gepa)"
    assert trace_store.list_for_gepa(min_tool_calls=1, unused_only=True) == []
