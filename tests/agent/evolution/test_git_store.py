"""Tests for EvolutionGitStore (E2 Step 2)."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.evolution.git_store import EvolutionGitStore
from nanobot.agent.evolution.proposals import ProposalStore

_VALID_SKILL_MD = """---
name: deploy-k8s
description: Deploy workloads to Kubernetes clusters
---

# Deploy K8s

## When to use
When deploying to Kubernetes.
"""


def _pending_proposal(store: ProposalStore, *, skill_name: str = "deploy-k8s") -> str:
    skill_md = _VALID_SKILL_MD.replace("deploy-k8s", skill_name)
    return store.write_proposal(
        skill_name=skill_name,
        skill_md=skill_md,
        trace_id="trace-1",
        rationale="repeatable deploy flow",
        confidence=0.9,
    )


def test_init_creates_git_repo(tmp_path: Path) -> None:
    git = EvolutionGitStore(tmp_path)

    assert git.init() is True
    assert (tmp_path / ".git").is_dir()
    assert "# nanobot evolution skills" in (tmp_path / ".gitignore").read_text(encoding="utf-8")


def test_apply_and_commit_records_evolve_history(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    git = EvolutionGitStore(tmp_path)
    proposal_id = _pending_proposal(store)

    result = store.apply_and_commit(proposal_id, git_store=git)

    assert result.ok is True
    assert result.commit_sha
    assert len(result.commit_sha) == 8
    commits = git.log()
    assert len(commits) == 1
    assert commits[0].message == "evolve: create skill deploy-k8s"
    assert commits[0].sha == result.commit_sha


def test_second_skill_commit_appends_log(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    git = EvolutionGitStore(tmp_path)

    first_id = _pending_proposal(store, skill_name="deploy-k8s")
    second_id = _pending_proposal(store, skill_name="lint-python")

    store.apply_and_commit(first_id, git_store=git)
    store.apply_and_commit(second_id, git_store=git)

    commits = git.log()
    assert len(commits) == 2
    assert commits[0].message == "evolve: create skill lint-python"
    assert commits[1].message == "evolve: create skill deploy-k8s"


def test_proposals_dir_is_not_committed(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    git = EvolutionGitStore(tmp_path)
    proposal_id = _pending_proposal(store)
    store.apply_and_commit(proposal_id, git_store=git)

    from dulwich.repo import Repo

    with Repo(str(tmp_path)) as repo:
        head = repo[repo.refs[b"HEAD"]]
        tree_paths = set(EvolutionGitStore._skill_paths_in_tree(repo, repo[head.tree]))
        assert not any(".proposals" in path for path in tree_paths)
        assert "skills/deploy-k8s/SKILL.md" in tree_paths


def test_restore_reverts_created_skill(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    git = EvolutionGitStore(tmp_path)
    proposal_id = _pending_proposal(store)
    result = store.apply_and_commit(proposal_id, git_store=git)
    assert result.commit_sha

    revert_sha = git.restore(result.commit_sha)
    assert revert_sha

    active = tmp_path / "skills" / "deploy-k8s" / "SKILL.md"
    assert not active.exists()
    commits = git.log(max_entries=5)
    assert commits[0].message.startswith("evolve: revert")


def test_merge_gitignore_when_dream_repo_exists(tmp_path: Path) -> None:
    from nanobot.utils.gitstore import GitStore

    dream = GitStore(
        tmp_path,
        tracked_files=["SOUL.md", "USER.md", "memory/MEMORY.md"],
    )
    dream.init()

    git = EvolutionGitStore(tmp_path)
    assert git.init() is False
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "# nanobot evolution skills" in content
    assert "!/skills/*/" in content

    store = ProposalStore(tmp_path)
    proposal_id = _pending_proposal(store)
    result = store.apply_and_commit(proposal_id, git_store=git)
    assert result.ok is True
    assert result.commit_sha


def test_log_ignores_non_evolve_commits(tmp_path: Path) -> None:
    from dulwich import porcelain

    git = EvolutionGitStore(tmp_path)
    git.init()
    porcelain.commit(
        str(tmp_path),
        message=b"dream: update soul",
        author=b"nanobot <nanobot@dream>",
        committer=b"nanobot <nanobot@dream>",
    )

    store = ProposalStore(tmp_path)
    proposal_id = _pending_proposal(store)
    store.apply_and_commit(proposal_id, git_store=git)

    commits = git.log()
    assert len(commits) == 1
    assert commits[0].message.startswith("evolve:")


def test_commit_update_message(tmp_path: Path) -> None:
    git = EvolutionGitStore(tmp_path)
    git.init()
    skill_dir = tmp_path / "skills" / "deploy-k8s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_VALID_SKILL_MD, encoding="utf-8")

    sha = git.commit_create("deploy-k8s")
    assert sha
    (skill_dir / "SKILL.md").write_text(_VALID_SKILL_MD + "\n\nUpdated.", encoding="utf-8")
    update_sha = git.commit_update("deploy-k8s", source="gepa")

    assert update_sha
    assert git.log()[0].message == "evolve: update skill deploy-k8s (gepa)"
