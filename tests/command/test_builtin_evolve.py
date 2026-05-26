"""Tests for /evolve-* slash commands (E2 Step 3)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace
from nanobot.agent.evolution.proposals import ProposalStore
from nanobot.agent.evolution.trace_store import TraceStore
from nanobot.bus.events import InboundMessage
from nanobot.command.evolve import (
    cmd_evolve_apply,
    cmd_evolve_list,
    cmd_evolve_log,
    cmd_evolve_reject,
    cmd_evolve_restore,
    cmd_evolve_run,
    cmd_evolve_show,
    cmd_evolve_status,
    format_gepa_run_status,
)
from nanobot.config.schema import EvolutionConfig, EvolutionGepaConfig
from nanobot.agent.evolution.gepa_status import GepaRunStatus
from nanobot.command.router import CommandContext
from nanobot.utils.gitstore import CommitInfo

_VALID_SKILL_MD = """---
name: deploy-k8s
description: Deploy workloads to Kubernetes clusters
---

# Deploy K8s
"""

_UPDATED_SKILL_MD = """---
name: deploy-k8s
description: Deploy workloads to Kubernetes clusters
---

# Deploy K8s

## Steps
1. kubectl apply
2. kubectl rollout status
"""


def _write_pending(store: ProposalStore, *, trace_id: str = "trace-abc") -> str:
    return store.write_proposal(
        skill_name="deploy-k8s",
        skill_md=_VALID_SKILL_MD,
        trace_id=trace_id,
        rationale="repeatable deploy flow",
        confidence=0.9,
    )


def _make_ctx(
    tmp_path: Path,
    raw: str,
    *,
    args: str = "",
    warm_skill_index: MagicMock | None = None,
) -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    warm = warm_skill_index or MagicMock()
    loop = SimpleNamespace(
        context=SimpleNamespace(
            workspace=tmp_path,
            warm_skill_index=warm,
        ),
    )
    return CommandContext(
        msg=msg,
        session=None,
        key=msg.session_key,
        raw=raw,
        args=args,
        loop=loop,
    )


@pytest.mark.asyncio
async def test_evolve_list_empty(tmp_path: Path) -> None:
    out = await cmd_evolve_list(_make_ctx(tmp_path, "/evolve-list"))
    assert "No pending skill proposals" in out.content


@pytest.mark.asyncio
async def test_evolve_list_shows_pending(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = _write_pending(store)

    out = await cmd_evolve_list(_make_ctx(tmp_path, "/evolve-list"))

    assert "## Pending Skill Proposals" in out.content
    assert proposal_id[:8] in out.content
    assert "deploy-k8s" in out.content


@pytest.mark.asyncio
async def test_evolve_show_includes_trace_summary(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    trace_store = TraceStore(tmp_path)
    trace = TurnTrace(
        session_key="cli:direct",
        query="deploy my app",
        trace_id="trace-abc",
        tool_calls=(ToolCallRecord(name="exec", args_summary="kubectl apply"),),
        tool_call_count=1,
    )
    trace_store.insert(trace)
    proposal_id = _write_pending(store, trace_id="trace-abc")

    out = await cmd_evolve_show(
        _make_ctx(tmp_path, "/evolve-show", args=proposal_id[:8]),
    )

    assert "## Proposal `deploy-k8s`" in out.content
    assert "trace-abc" in out.content
    assert "deploy my app" in out.content
    assert "kubectl apply" in out.content
    assert "```markdown" in out.content


@pytest.mark.asyncio
async def test_evolve_show_includes_gepa_metadata_and_diff(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    store.write_active_skill("deploy-k8s", _VALID_SKILL_MD)
    proposal_id = store.write_gepa_proposal(
        "deploy-k8s",
        _UPDATED_SKILL_MD,
        base_sha="a1b2c3d4",
        evaluation_score=0.912,
        trace_ids=["trace-gepa-1", "trace-gepa-2"],
        rationale="Improved rollout checks",
    )

    out = await cmd_evolve_show(
        _make_ctx(tmp_path, "/evolve-show", args=proposal_id[:8]),
    )

    assert "## Proposal `deploy-k8s`" in out.content
    assert "- Proposal kind: update" in out.content
    assert "- Base skill: `deploy-k8s`" in out.content
    assert "- Base SHA: `a1b2c3d4`" in out.content
    assert "- Evaluation score: 0.912" in out.content
    assert "### Active skill diff" in out.content
    assert "kubectl rollout status" in out.content
    assert "trace-gepa-1" in out.content
    assert "trace-gepa-2" in out.content
    assert "Improved rollout checks" in out.content


@pytest.mark.asyncio
async def test_evolve_apply_promotes_skill_and_warms_index(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = _write_pending(store)
    warm = MagicMock()
    ctx = _make_ctx(tmp_path, "/evolve-apply", args=proposal_id[:8], warm_skill_index=warm)

    out = await cmd_evolve_apply(ctx)

    assert "Applied skill **deploy-k8s**" in out.content
    assert (tmp_path / "skills" / "deploy-k8s" / "SKILL.md").is_file()
    warm.assert_called_once_with()
    meta = json.loads(
        (tmp_path / "skills" / ".proposals" / proposal_id / "meta.json").read_text(encoding="utf-8")
    )
    assert meta["status"] == "applied"


@pytest.mark.asyncio
async def test_evolve_apply_routes_gepa_update_proposal(tmp_path: Path) -> None:
    from nanobot.agent.evolution.git_store import EvolutionGitStore

    store = ProposalStore(tmp_path)
    git = EvolutionGitStore(tmp_path)
    git.init()
    store.write_active_skill("deploy-k8s", _VALID_SKILL_MD)
    git.commit_create("deploy-k8s")
    proposal_id = store.write_gepa_proposal(
        "deploy-k8s",
        _UPDATED_SKILL_MD,
        base_sha="a1b2c3d4",
        evaluation_score=0.9,
        trace_ids=["trace-gepa"],
        rationale="GEPA improved rollout checks",
    )
    warm = MagicMock()
    ctx = _make_ctx(tmp_path, "/evolve-apply", args=proposal_id[:8], warm_skill_index=warm)

    out = await cmd_evolve_apply(ctx)

    assert "Applied skill **deploy-k8s**" in out.content
    assert (tmp_path / "skills" / "deploy-k8s" / "SKILL.md").read_text(encoding="utf-8") == _UPDATED_SKILL_MD
    warm.assert_called_once_with()
    meta = json.loads(
        (tmp_path / "skills" / ".proposals" / proposal_id / "meta.json").read_text(encoding="utf-8")
    )
    assert meta["status"] == "applied"
    assert meta["source"] == "gepa"
    assert git.log()[0].message == "evolve: update skill deploy-k8s (gepa)"


@pytest.mark.asyncio
async def test_evolve_reject_moves_proposal(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = _write_pending(store)

    out = await cmd_evolve_reject(
        _make_ctx(tmp_path, "/evolve-reject", args=proposal_id[:8]),
    )

    assert "Rejected proposal **deploy-k8s**" in out.content
    assert (tmp_path / "skills" / ".rejected" / proposal_id).is_dir()
    assert not (tmp_path / "skills" / ".proposals" / proposal_id).exists()


class _FakeEvolveGit:
    def __init__(
        self,
        *,
        initialized: bool = True,
        commits: list[CommitInfo] | None = None,
        diff_map: dict[str, tuple[CommitInfo, str] | None] | None = None,
        restore_result: str | None = None,
    ):
        self._initialized = initialized
        self._commits = commits or []
        self._diff_map = diff_map or {}
        self._restore_result = restore_result

    def is_initialized(self) -> bool:
        return self._initialized

    def log(self, max_entries: int = 20) -> list[CommitInfo]:
        return self._commits[:max_entries]

    def show_commit_diff(self, sha: str, max_entries: int = 50):
        return self._diff_map.get(sha)

    def restore(self, sha: str) -> str | None:
        return self._restore_result


@pytest.mark.asyncio
async def test_evolve_log_latest(tmp_path: Path, monkeypatch) -> None:
    commit = CommitInfo(
        sha="abcd1234",
        message="evolve: create skill deploy-k8s",
        timestamp="2026-05-24 12:00",
    )
    diff = (
        "diff --git a/skills/deploy-k8s/SKILL.md b/skills/deploy-k8s/SKILL.md\n"
        "--- a/skills/deploy-k8s/SKILL.md\n"
        "+++ b/skills/deploy-k8s/SKILL.md\n"
        "+new skill\n"
    )
    fake_git = _FakeEvolveGit(commits=[commit], diff_map={commit.sha: (commit, diff)})
    monkeypatch.setattr("nanobot.command.evolve.EvolutionGitStore", lambda _ws: fake_git)

    out = await cmd_evolve_log(_make_ctx(tmp_path, "/evolve-log"))

    assert "## Skill Evolution" in out.content
    assert "`abcd1234`" in out.content
    assert "skills/deploy-k8s/SKILL.md" in out.content
    assert "Use `/evolve-restore abcd1234`" in out.content


@pytest.mark.asyncio
async def test_evolve_restore_lists_commits(tmp_path: Path, monkeypatch) -> None:
    commits = [
        CommitInfo(sha="11111111", message="evolve: create skill a", timestamp="2026-05-24"),
        CommitInfo(sha="22222222", message="evolve: create skill b", timestamp="2026-05-23"),
    ]
    fake_git = _FakeEvolveGit(commits=commits)
    monkeypatch.setattr("nanobot.command.evolve.EvolutionGitStore", lambda _ws: fake_git)

    out = await cmd_evolve_restore(_make_ctx(tmp_path, "/evolve-restore"))

    assert "## Evolve Restore" in out.content
    assert "`11111111`" in out.content
    assert "Restore a version with `/evolve-restore <sha>`." in out.content


@pytest.mark.asyncio
async def test_evolve_restore_applies_and_warms_index(tmp_path: Path, monkeypatch) -> None:
    commit = CommitInfo(
        sha="abcd1234",
        message="evolve: create skill deploy-k8s",
        timestamp="2026-05-24 12:00",
    )
    diff = "diff --git a/skills/deploy-k8s/SKILL.md b/skills/deploy-k8s/SKILL.md\n"
    fake_git = _FakeEvolveGit(
        diff_map={commit.sha: (commit, diff)},
        restore_result="eeee9999",
    )
    monkeypatch.setattr("nanobot.command.evolve.EvolutionGitStore", lambda _ws: fake_git)
    warm = MagicMock()

    out = await cmd_evolve_restore(
        _make_ctx(tmp_path, "/evolve-restore", args="abcd1234", warm_skill_index=warm),
    )

    assert "Restored workspace skills" in out.content
    assert "`eeee9999`" in out.content
    warm.assert_called_once_with()


def _make_loop_with_evolution(
    tmp_path: Path,
    *,
    gepa_enabled: bool = True,
    schedule: MagicMock | None = None,
) -> SimpleNamespace:
    evolution = EvolutionConfig(
        enable=True,
        gepa=EvolutionGepaConfig(enable=gepa_enabled),
    )
    return SimpleNamespace(
        context=SimpleNamespace(workspace=tmp_path, warm_skill_index=MagicMock()),
        _evolution=evolution,
        _schedule_gepa_run=schedule or MagicMock(),
    )


@pytest.mark.asyncio
async def test_evolve_run_schedules_background(tmp_path: Path) -> None:
    schedule = MagicMock()
    loop = _make_loop_with_evolution(tmp_path, schedule=schedule)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/evolve-run")
    ctx = CommandContext(
        msg=msg,
        session=None,
        key=msg.session_key,
        raw="/evolve-run",
        args="deploy-k8s",
        loop=loop,
    )

    out = await cmd_evolve_run(ctx)

    schedule.assert_called_once_with(skill_name="deploy-k8s", trigger="slash")
    assert "GEPA run started" in out.content


@pytest.mark.asyncio
async def test_evolve_run_rejects_when_disabled(tmp_path: Path) -> None:
    loop = _make_loop_with_evolution(tmp_path, gepa_enabled=False)
    ctx = CommandContext(
        msg=InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/evolve-run"),
        session=None,
        key="cli:direct",
        raw="/evolve-run",
        args="",
        loop=loop,
    )

    out = await cmd_evolve_run(ctx)

    assert "disabled" in out.content.lower()


@pytest.mark.asyncio
async def test_evolve_run_rejects_when_already_running(tmp_path: Path) -> None:
    from nanobot.agent.evolution.gepa_status import GepaRunStore

    loop = _make_loop_with_evolution(tmp_path)
    GepaRunStore(tmp_path).save(
        GepaRunStatus(run_id="run-1", phase="optimizing", started_at="2026-05-24T00:00:00Z"),
    )
    ctx = CommandContext(
        msg=InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/evolve-run"),
        session=None,
        key="cli:direct",
        raw="/evolve-run",
        args="",
        loop=loop,
    )

    out = await cmd_evolve_run(ctx)

    assert "already running" in out.content.lower()
    loop._schedule_gepa_run.assert_not_called()


def test_format_gepa_run_status_idle() -> None:
    assert "idle" in format_gepa_run_status(GepaRunStatus.idle()).lower()


def test_format_gepa_run_status_completed() -> None:
    status = GepaRunStatus(
        run_id="abcdef12-3456",
        phase="completed",
        trigger="slash",
        skill_name="deploy-k8s",
        started_at="2026-05-24T00:00:00Z",
        finished_at="2026-05-24T00:05:00Z",
        proposals_created=("proposal-1",),
        budget_usd_spent=1.25,
        message="done",
    )

    text = format_gepa_run_status(status)

    assert "completed" in text
    assert "deploy-k8s" in text
    assert "proposal-1"[:8] in text
    assert "/evolve-show" in text


@pytest.mark.asyncio
async def test_evolve_status_reads_store(tmp_path: Path) -> None:
    from nanobot.agent.evolution.gepa_status import GepaRunStore

    GepaRunStore(tmp_path).save(
        GepaRunStatus(run_id="run-xyz", phase="failed", error="boom"),
    )
    loop = _make_loop_with_evolution(tmp_path)
    ctx = CommandContext(
        msg=InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/evolve-status"),
        session=None,
        key="cli:direct",
        raw="/evolve-status",
        args="",
        loop=loop,
    )

    out = await cmd_evolve_status(ctx)

    assert "failed" in out.content
    assert "boom" in out.content
