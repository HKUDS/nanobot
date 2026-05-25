"""Tests for GEPA proposal writing and apply (E4-C2/C3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.evolution.git_store import EvolutionGitStore
from nanobot.agent.evolution.proposals import (
    ERR_APPLY_ACTIVE_SKILL_MISSING,
    ERR_APPLY_NOT_GEPA,
    SKIP_PENDING_GEPA_UPDATE,
    ProposalStore,
    validate_gepa_update,
)

_VALID_SKILL_MD = """---
name: deploy-k8s
description: Deploy applications to Kubernetes clusters
---

# Kubernetes Deploy

## When to use
Use when the user asks to deploy to k8s.

## Steps
1. Read manifests with read_file
2. Apply with exec kubectl
"""

_UPDATED_SKILL_MD = """---
name: deploy-k8s
description: Deploy applications to Kubernetes clusters
---

# Kubernetes Deploy

## When to use
Use when the user asks to deploy to k8s.

## Steps
1. Read manifests with read_file
2. Apply with exec kubectl
3. Verify rollout status with kubectl rollout status
"""


def _seed_active_skill(store: ProposalStore, tmp_path: Path) -> None:
    store.write_active_skill("deploy-k8s", _VALID_SKILL_MD)


def _pending_gepa_update(store: ProposalStore, *, skill_md: str = _UPDATED_SKILL_MD) -> str:
    return store.write_gepa_proposal(
        "deploy-k8s",
        skill_md,
        base_sha="a1b2c3d4",
        evaluation_score=0.91,
        trace_ids=["trace-1"],
        rationale="Improved kubectl rollout checks",
    )

def test_write_gepa_proposal_creates_proposal_with_full_meta(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)

    proposal_id = store.write_gepa_proposal(
        "deploy-k8s",
        _VALID_SKILL_MD,
        base_sha="a1b2c3d4",
        evaluation_score=0.91,
        trace_ids=["trace-1", "trace-2"],
        rationale="Improved kubectl rollout checks",
    )

    proposal_dir = tmp_path / "skills" / ".proposals" / proposal_id
    assert (proposal_dir / "SKILL.md").read_text(encoding="utf-8") == _VALID_SKILL_MD
    meta = json.loads((proposal_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["proposal_id"] == proposal_id
    assert meta["source"] == "gepa"
    assert meta["proposal_kind"] == "update"
    assert meta["skill_name"] == "deploy-k8s"
    assert meta["base_skill"] == "deploy-k8s"
    assert meta["base_sha"] == "a1b2c3d4"
    assert meta["evaluation_score"] == 0.91
    assert meta["trace_id"] == "trace-1,trace-2"
    assert meta["rationale"] == "Improved kubectl rollout checks"
    assert meta["status"] == "pending"
    assert not (tmp_path / "skills" / "deploy-k8s" / "SKILL.md").exists()


def test_write_gepa_proposal_rejects_duplicate_pending_update(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    store.write_gepa_proposal(
        "deploy-k8s",
        _VALID_SKILL_MD,
        base_sha="aaaa1111",
        evaluation_score=0.8,
        trace_ids=["trace-1"],
        rationale="first",
    )

    with pytest.raises(ValueError, match=SKIP_PENDING_GEPA_UPDATE):
        store.write_gepa_proposal(
            "deploy-k8s",
            _VALID_SKILL_MD,
            base_sha="bbbb2222",
            evaluation_score=0.9,
            trace_ids=["trace-2"],
            rationale="second",
        )


def test_write_gepa_proposal_allows_different_skill_names(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    other_skill_md = _VALID_SKILL_MD.replace("deploy-k8s", "deploy-gcp")

    first_id = store.write_gepa_proposal(
        "deploy-k8s",
        _VALID_SKILL_MD,
        base_sha="aaaa1111",
        evaluation_score=0.8,
        trace_ids=["trace-1"],
        rationale="k8s",
    )
    second_id = store.write_gepa_proposal(
        "deploy-gcp",
        other_skill_md,
        base_sha="cccc3333",
        evaluation_score=0.7,
        trace_ids=["trace-2"],
        rationale="gcp",
    )

    assert first_id != second_id
    assert len(store.list_pending()) == 2


def test_write_gepa_proposal_does_not_block_on_pending_post_task_create(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    store.write_proposal(
        skill_name="deploy-k8s",
        skill_md=_VALID_SKILL_MD,
        trace_id="trace-create",
        rationale="post task create",
        confidence=0.9,
    )

    proposal_id = store.write_gepa_proposal(
        "deploy-k8s",
        _VALID_SKILL_MD,
        base_sha="dddd4444",
        evaluation_score=0.85,
        trace_ids=["trace-gepa"],
        rationale="gepa update",
    )

    assert proposal_id
    assert store.pending_gepa_update_exists("deploy-k8s") is True
    assert store.pending_proposal_exists("deploy-k8s") is True


def test_apply_update_promotes_gepa_proposal_to_active_skill(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    git = EvolutionGitStore(tmp_path)
    git.init()
    _seed_active_skill(store, tmp_path)
    git.commit_create("deploy-k8s")
    proposal_id = _pending_gepa_update(store)

    result = store.apply_update(proposal_id, git_store=git)

    assert result.ok is True
    assert result.skill_path == "skills/deploy-k8s/SKILL.md"
    assert result.commit_sha
    active = tmp_path / "skills" / "deploy-k8s" / "SKILL.md"
    assert active.read_text(encoding="utf-8") == _UPDATED_SKILL_MD
    meta = store.read_meta(proposal_id)
    assert meta is not None
    assert meta.status == "applied"
    assert git.log()[0].message == "evolve: update skill deploy-k8s (gepa)"


def test_apply_update_fails_when_active_skill_missing(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = _pending_gepa_update(store)

    result = store.apply_update(proposal_id)

    assert result.ok is False
    assert result.skip_reason == ERR_APPLY_ACTIVE_SKILL_MISSING


def test_apply_update_rejects_description_drift(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    _seed_active_skill(store, tmp_path)
    drifted_md = _UPDATED_SKILL_MD.replace(
        "description: Deploy applications to Kubernetes clusters",
        "description: Ship containers somewhere else",
    )
    proposal_id = _pending_gepa_update(store, skill_md=drifted_md)

    result = store.apply_update(proposal_id)

    assert result.ok is False
    assert "description drift not allowed" in result.skip_reason
    assert (
        tmp_path / "skills" / "deploy-k8s" / "SKILL.md"
    ).read_text(encoding="utf-8") == _VALID_SKILL_MD


def test_apply_update_rejects_post_task_proposal(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = store.write_proposal(
        skill_name="deploy-k8s",
        skill_md=_VALID_SKILL_MD,
        trace_id="trace-create",
        rationale="create",
        confidence=0.9,
    )

    result = store.apply_update(proposal_id)

    assert result.ok is False
    assert result.skip_reason == ERR_APPLY_NOT_GEPA


def test_apply_still_handles_create_proposals(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = store.write_proposal(
        skill_name="deploy-k8s",
        skill_md=_VALID_SKILL_MD,
        trace_id="trace-create",
        rationale="create",
        confidence=0.9,
    )

    result = store.apply(proposal_id)

    assert result.ok is True
    assert (tmp_path / "skills" / "deploy-k8s" / "SKILL.md").is_file()


def test_validate_gepa_update_requires_matching_description() -> None:
    error = validate_gepa_update(
        _UPDATED_SKILL_MD.replace(
            "description: Deploy applications to Kubernetes clusters",
            "description: changed",
        ),
        _VALID_SKILL_MD,
        skill_name="deploy-k8s",
        base_skill="deploy-k8s",
    )

    assert error == "description drift not allowed"
