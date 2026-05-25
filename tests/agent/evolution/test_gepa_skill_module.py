"""Tests for GEPA SkillModule body round-trip (E4-D2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.evolution.deps import evolution_extra_available
from nanobot.agent.evolution.gepa_skill_module import (
    ERR_NAME_MISMATCH,
    GepaSkillModule,
    extract_body_from_dspy_module,
    merge_skill_md,
    split_skill_md,
)

_SKILL_MD = """---
name: deploy-k8s
description: Deploy workloads to Kubernetes clusters
---

# Deploy K8s

## When to use
Use when the user asks to deploy to Kubernetes.

## Steps
1. kubectl apply -f manifest.yaml
"""

_UPDATED_BODY = """# Deploy K8s

## When to use
Use when the user asks to deploy to Kubernetes.

## Steps
1. kubectl apply -f manifest.yaml
2. kubectl rollout status deploy/nginx
"""


def test_split_and_merge_skill_md_round_trip() -> None:
    parts = split_skill_md(_SKILL_MD)

    assert parts.skill_name == "deploy-k8s"
    assert parts.description == "Deploy workloads to Kubernetes clusters"
    assert "kubectl apply" in parts.body

    rebuilt = merge_skill_md(parts.frontmatter, parts.body)
    reparsed = split_skill_md(rebuilt)

    assert reparsed.frontmatter == parts.frontmatter
    assert reparsed.body == parts.body
    assert reparsed.skill_name == parts.skill_name
    assert reparsed.description == parts.description


def test_gepa_skill_module_updates_body_while_frontmatter_stays_frozen() -> None:
    module = GepaSkillModule.from_skill_md(_SKILL_MD)
    original_frontmatter = module.frontmatter

    module.body = _UPDATED_BODY
    rebuilt = module.to_skill_md()
    reparsed = split_skill_md(rebuilt)

    assert reparsed.frontmatter == original_frontmatter
    assert reparsed.skill_name == "deploy-k8s"
    assert reparsed.description == "Deploy workloads to Kubernetes clusters"
    assert "rollout status" in reparsed.body
    assert reparsed.body == _UPDATED_BODY.strip()


def test_gepa_skill_module_from_active_skill(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "deploy-k8s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")

    module = GepaSkillModule.from_active_skill(tmp_path, "deploy-k8s")

    assert module.skill_name == "deploy-k8s"
    assert module.body.startswith("# Deploy K8s")


def test_gepa_skill_module_rejects_name_mismatch() -> None:
    with pytest.raises(ValueError, match=ERR_NAME_MISMATCH):
        GepaSkillModule.from_skill_md(_SKILL_MD, expected_name="other-skill")


@pytest.mark.skipif(not evolution_extra_available(), reason="evolution extra not installed")
def test_gepa_skill_module_dspy_body_round_trip() -> None:
    module = GepaSkillModule.from_skill_md(_SKILL_MD)
    original_frontmatter = module.frontmatter

    dspy_module = module.build_dspy_module()
    assert extract_body_from_dspy_module(dspy_module) == module.body

    optimized_body = module.body + "\n\n## Verification\n3. Check pod logs with kubectl logs."
    _set_instructions(dspy_module, optimized_body)

    module.sync_from_dspy_module(dspy_module)
    reparsed = split_skill_md(module.to_skill_md())

    assert extract_body_from_dspy_module(dspy_module) == optimized_body
    assert reparsed.frontmatter == original_frontmatter
    assert reparsed.description == "Deploy workloads to Kubernetes clusters"
    assert "kubectl logs" in reparsed.body


def _set_instructions(dspy_module, body: str) -> None:
    predictor = getattr(dspy_module, "skill_executor")
    predictor.signature = predictor.signature.with_instructions(body)
