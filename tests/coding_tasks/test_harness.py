from pathlib import Path

from nanobot.coding_tasks.harness import build_codex_bootstrap_prompt, detect_repo_harness


def test_detect_repo_harness_distinguishes_active_and_missing(tmp_path: Path) -> None:
    active_repo = tmp_path / "active-repo"
    active_repo.mkdir()
    (active_repo / "PLAN.json").write_text("[]", encoding="utf-8")
    (active_repo / "PROGRESS.md").write_text("progress", encoding="utf-8")
    (active_repo / "init.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    missing_repo = tmp_path / "missing-repo"
    missing_repo.mkdir()

    active = detect_repo_harness(active_repo)
    missing = detect_repo_harness(missing_repo)

    assert active.has_plan is True
    assert active.has_progress is True
    assert active.has_init is True
    assert active.harness_state == "active"

    assert missing.has_plan is False
    assert missing.has_progress is False
    assert missing.has_init is False
    assert missing.harness_state == "missing"


def test_detect_repo_harness_marks_partial_harness_as_initializing(tmp_path: Path) -> None:
    partial_repo = tmp_path / "partial-repo"
    partial_repo.mkdir()
    (partial_repo / "PROGRESS.md").write_text("progress", encoding="utf-8")

    detected = detect_repo_harness(partial_repo)

    assert detected.has_plan is False
    assert detected.has_progress is True
    assert detected.has_init is False
    assert detected.harness_state == "initializing"


def test_build_codex_bootstrap_prompt_for_existing_harness_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("Follow repo rules", encoding="utf-8")
    (repo / "PLAN.json").write_text("[]", encoding="utf-8")
    (repo / "PROGRESS.md").write_text("progress", encoding="utf-8")
    (repo / "init.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    prompt = build_codex_bootstrap_prompt(
        repo_path=repo,
        goal="Implement feature 14",
        branch_name="codex/test-branch",
    )

    assert "Harness mode: existing harness detected." in prompt
    assert "Read PROGRESS.md." in prompt
    assert "Read PLAN.json." in prompt
    assert "Run the repository startup sequence, including init.sh if present." in prompt
    assert "Task goal: Implement feature 14" in prompt
    assert "Preferred branch: codex/test-branch" in prompt
    assert "Do not push, deploy, or perform external side effects" in prompt
    assert "Repository instructions detected: read AGENTS.md before any edits." in prompt


def test_build_codex_bootstrap_prompt_for_missing_harness_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    prompt = build_codex_bootstrap_prompt(
        repo_path=repo,
        goal="Implement feature 15",
    )

    assert "Harness mode: no complete harness detected." in prompt
    assert "Create a granular PLAN.json" in prompt
    assert "Create PROGRESS.md" in prompt
    assert "Create init.sh" in prompt
    assert "After initialization, continue with the requested task goal." in prompt
    assert "Task goal: Implement feature 15" in prompt
