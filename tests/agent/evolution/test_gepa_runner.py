"""Tests for GEPA runner orchestration (E4-D6/D7)."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest
from loguru import logger

from nanobot.agent.evolution.gepa_dataset import GepaEvalExample
from nanobot.agent.evolution.gepa_optimizer import GepaOptimizeResult
from nanobot.agent.evolution.gepa_runner import (
    GEPA_SKIP_ALREADY_RUNNING,
    GepaRunner,
    list_active_skill_names,
)
from nanobot.agent.evolution.gepa_skill_module import GepaSkillModule
from nanobot.agent.evolution.gepa_status import GepaRunLock, GepaRunStore
from nanobot.agent.evolution.models import ToolCallRecord
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
    def __init__(self, *, improved: bool = True) -> None:
        self.improved = improved
        self.calls = 0

    def optimize(
        self,
        skill_module: GepaSkillModule,
        trainset: Sequence[GepaEvalExample],
        valset: Sequence[GepaEvalExample] | None = None,
    ) -> GepaOptimizeResult:
        _ = valset
        self.calls += 1
        skill_module.body = _EVOLVED_BODY
        baseline = 0.5
        evolved = 0.9 if self.improved else 0.4
        return GepaOptimizeResult(
            skill_name=skill_module.skill_name,
            skill_md=skill_module.to_skill_md(),
            evaluation_score=evolved,
            baseline_score=baseline,
            improved=evolved > baseline,
            trace_ids=tuple(example.trace_id for example in trainset),
        )


def _insert_traces(store: TraceStore, skill_name: str, count: int = 3) -> None:
    from nanobot.agent.evolution.models import TurnTrace

    for index in range(count):
        store.insert(
            TurnTrace(
                session_key="cli:direct",
                query=f"deploy task {index}",
                trace_id=f"{skill_name}-trace-{index}",
                skills_injected=(skill_name,),
                tool_calls=(
                    ToolCallRecord(name="exec", args_summary="kubectl apply -f nginx.yaml"),
                ),
                tool_call_count=3,
                stop_reason="completed",
                outcome="success",
            )
        )


def _evolution_enabled() -> EvolutionConfig:
    return EvolutionConfig(enable=True, gepa=EvolutionGepaConfig(enable=True))


@pytest.fixture
def _patch_evolution_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.agent.evolution.gepa_runner.require_evolution_extra",
        lambda: None,
    )


@pytest.mark.asyncio
async def test_list_active_skill_names(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "deploy-k8s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    (tmp_path / "skills" / ".proposals").mkdir()

    assert list_active_skill_names(tmp_path) == ["deploy-k8s"]


def test_runner_uses_gepa_config_limits(tmp_path: Path) -> None:
    evolution = EvolutionConfig(
        enable=True,
        gepa=EvolutionGepaConfig(enable=True, min_traces=5, max_skills_per_run=2),
    )
    runner = GepaRunner(tmp_path, evolution, _DummyProvider())

    assert runner._min_traces == 5
    assert runner._max_skills_per_run == 2


@pytest.mark.asyncio
async def test_run_skipped_when_gepa_disabled(tmp_path: Path) -> None:
    runner = GepaRunner(
        tmp_path,
        EvolutionConfig(enable=True, gepa=EvolutionGepaConfig(enable=False)),
        _DummyProvider(),
    )
    result = await runner.run(trigger="cli")
    assert result.skipped is True
    assert runner.status_store.get().phase == "skipped"


@pytest.mark.asyncio
async def test_run_skipped_when_lock_held(tmp_path: Path, _patch_evolution_extra: None) -> None:
    lock = GepaRunLock(tmp_path)
    assert lock.try_acquire_run_lock() is True

    runner = GepaRunner(tmp_path, _evolution_enabled(), _DummyProvider())
    result = await runner.run(trigger="slash")

    assert result.phase == "skipped"
    assert result.message == GEPA_SKIP_ALREADY_RUNNING
    lock.release_run_lock()


@pytest.mark.asyncio
async def test_run_emits_structured_gepa_logs(
    tmp_path: Path,
    _patch_evolution_extra: None,
) -> None:
    skill_dir = tmp_path / "skills" / "deploy-k8s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")

    trace_store = TraceStore(tmp_path)
    _insert_traces(trace_store, "deploy-k8s")

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(message), format="{message}", level="DEBUG")

    try:
        runner = GepaRunner(
            tmp_path,
            _evolution_enabled(),
            _DummyProvider(),
            optimizer=_MockOptimizer(improved=True),
            evaluator=None,
        )
        await runner.run(skill_name="deploy-k8s", trigger="cli")
    finally:
        logger.remove(sink_id)

    joined = "\n".join(messages)
    assert "GEPA [start]" in joined
    assert "GEPA [select]" in joined
    assert "GEPA [optimize]" in joined
    assert "GEPA [dataset]" in joined
    assert "GEPA [optimized]" in joined
    assert "GEPA [proposal]" in joined
    assert "GEPA [done]" in joined


@pytest.mark.asyncio
async def test_run_respects_max_skills_per_run(
    tmp_path: Path,
    _patch_evolution_extra: None,
) -> None:
    for name in ("alpha-skill", "zulu-skill"):
        skill_dir = tmp_path / "skills" / name
        skill_dir.mkdir(parents=True)
        md = _SKILL_MD.replace("deploy-k8s", name).replace("Deploy workloads", f"Skill {name}")
        (skill_dir / "SKILL.md").write_text(md, encoding="utf-8")

    trace_store = TraceStore(tmp_path)
    _insert_traces(trace_store, "alpha-skill")
    _insert_traces(trace_store, "zulu-skill")

    optimizer = _MockOptimizer()
    evolution = EvolutionConfig(
        enable=True,
        gepa=EvolutionGepaConfig(enable=True, max_skills_per_run=1),
    )
    runner = GepaRunner(
        tmp_path,
        evolution,
        _DummyProvider(),
        optimizer=optimizer,
        evaluator=None,
    )
    result = await runner.run(trigger="cli")

    assert result.phase == "completed"
    assert optimizer.calls == 1
    assert result.skills_processed == 1


@pytest.mark.asyncio
async def test_run_writes_proposal_and_updates_status(
    tmp_path: Path,
    _patch_evolution_extra: None,
) -> None:
    skill_dir = tmp_path / "skills" / "deploy-k8s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")

    trace_store = TraceStore(tmp_path)
    _insert_traces(trace_store, "deploy-k8s")

    runner = GepaRunner(
        tmp_path,
        _evolution_enabled(),
        _DummyProvider(),
        optimizer=_MockOptimizer(improved=True),
        evaluator=None,
    )
    result = await runner.run(skill_name="deploy-k8s", trigger="cli")

    assert result.phase == "completed"
    assert len(result.proposals_created) == 1
    assert len(result.traces_consumed) == 3

    proposal_dir = tmp_path / "skills" / ".proposals" / result.proposals_created[0]
    assert (proposal_dir / "SKILL.md").is_file()
    assert (proposal_dir / "meta.json").is_file()
    meta_text = (proposal_dir / "meta.json").read_text(encoding="utf-8")
    assert '"source": "gepa"' in meta_text
    assert '"proposal_kind": "update"' in meta_text
    assert "rollout status" in (proposal_dir / "SKILL.md").read_text(encoding="utf-8")

    status = GepaRunStore(tmp_path).get()
    assert status.phase == "completed"
    assert status.proposals_created == result.proposals_created
    assert status.traces_consumed == result.traces_consumed


@pytest.mark.asyncio
async def test_run_skips_proposal_when_not_improved(
    tmp_path: Path,
    _patch_evolution_extra: None,
) -> None:
    skill_dir = tmp_path / "skills" / "deploy-k8s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")

    trace_store = TraceStore(tmp_path)
    _insert_traces(trace_store, "deploy-k8s")

    runner = GepaRunner(
        tmp_path,
        _evolution_enabled(),
        _DummyProvider(),
        optimizer=_MockOptimizer(improved=False),
    )
    result = await runner.run(skill_name="deploy-k8s", trigger="cli")

    assert result.phase == "completed"
    assert result.proposals_created == ()
    assert not list((tmp_path / "skills" / ".proposals").glob("*/meta.json"))


@pytest.mark.asyncio
async def test_run_marks_traces_used_after_proposal(
    tmp_path: Path,
    _patch_evolution_extra: None,
) -> None:
    skill_dir = tmp_path / "skills" / "deploy-k8s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")

    trace_store = TraceStore(tmp_path)
    _insert_traces(trace_store, "deploy-k8s")

    runner = GepaRunner(
        tmp_path,
        _evolution_enabled(),
        _DummyProvider(),
        optimizer=_MockOptimizer(),
    )
    await runner.run(skill_name="deploy-k8s", trigger="cron")

    remaining = trace_store.list_for_gepa(min_tool_calls=1, unused_only=True)
    assert remaining == []
