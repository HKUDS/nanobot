"""Tests for nanobot.agent.skills.SkillsLoader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.skills import BUILTIN_SKILLS_DIR, SkillsLoader


def _write_skill(
    base: Path,
    name: str,
    *,
    metadata_json: dict | None = None,
    body: str = "# Skill\n",
) -> Path:
    """Create ``base / name / SKILL.md`` with optional nanobot metadata JSON."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True)
    lines = ["---"]
    if metadata_json is not None:
        payload = json.dumps({"nanobot": metadata_json}, separators=(",", ":"))
        lines.append(f'metadata: {payload}')
    lines.extend(["---", "", body])
    path = skill_dir / "SKILL.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_list_skills_empty_when_skills_dir_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    assert loader.list_skills(filter_unavailable=False) == []


def test_list_skills_empty_when_skills_dir_exists_but_empty(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "skills").mkdir(parents=True)
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    assert loader.list_skills(filter_unavailable=False) == []


def test_list_skills_workspace_entry_shape_and_source(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    skills_root = workspace / "skills"
    skills_root.mkdir(parents=True)
    skill_path = _write_skill(skills_root, "alpha", body="# Alpha")
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    entries = loader.list_skills(filter_unavailable=False)
    assert entries == [
        {"name": "alpha", "path": str(skill_path), "source": "workspace"},
    ]


def test_list_skills_skips_non_directories_and_missing_skill_md(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    skills_root = workspace / "skills"
    skills_root.mkdir(parents=True)
    (skills_root / "not_a_dir.txt").write_text("x", encoding="utf-8")
    (skills_root / "no_skill_md").mkdir()
    ok_path = _write_skill(skills_root, "ok", body="# Ok")
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    entries = loader.list_skills(filter_unavailable=False)
    names = {entry["name"] for entry in entries}
    assert names == {"ok"}
    assert entries[0]["path"] == str(ok_path)


def test_list_skills_workspace_shadows_builtin_same_name(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    ws_path = _write_skill(ws_skills, "dup", body="# Workspace wins")

    builtin = tmp_path / "builtin"
    _write_skill(builtin, "dup", body="# Builtin")

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    entries = loader.list_skills(filter_unavailable=False)
    assert len(entries) == 1
    assert entries[0]["source"] == "workspace"
    assert entries[0]["path"] == str(ws_path)


def test_list_skills_merges_workspace_and_builtin(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    ws_path = _write_skill(ws_skills, "ws_only", body="# W")
    builtin = tmp_path / "builtin"
    bi_path = _write_skill(builtin, "bi_only", body="# B")

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    entries = sorted(loader.list_skills(filter_unavailable=False), key=lambda item: item["name"])
    assert entries == [
        {"name": "bi_only", "path": str(bi_path), "source": "builtin"},
        {"name": "ws_only", "path": str(ws_path), "source": "workspace"},
    ]


def test_list_skills_builtin_omitted_when_dir_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    ws_path = _write_skill(ws_skills, "solo", body="# S")
    missing_builtin = tmp_path / "no_such_builtin"

    loader = SkillsLoader(workspace, builtin_skills_dir=missing_builtin)
    entries = loader.list_skills(filter_unavailable=False)
    assert entries == [{"name": "solo", "path": str(ws_path), "source": "workspace"}]


def test_list_skills_filter_unavailable_excludes_unmet_bin_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_root = workspace / "skills"
    skills_root.mkdir(parents=True)
    _write_skill(
        skills_root,
        "needs_bin",
        metadata_json={"requires": {"bins": ["nanobot_test_fake_binary"]}},
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    def fake_which(cmd: str) -> str | None:
        if cmd == "nanobot_test_fake_binary":
            return None
        return "/usr/bin/true"

    monkeypatch.setattr("nanobot.agent.skills.shutil.which", fake_which)

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    assert loader.list_skills(filter_unavailable=True) == []


def test_list_skills_filter_unavailable_includes_when_bin_requirement_met(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_root = workspace / "skills"
    skills_root.mkdir(parents=True)
    skill_path = _write_skill(
        skills_root,
        "has_bin",
        metadata_json={"requires": {"bins": ["nanobot_test_fake_binary"]}},
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    def fake_which(cmd: str) -> str | None:
        if cmd == "nanobot_test_fake_binary":
            return "/fake/nanobot_test_fake_binary"
        return None

    monkeypatch.setattr("nanobot.agent.skills.shutil.which", fake_which)

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    entries = loader.list_skills(filter_unavailable=True)
    assert entries == [
        {"name": "has_bin", "path": str(skill_path), "source": "workspace"},
    ]


def test_list_skills_filter_unavailable_false_keeps_unmet_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_root = workspace / "skills"
    skills_root.mkdir(parents=True)
    skill_path = _write_skill(
        skills_root,
        "blocked",
        metadata_json={"requires": {"bins": ["nanobot_test_fake_binary"]}},
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    monkeypatch.setattr("nanobot.agent.skills.shutil.which", lambda _cmd: None)

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    entries = loader.list_skills(filter_unavailable=False)
    assert entries == [
        {"name": "blocked", "path": str(skill_path), "source": "workspace"},
    ]


def test_list_skills_filter_unavailable_excludes_unmet_env_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_root = workspace / "skills"
    skills_root.mkdir(parents=True)
    _write_skill(
        skills_root,
        "needs_env",
        metadata_json={"requires": {"env": ["NANOBOT_SKILLS_TEST_ENV_VAR"]}},
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    monkeypatch.delenv("NANOBOT_SKILLS_TEST_ENV_VAR", raising=False)

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    assert loader.list_skills(filter_unavailable=True) == []


def test_list_skills_openclaw_metadata_parsed_for_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_root = workspace / "skills"
    skills_root.mkdir(parents=True)
    skill_dir = skills_root / "openclaw_skill"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    oc_payload = json.dumps({"openclaw": {"requires": {"bins": ["nanobot_oc_bin"]}}}, separators=(",", ":"))
    skill_path.write_text(
        "\n".join(["---", f"metadata: {oc_payload}", "---", "", "# OC"]),
        encoding="utf-8",
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    monkeypatch.setattr("nanobot.agent.skills.shutil.which", lambda _cmd: None)

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    assert loader.list_skills(filter_unavailable=True) == []

    monkeypatch.setattr(
        "nanobot.agent.skills.shutil.which",
        lambda cmd: "/x" if cmd == "nanobot_oc_bin" else None,
    )
    entries = loader.list_skills(filter_unavailable=True)
    assert entries == [
        {"name": "openclaw_skill", "path": str(skill_path), "source": "workspace"},
    ]


def test_disabled_skills_excluded_from_list(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    _write_skill(ws_skills, "alpha", body="# Alpha")
    beta_path = _write_skill(ws_skills, "beta", body="# Beta")
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin, disabled_skills={"alpha"})
    entries = loader.list_skills(filter_unavailable=False)
    assert len(entries) == 1
    assert entries[0]["name"] == "beta"
    assert entries[0]["path"] == str(beta_path)


def test_disabled_skills_empty_set_no_effect(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    _write_skill(ws_skills, "alpha", body="# Alpha")
    _write_skill(ws_skills, "beta", body="# Beta")
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin, disabled_skills=set())
    entries = loader.list_skills(filter_unavailable=False)
    assert len(entries) == 2


def test_disabled_skills_excluded_from_build_skills_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    _write_skill(ws_skills, "alpha", body="# Alpha")
    _write_skill(ws_skills, "beta", body="# Beta")
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin, disabled_skills={"alpha"})
    summary = loader.build_skills_summary()
    assert "alpha" not in summary
    assert "beta" in summary


def test_disabled_skills_excluded_from_get_always_skills(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    _write_skill(ws_skills, "alpha", metadata_json={"always": True}, body="# Alpha")
    _write_skill(ws_skills, "beta", metadata_json={"always": True}, body="# Beta")
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin, disabled_skills={"alpha"})
    always = loader.get_always_skills()
    assert "alpha" not in always
    assert "beta" in always


# -- multiline description tests (YAML folded > and literal |) -----------------


def test_build_skills_summary_folded_description(tmp_path: Path) -> None:
    """description: > (YAML folded scalar) should be parsed correctly."""
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    skill_dir = ws_skills / "pdf"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        "name: pdf\n"
        "description: >\n"
        "  Use this skill when visual quality and design identity matter for a PDF.\n"
        "  CREATE (generate from scratch): \"make a PDF\".\n"
        "---\n\n# PDF Skill\n",
        encoding="utf-8",
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    summary = loader.build_skills_summary()
    assert "pdf" in summary
    assert "visual quality" in summary


def test_build_skills_summary_literal_description(tmp_path: Path) -> None:
    """description: | (YAML literal scalar) should be parsed correctly."""
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    skill_dir = ws_skills / "multi"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        "name: multi\n"
        "description: |\n"
        "  Line one of description.\n"
        "  Line two of description.\n"
        "---\n\n# Multi\n",
        encoding="utf-8",
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    meta = loader.get_skill_metadata("multi")
    assert meta is not None
    desc = meta.get("description")
    assert isinstance(desc, str)
    assert "Line one" in desc
    assert "Line two" in desc


def test_get_skill_metadata_handles_yaml_types(tmp_path: Path) -> None:
    """yaml.safe_load returns native types; always should be True, not 'true'."""
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    skill_dir = ws_skills / "typed"
    skill_dir.mkdir(parents=True)
    payload = json.dumps({"nanobot": {"requires": {"bins": ["gh"]}, "always": True}}, separators=(",", ":"))
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        "name: typed\n"
        f"metadata: {payload}\n"
        "always: true\n"
        "---\n\n# Typed\n",
        encoding="utf-8",
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    meta = loader.get_skill_metadata("typed")
    assert meta is not None
    # YAML parsed 'true' to Python True
    assert meta.get("always") is True
    # metadata is a parsed dict, not a JSON string
    assert isinstance(meta.get("metadata"), dict)


def test_infer_origin_user(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path)
    p = tmp_path / "skills" / "foo" / "SKILL.md"
    assert loader._infer_origin_from_path(p) == "user"


def test_infer_origin_agent(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path)
    p = tmp_path / "skills" / "agent" / "foo" / "SKILL.md"
    assert loader._infer_origin_from_path(p) == "agent"


def test_infer_origin_builtin(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path)
    p = BUILTIN_SKILLS_DIR / "foo" / "SKILL.md"
    assert loader._infer_origin_from_path(p) == "builtin"


def test_agent_subdir_not_treated_as_top_level_skill(tmp_path: Path) -> None:
    # User has <workspace>/skills/agent/foo/SKILL.md
    skills_dir = tmp_path / "skills"
    (skills_dir / "agent" / "foo").mkdir(parents=True)
    (skills_dir / "agent" / "foo" / "SKILL.md").write_text("---\nname: foo\n---\nbody")
    (skills_dir / "real-user-skill").mkdir()
    (skills_dir / "real-user-skill" / "SKILL.md").write_text("---\nname: rus\n---\nbody")

    loader = SkillsLoader(tmp_path)
    names = {e["name"] for e in loader.list_skills(filter_unavailable=False)}
    # "agent" itself MUST NOT appear as a skill name
    assert "agent" not in names
    # The agent-source skill MUST appear under its real name
    assert "foo" in names
    assert "real-user-skill" in names


def test_entries_from_agent_dir_returns_real_skill_entries(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills" / "agent"
    skills_dir.mkdir(parents=True)
    (skills_dir / "auto-sum").mkdir()
    (skills_dir / "auto-sum" / "SKILL.md").write_text("---\nname: auto-sum\n---\nbody")
    loader = SkillsLoader(tmp_path)
    entries = loader._entries_from_agent_dir()
    assert any(e["name"] == "auto-sum" for e in entries)
    # Source field stays "workspace" per spec §3.1
    assert all(e["source"] == "workspace" for e in entries)


def test_list_skills_priority_user_over_agent_over_builtin(
    tmp_path: Path, monkeypatch
) -> None:
    # All three sources have "summarize"
    builtin = tmp_path / "_fake_builtin"
    builtin.mkdir()
    (builtin / "summarize").mkdir()
    (builtin / "summarize" / "SKILL.md").write_text(
        "---\nname: summarize\n---\nbuiltin-body"
    )

    agent_dir = tmp_path / "skills" / "agent" / "summarize"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text("---\nname: summarize\n---\nagent-body")

    user_dir = tmp_path / "skills" / "summarize"
    user_dir.mkdir()
    (user_dir / "SKILL.md").write_text("---\nname: summarize\n---\nuser-body")

    loader = SkillsLoader(tmp_path, builtin_skills_dir=builtin)
    entries = loader.list_skills(filter_unavailable=False)
    names = [e["name"] for e in entries]
    # exactly one "summarize"; the user copy wins
    assert names.count("summarize") == 1
    winner = next(e for e in entries if e["name"] == "summarize")
    assert winner["path"] == str(user_dir / "SKILL.md")


def test_collision_warning_logged_once_per_loader(
    tmp_path: Path, loguru_caplog
) -> None:
    builtin = tmp_path / "_fake_builtin"
    builtin.mkdir()
    (builtin / "dup").mkdir()
    (builtin / "dup" / "SKILL.md").write_text("---\nname: dup\n---\nb")
    user = tmp_path / "skills" / "dup"
    user.mkdir(parents=True)
    (user / "SKILL.md").write_text("---\nname: dup\n---\nu")

    loader = SkillsLoader(tmp_path, builtin_skills_dir=builtin)
    loader.list_skills()
    loader.list_skills()
    loader.list_skills()
    collisions = [
        r for r in loguru_caplog.records if "collision" in r.getMessage().lower()
    ]
    assert len(collisions) == 1


def test_list_skills_with_shadows_three_source(tmp_path: Path) -> None:
    builtin = tmp_path / "_b"
    builtin.mkdir()
    (builtin / "x").mkdir()
    (builtin / "x" / "SKILL.md").write_text("---\nname: x\n---\nb")
    (tmp_path / "skills" / "agent" / "x").mkdir(parents=True)
    (tmp_path / "skills" / "agent" / "x" / "SKILL.md").write_text("---\nname: x\n---\na")
    (tmp_path / "skills" / "x").mkdir(parents=True)
    (tmp_path / "skills" / "x" / "SKILL.md").write_text("---\nname: x\n---\nu")
    (tmp_path / "skills" / "y").mkdir()
    (tmp_path / "skills" / "y" / "SKILL.md").write_text("---\nname: y\n---\nu")
    loader = SkillsLoader(tmp_path, builtin_skills_dir=builtin)
    rows = loader.list_skills_with_shadows()
    by_name = {r["name"]: r for r in rows}
    assert by_name["x"]["effective_origin"] == "user"
    assert set(by_name["x"]["shadowed_origins"]) == {"agent", "builtin"}
    assert by_name["y"]["effective_origin"] == "user"
    assert by_name["y"]["shadowed_origins"] == []


def test_list_skills_with_shadows_respects_disabled(tmp_path: Path) -> None:
    builtin = tmp_path / "_b"
    builtin.mkdir()
    (tmp_path / "skills" / "foo").mkdir(parents=True)
    (tmp_path / "skills" / "foo" / "SKILL.md").write_text("---\nname: foo\n---\n")
    (tmp_path / "skills" / "bar").mkdir()
    (tmp_path / "skills" / "bar" / "SKILL.md").write_text("---\nname: bar\n---\n")
    loader = SkillsLoader(tmp_path, builtin_skills_dir=builtin, disabled_skills={"bar"})
    rows = loader.list_skills_with_shadows()
    names = {r["name"] for r in rows}
    assert names == {"foo"}


def test_list_skills_with_shadows_does_not_call_get_skill_meta(
    tmp_path: Path, monkeypatch
) -> None:
    builtin = tmp_path / "_b"
    builtin.mkdir()
    (tmp_path / "skills" / "foo").mkdir(parents=True)
    (tmp_path / "skills" / "foo" / "SKILL.md").write_text("---\nname: foo\n---\n")
    loader = SkillsLoader(tmp_path, builtin_skills_dir=builtin)
    calls: list = []
    monkeypatch.setattr(loader, "_get_skill_meta", lambda n: calls.append(n) or {})
    loader.list_skills_with_shadows()
    assert calls == []  # MUST NOT touch frontmatter


def test_telemetry_param_is_keyword_only(tmp_path: Path) -> None:
    from nanobot.agent.skills_telemetry import SkillTelemetry

    telem = SkillTelemetry(tmp_path / "ws")
    # Keyword form must work
    loader = SkillsLoader(tmp_path / "ws", telemetry=telem)
    assert loader.telemetry is telem
    # Positional form must raise TypeError (telemetry is keyword-only)
    with pytest.raises(TypeError):
        SkillsLoader(tmp_path / "ws", None, None, telem)  # type: ignore[misc]


def test_telemetry_default_is_none(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path)
    assert loader.telemetry is None


def test_build_skills_summary_bumps_view_per_returned_skill(tmp_path: Path) -> None:
    from nanobot.agent.skills_telemetry import SkillTelemetry
    (tmp_path / "skills" / "foo").mkdir(parents=True)
    (tmp_path / "skills" / "foo" / "SKILL.md").write_text(
        "---\nname: foo\ndescription: f\n---\nbody"
    )
    (tmp_path / "skills" / "bar").mkdir()
    (tmp_path / "skills" / "bar" / "SKILL.md").write_text(
        "---\nname: bar\ndescription: b\n---\nbody"
    )
    builtin = tmp_path / "_b"
    builtin.mkdir()
    telem = SkillTelemetry(tmp_path)
    loader = SkillsLoader(tmp_path, builtin_skills_dir=builtin, telemetry=telem)
    summary = loader.build_skills_summary()
    assert "foo" in summary and "bar" in summary
    snap = telem.snapshot()
    assert snap["entries"]["foo"]["views"] == 1
    assert snap["entries"]["bar"]["views"] == 1


def test_build_skills_summary_no_bump_when_telemetry_none(tmp_path: Path) -> None:
    (tmp_path / "skills" / "foo").mkdir(parents=True)
    (tmp_path / "skills" / "foo" / "SKILL.md").write_text(
        "---\nname: foo\ndescription: f\n---\n"
    )
    builtin = tmp_path / "_b"
    builtin.mkdir()
    loader = SkillsLoader(tmp_path, builtin_skills_dir=builtin, telemetry=None)
    # Must not raise — physically impossible to bump.
    loader.build_skills_summary()


def test_load_skills_for_context_bumps_use_per_loaded_skill(tmp_path: Path) -> None:
    from nanobot.agent.skills_telemetry import SkillTelemetry
    (tmp_path / "skills" / "foo").mkdir(parents=True)
    (tmp_path / "skills" / "foo" / "SKILL.md").write_text(
        "---\nname: foo\n---\nfoo-body"
    )
    (tmp_path / "skills" / "bar").mkdir()
    (tmp_path / "skills" / "bar" / "SKILL.md").write_text(
        "---\nname: bar\n---\nbar-body"
    )
    builtin = tmp_path / "_b"
    builtin.mkdir()
    telem = SkillTelemetry(tmp_path)
    loader = SkillsLoader(tmp_path, builtin_skills_dir=builtin, telemetry=telem)
    out = loader.load_skills_for_context(["foo", "bar"])
    assert "foo-body" in out and "bar-body" in out
    snap = telem.snapshot()
    assert snap["entries"]["foo"]["uses"] == 1
    assert snap["entries"]["bar"]["uses"] == 1


def test_load_skills_for_context_does_not_bump_missing_skill(tmp_path: Path) -> None:
    from nanobot.agent.skills_telemetry import SkillTelemetry
    builtin = tmp_path / "_b"
    builtin.mkdir()
    telem = SkillTelemetry(tmp_path)
    loader = SkillsLoader(tmp_path, builtin_skills_dir=builtin, telemetry=telem)
    loader.load_skills_for_context(["does-not-exist"])
    snap = telem.snapshot()
    # Per spec §7 row (e): bump only after load success → no entry for missing skill
    assert "does-not-exist" not in snap["entries"]
