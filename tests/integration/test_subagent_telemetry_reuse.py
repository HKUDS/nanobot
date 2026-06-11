"""Spec §4.4 + §7: a subagent spawned by SubagentManager must share the parent
AgentLoop's SkillTelemetry instance — never create its own (M1 Task E2)."""

from __future__ import annotations

from pathlib import Path


def test_subagent_skills_loader_shares_parent_telemetry(tmp_path: Path) -> None:
    from nanobot.agent.skills_telemetry import SkillTelemetry
    from nanobot.agent.subagent import SubagentManager

    workspace = tmp_path
    (workspace / "skills" / "alpha").mkdir(parents=True)
    (workspace / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: a\n---\nbody"
    )

    parent_telemetry = SkillTelemetry(workspace=workspace)
    mgr = SubagentManager(
        provider=object(),
        workspace=workspace,
        bus=None,
        max_tool_result_chars=10_000,
        model="m",
        telemetry=parent_telemetry,
    )

    # _build_subagent_prompt constructs an inner SkillsLoader that should be
    # threaded with the parent's telemetry instance; calling it bumps `view`
    # for every skill returned by build_skills_summary.
    _ = mgr._build_subagent_prompt(workspace=workspace)

    snapshot = parent_telemetry.snapshot()
    assert "alpha" in snapshot["entries"]
    assert snapshot["entries"]["alpha"]["views"] >= 1


def test_subagent_does_not_create_second_telemetry_file(tmp_path: Path) -> None:
    """Smoke: no extra .telemetry.json* artefacts beyond the parent's one."""
    from nanobot.agent.skills_telemetry import SkillTelemetry
    from nanobot.agent.subagent import SubagentManager

    workspace = tmp_path
    (workspace / "skills" / "alpha").mkdir(parents=True)
    (workspace / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: a\n---\nbody"
    )

    parent_telemetry = SkillTelemetry(workspace=workspace)
    mgr = SubagentManager(
        provider=object(),
        workspace=workspace,
        bus=None,
        max_tool_result_chars=10_000,
        model="m",
        telemetry=parent_telemetry,
    )
    mgr._build_subagent_prompt(workspace=workspace)
    parent_telemetry.flush()

    files = sorted(
        p.name for p in (workspace / "skills").iterdir() if p.name.startswith(".telemetry")
    )
    # Exactly the canonical telemetry file — no parallel subagent-owned copy
    # and no stale .tmp residue (A11 cleanup runs in SkillTelemetry.__init__).
    assert files == [".telemetry.json"]
