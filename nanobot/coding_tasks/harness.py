"""Harness detection and Codex bootstrap prompt construction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RepoHarnessState:
    """Detected harness-related files in a target repository."""

    repo_path: str
    has_plan: bool
    has_progress: bool
    has_init: bool

    @property
    def harness_state(self) -> str:
        if self.has_plan and self.has_progress and self.has_init:
            return "active"
        if self.has_plan or self.has_progress or self.has_init:
            return "initializing"
        return "missing"


def detect_repo_harness(repo_path: str | Path) -> RepoHarnessState:
    """Inspect a repository for standard long-running harness files."""
    root = Path(repo_path).expanduser().resolve()
    return RepoHarnessState(
        repo_path=str(root),
        has_plan=(root / "PLAN.json").exists(),
        has_progress=(root / "PROGRESS.md").exists(),
        has_init=(root / "init.sh").exists(),
    )


def build_codex_bootstrap_prompt(
    *,
    repo_path: str | Path,
    goal: str,
    branch_name: str | None = None,
    approval_policy: str = "local_only",
    harness: RepoHarnessState | None = None,
) -> str:
    """Build the initial prompt nanobot should send to Codex for a coding task."""
    state = harness or detect_repo_harness(repo_path)
    root = Path(repo_path).expanduser().resolve()
    lines = [
        "You are Codex running as nanobot's coding worker.",
        f"Target repository: {root}",
        f"Task goal: {goal}",
        f"Approval policy: {approval_policy}",
    ]
    if branch_name:
        lines.append(f"Preferred branch: {branch_name}")

    lines.extend(
        [
            "Execution boundaries:",
            "- You may read and edit repository files, run local tests, and create local commits when appropriate.",
            "- Do not push, deploy, or perform external side effects unless nanobot explicitly says so.",
            "- Follow the repository's AGENTS.md and local instructions without overwriting them.",
        ]
    )
    if (root / "AGENTS.md").exists():
        lines.append("Repository instructions detected: read AGENTS.md before any edits.")

    if state.harness_state == "active":
        lines.extend(
            [
                "Harness mode: existing harness detected.",
                "Before editing anything, restore the repository state:",
                "1. Read PROGRESS.md.",
                "2. Read PLAN.json.",
                "3. Run the repository startup sequence, including init.sh if present.",
                "4. Verify existing functionality still works before new edits.",
                "Only after restoring context should you continue the requested task goal.",
            ]
        )
    else:
        lines.extend(
            [
                "Harness mode: no complete harness detected.",
                "Before implementing the task goal, initialize the repository harness:",
                "1. Create a granular PLAN.json that tracks the remaining work.",
                "2. Create PROGRESS.md with the initial state and key decisions.",
                "3. Create init.sh for repeatable startup and validation.",
                "4. Commit the harness scaffolding before feature work if the repository instructions allow it.",
                "After initialization, continue with the requested task goal.",
            ]
        )
        if state.harness_state == "initializing":
            lines.append(
                "Some harness files already exist, so preserve and complete the partial harness instead of replacing it."
            )

    return "\n".join(lines)
