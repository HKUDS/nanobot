"""Tests for ProposalMeta GEPA field extensions (E4-C1)."""

from __future__ import annotations

import json

from nanobot.agent.evolution.proposals import ProposalMeta


def test_proposal_meta_from_dict_legacy_post_task() -> None:
    legacy = {
        "proposal_id": "abc-123",
        "source": "post_task",
        "trace_id": "trace-1",
        "skill_name": "k8s-deploy",
        "rationale": "repeatable workflow",
        "confidence": 0.85,
        "created_at": "2026-05-24T10:00:00+00:00",
        "status": "pending",
    }

    meta = ProposalMeta.from_dict(legacy)

    assert meta.proposal_id == "abc-123"
    assert meta.source == "post_task"
    assert meta.base_skill == ""
    assert meta.base_sha == ""
    assert meta.evaluation_score is None
    assert meta.proposal_kind is None
    assert meta.resolved_proposal_kind() == "create"


def test_proposal_meta_legacy_to_dict_omits_gepa_fields() -> None:
    meta = ProposalMeta(
        proposal_id="abc-123",
        source="post_task",
        trace_id="trace-1",
        skill_name="k8s-deploy",
        rationale="repeatable workflow",
        confidence=0.85,
        created_at="2026-05-24T10:00:00+00:00",
    )

    payload = meta.to_dict()

    assert payload == {
        "proposal_id": "abc-123",
        "source": "post_task",
        "trace_id": "trace-1",
        "skill_name": "k8s-deploy",
        "rationale": "repeatable workflow",
        "confidence": 0.85,
        "created_at": "2026-05-24T10:00:00+00:00",
        "status": "pending",
    }


def test_proposal_meta_gepa_round_trip() -> None:
    meta = ProposalMeta(
        proposal_id="gepa-456",
        source="gepa",
        trace_id="trace-9",
        skill_name="deploy-k8s",
        rationale="GEPA optimized instructions",
        confidence=1.0,
        created_at="2026-05-24T12:00:00+00:00",
        base_skill="deploy-k8s",
        base_sha="a1b2c3d4",
        evaluation_score=0.92,
        proposal_kind="update",
    )

    restored = ProposalMeta.from_dict(json.loads(json.dumps(meta.to_dict())))

    assert restored == meta
    assert restored.resolved_proposal_kind() == "update"


def test_proposal_meta_infers_update_kind_from_gepa_source() -> None:
    meta = ProposalMeta.from_dict(
        {
            "proposal_id": "gepa-789",
            "source": "gepa",
            "trace_id": "trace-2",
            "skill_name": "deploy-k8s",
            "rationale": "optimized",
            "confidence": 0.0,
            "created_at": "2026-05-24T12:00:00+00:00",
            "base_skill": "deploy-k8s",
            "base_sha": "deadbeef",
        }
    )

    assert meta.proposal_kind is None
    assert meta.resolved_proposal_kind() == "update"


def test_proposal_meta_from_dict_tolerates_invalid_gepa_fields() -> None:
    meta = ProposalMeta.from_dict(
        {
            "proposal_id": "x",
            "source": "gepa",
            "trace_id": "t",
            "skill_name": "s",
            "rationale": "r",
            "confidence": 0.5,
            "created_at": "2026-05-24T12:00:00+00:00",
            "proposal_kind": "invalid",
            "evaluation_score": "not-a-number",
            "base_skill": None,
            "base_sha": None,
        }
    )

    assert meta.proposal_kind is None
    assert meta.evaluation_score is None
    assert meta.base_skill == ""
    assert meta.base_sha == ""
