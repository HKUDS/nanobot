"""Tests for PostTask proposal writing (E1 Step 3)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace
from nanobot.agent.evolution.post_task import PostTaskDecision, PostTaskEvolver
from nanobot.agent.evolution.proposals import (
    SKIP_ACTIVE_SKILL_EXISTS,
    SKIP_PENDING_PROPOSAL,
    ProposalStore,
    normalize_skill_md_content,
    validate_skill_md,
)
from nanobot.config.schema import EvolutionConfig, EvolutionPostTaskConfig
from nanobot.providers.base import LLMProvider, LLMResponse

_VALID_SKILL_MD = """---
name: k8s-deploy
description: Deploy applications to Kubernetes clusters
---

# Kubernetes Deploy

## When to use
Use when the user asks to deploy to k8s.

## Steps
1. Read manifests with read_file
2. Apply with exec kubectl

## Example
User: deploy nginx
Agent: apply deployment.yaml then check rollout status
"""


def _trace() -> TurnTrace:
    tool_calls = tuple(
        ToolCallRecord(name=f"tool_{index}", args_summary=f"arg{index}", ok=True)
        for index in range(5)
    )
    return TurnTrace(
        session_key="cli:direct",
        query="deploy nginx to k8s",
        tool_calls=tool_calls,
        tool_call_count=5,
        stop_reason="completed",
        outcome="success",
    )


def _decision() -> PostTaskDecision:
    return PostTaskDecision(
        action="create_skill",
        skill_name="k8s-deploy",
        rationale="repeatable deployment workflow",
        confidence=0.9,
    )


def test_normalize_skill_md_content_strips_fence() -> None:
    raw = f"```markdown\n{_VALID_SKILL_MD}\n```"
    assert normalize_skill_md_content(raw).startswith("---")


def test_validate_skill_md_accepts_valid_content() -> None:
    assert validate_skill_md(_VALID_SKILL_MD, skill_name="k8s-deploy") is None


def test_validate_skill_md_rejects_missing_frontmatter() -> None:
    assert validate_skill_md("# no frontmatter", skill_name="k8s-deploy") == "missing YAML frontmatter"


def test_validate_skill_md_rejects_name_mismatch() -> None:
    assert validate_skill_md(_VALID_SKILL_MD, skill_name="other-name") == "frontmatter name mismatch (expected other-name)"


def test_proposal_store_dedup_active_skill(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "k8s-deploy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_VALID_SKILL_MD, encoding="utf-8")

    store = ProposalStore(tmp_path)
    assert store.check_dedup("k8s-deploy") == SKIP_ACTIVE_SKILL_EXISTS


def test_proposal_store_dedup_pending_proposal(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    store.write_proposal(
        skill_name="k8s-deploy",
        skill_md=_VALID_SKILL_MD,
        trace_id="trace-1",
        rationale="test",
        confidence=0.8,
    )
    assert store.check_dedup("k8s-deploy") == SKIP_PENDING_PROPOSAL


def test_proposal_store_write_proposal_creates_files(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = store.write_proposal(
        skill_name="k8s-deploy",
        skill_md=_VALID_SKILL_MD,
        trace_id="trace-abc",
        rationale="repeatable",
        confidence=0.85,
    )

    proposal_dir = tmp_path / "skills" / ".proposals" / proposal_id
    assert (proposal_dir / "SKILL.md").read_text(encoding="utf-8") == _VALID_SKILL_MD
    meta = json.loads((proposal_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["proposal_id"] == proposal_id
    assert meta["source"] == "post_task"
    assert meta["trace_id"] == "trace-abc"
    assert meta["skill_name"] == "k8s-deploy"
    assert meta["status"] == "pending"


def test_proposal_store_write_active_skill(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    path = store.write_active_skill("k8s-deploy", _VALID_SKILL_MD)
    assert path == tmp_path / "skills" / "k8s-deploy" / "SKILL.md"
    assert path.read_text(encoding="utf-8") == _VALID_SKILL_MD


def test_list_workspace_skill_summaries_ignores_proposals_dir(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "existing-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: existing-skill\ndescription: Already there\n---\n",
        encoding="utf-8",
    )
    store = ProposalStore(tmp_path)
    store.write_proposal(
        skill_name="pending-skill",
        skill_md=_VALID_SKILL_MD.replace("k8s-deploy", "pending-skill"),
        trace_id="t1",
        rationale="x",
        confidence=0.8,
    )

    summaries = store.list_workspace_skill_summaries()
    assert summaries == ["existing-skill — Already there"]


def test_create_proposal_writes_pending_proposal(tmp_path: Path) -> None:
    async def _run() -> object:
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content=_VALID_SKILL_MD, finish_reason="stop")
        )
        evolver = PostTaskEvolver(
            tmp_path,
            EvolutionConfig(enable=True, post_task=EvolutionPostTaskConfig(auto_apply=False)),
            provider=provider,
            llm_timeout_s=5.0,
        )
        return await evolver.create_proposal(_trace(), _decision())

    result = asyncio.run(_run())
    assert result.created is True
    assert result.auto_applied is False
    assert result.proposal_id
    assert result.skill_name == "k8s-deploy"
    assert result.skill_path.startswith("skills/.proposals/")


def test_create_proposal_auto_apply_writes_active_skill(tmp_path: Path) -> None:
    async def _run() -> object:
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content=_VALID_SKILL_MD, finish_reason="stop")
        )
        evolver = PostTaskEvolver(
            tmp_path,
            EvolutionConfig(enable=True, post_task=EvolutionPostTaskConfig(auto_apply=True)),
            provider=provider,
            llm_timeout_s=5.0,
        )
        return await evolver.create_proposal(_trace(), _decision())

    result = asyncio.run(_run())
    assert result.created is True
    assert result.auto_applied is True
    assert result.proposal_id == ""
    assert (tmp_path / "skills" / "k8s-deploy" / "SKILL.md").is_file()


def test_create_proposal_skips_when_active_skill_exists(tmp_path: Path) -> None:
    async def _run() -> tuple[object, MagicMock]:
        store = ProposalStore(tmp_path)
        store.write_active_skill("k8s-deploy", _VALID_SKILL_MD)
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_retry = AsyncMock()
        evolver = PostTaskEvolver(
            tmp_path,
            EvolutionConfig(enable=True),
            provider=provider,
            proposal_store=store,
        )
        result = await evolver.create_proposal(_trace(), _decision())
        return result, provider

    result, provider = asyncio.run(_run())
    assert result.created is False
    assert result.skip_reason == SKIP_ACTIVE_SKILL_EXISTS
    provider.chat_with_retry.assert_not_awaited()


def test_create_proposal_skips_on_llm_failure(tmp_path: Path) -> None:
    async def _run() -> object:
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="bad", finish_reason="error")
        )
        evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=True), provider=provider)
        return await evolver.create_proposal(_trace(), _decision())

    result = asyncio.run(_run())
    assert result.created is False
    assert result.skip_reason == "skill generation failed"
