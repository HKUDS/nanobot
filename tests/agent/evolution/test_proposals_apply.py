"""Tests for proposal apply/reject (E2 Step 1)."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.agent.evolution.proposals import (
    ERR_APPLY_ACTIVE_SKILL_EXISTS,
    ERR_PROPOSAL_ALREADY_REJECTED,
    ERR_PROPOSAL_NOT_FOUND,
    ERR_PROPOSAL_NOT_PENDING,
    ProposalStore,
)

_VALID_SKILL_MD = """---
name: evolution-smoke-check
description: Repeatable evolution module smoke check before release
---

# Evolution Smoke Check

## When to use
Before each release, audit the evolution module.

## Steps
1. list_dir nanobot/agent/evolution
2. read_file post_task.py
3. grep loop.py for PostTask hooks
"""


def _pending_proposal(
    store: ProposalStore,
    *,
    skill_name: str = "evolution-smoke-check",
) -> str:
    skill_md = _VALID_SKILL_MD.replace("evolution-smoke-check", skill_name)
    return store.write_proposal(
        skill_name=skill_name,
        skill_md=skill_md,
        trace_id="trace-1",
        rationale="repeatable checklist",
        confidence=0.9,
    )


def test_apply_promotes_proposal_to_active_skill(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = _pending_proposal(store)

    result = store.apply(proposal_id)

    assert result.ok is True
    assert result.skill_name == "evolution-smoke-check"
    assert result.skill_path == "skills/evolution-smoke-check/SKILL.md"
    active = tmp_path / "skills" / "evolution-smoke-check" / "SKILL.md"
    assert active.is_file()
    assert active.read_text(encoding="utf-8") == _VALID_SKILL_MD

    meta = store.read_meta(proposal_id)
    assert meta is not None
    assert meta.status == "applied"
    assert meta.applied_at


def test_apply_is_idempotent_when_already_applied(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = _pending_proposal(store)

    first = store.apply(proposal_id)
    second = store.apply(proposal_id)

    assert first.ok is True
    assert second.ok is True
    assert second.skill_path == "skills/evolution-smoke-check/SKILL.md"


def test_apply_fails_when_active_skill_exists(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    store.write_active_skill("evolution-smoke-check", _VALID_SKILL_MD)
    proposal_id = _pending_proposal(store)

    result = store.apply(proposal_id)

    assert result.ok is False
    assert result.skip_reason == ERR_APPLY_ACTIVE_SKILL_EXISTS


def test_apply_not_found(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    result = store.apply("missing-id")
    assert result.ok is False
    assert result.skip_reason == ERR_PROPOSAL_NOT_FOUND


def test_apply_rejects_invalid_skill_md(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = store.write_proposal(
        skill_name="evolution-smoke-check",
        skill_md="# no frontmatter",
        trace_id="trace-1",
        rationale="bad",
        confidence=0.9,
    )

    result = store.apply(proposal_id)

    assert result.ok is False
    assert "invalid" in result.skip_reason


def test_reject_moves_proposal_to_rejected_dir(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = _pending_proposal(store)

    result = store.reject(proposal_id)

    assert result.ok is True
    assert result.skill_name == "evolution-smoke-check"
    rejected_dir = tmp_path / "skills" / ".rejected" / proposal_id
    assert rejected_dir.is_dir()
    assert (rejected_dir / "SKILL.md").is_file()
    assert not (tmp_path / "skills" / ".proposals" / proposal_id).exists()

    meta = json.loads((rejected_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "rejected"
    assert meta["rejected_at"]
    assert store.list_pending() == []


def test_reject_fails_after_apply(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = _pending_proposal(store)
    store.apply(proposal_id)

    result = store.reject(proposal_id)

    assert result.ok is False
    assert result.skip_reason == ERR_PROPOSAL_NOT_PENDING


def test_reject_is_idempotent_failure(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = _pending_proposal(store)
    store.reject(proposal_id)

    result = store.reject(proposal_id)

    assert result.ok is False
    assert result.skip_reason == ERR_PROPOSAL_ALREADY_REJECTED


def test_get_reads_pending_and_rejected(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = _pending_proposal(store)

    pending = store.get(proposal_id)
    assert pending is not None
    assert pending.meta.status == "pending"
    assert pending.skill_md == _VALID_SKILL_MD

    store.reject(proposal_id)
    rejected = store.get(proposal_id)
    assert rejected is not None
    assert rejected.meta.status == "rejected"
    assert rejected.proposal_dir.name == proposal_id
