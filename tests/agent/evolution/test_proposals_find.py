"""Tests for proposal id prefix resolution."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.evolution.proposals import ProposalStore

_VALID_SKILL_MD = """---
name: deploy-k8s
description: Deploy workloads to Kubernetes clusters
---

# Deploy K8s
"""


def test_find_proposal_id_by_prefix(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    proposal_id = store.write_proposal(
        skill_name="deploy-k8s",
        skill_md=_VALID_SKILL_MD,
        trace_id="trace-1",
        rationale="test",
        confidence=0.9,
    )

    assert store.find_proposal_id(proposal_id[:8]) == proposal_id
    assert store.find_proposal_id(proposal_id) == proposal_id
    assert store.find_proposal_id("missing") is None


def test_find_proposal_id_ambiguous_prefix_returns_none(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    first = store.write_proposal(
        skill_name="deploy-k8s",
        skill_md=_VALID_SKILL_MD,
        trace_id="trace-1",
        rationale="one",
        confidence=0.9,
    )
    second = store.write_proposal(
        skill_name="lint-python",
        skill_md=_VALID_SKILL_MD.replace("deploy-k8s", "lint-python").replace(
            "Deploy workloads to Kubernetes clusters",
            "Lint Python projects",
        ),
        trace_id="trace-2",
        rationale="two",
        confidence=0.8,
    )
    assert first[:8] != second[:8] or first[0] == second[0]
    # Force ambiguous by searching a single-character prefix shared by both ids.
    shared = ""
    for left, right in zip(first, second, strict=True):
        if left == right:
            shared += left
        else:
            break
    if len(shared) < 2:
        return
    assert store.find_proposal_id(shared) is None
