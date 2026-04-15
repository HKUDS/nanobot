"""Tests for nanobot.agent.tools.skills (SkillsListTool, SkillViewTool)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.skills import SkillsListTool, SkillViewTool


def _make_loader(tmp_path: Path) -> tuple[SkillsLoader, Path, Path]:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    return loader, ws_skills, builtin


def _write_skill(
    base: Path,
    name: str,
    *,
    description: str = "",
    body: str = "# Skill\n",
) -> Path:
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    if description:
        lines.append(f"description: {description}")
    lines.extend(["---", "", body])
    path = skill_dir / "SKILL.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# SkillsListTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skills_list_returns_source_and_mutable(tmp_path: Path) -> None:
    loader, ws_skills, builtin = _make_loader(tmp_path)
    _write_skill(ws_skills, "ws-skill", description="workspace skill")
    _write_skill(builtin, "bi-skill", description="builtin skill")

    tool = SkillsListTool(catalog=loader)
    raw = await tool.execute()
    data = json.loads(raw)
    assert data["success"]
    assert data["count"] == 2

    by_name = {s["name"]: s for s in data["skills"]}
    assert by_name["ws-skill"]["source"] == "workspace"
    assert by_name["ws-skill"]["mutable"] is True
    assert by_name["bi-skill"]["source"] == "builtin"
    assert by_name["bi-skill"]["mutable"] is False


@pytest.mark.asyncio
async def test_skills_list_category_filter(tmp_path: Path) -> None:
    loader, ws_skills, _ = _make_loader(tmp_path)
    _write_skill(ws_skills, "feishu-card", description="feishu card")
    _write_skill(ws_skills, "weather", description="weather")

    tool = SkillsListTool(catalog=loader)
    raw = await tool.execute(category="feishu")
    data = json.loads(raw)
    assert data["count"] == 1
    assert data["skills"][0]["name"] == "feishu-card"


@pytest.mark.asyncio
async def test_skills_list_includes_supporting_files(tmp_path: Path) -> None:
    loader, ws_skills, _ = _make_loader(tmp_path)
    _write_skill(ws_skills, "with-refs", description="has refs")
    ref_dir = ws_skills / "with-refs" / "references"
    ref_dir.mkdir()
    (ref_dir / "api.md").write_text("# API", encoding="utf-8")

    tool = SkillsListTool(catalog=loader)
    raw = await tool.execute()
    data = json.loads(raw)
    skill = data["skills"][0]
    assert skill["supporting_files"] == {"references": ["references/api.md"]}


@pytest.mark.asyncio
async def test_skills_list_empty(tmp_path: Path) -> None:
    loader, _, _ = _make_loader(tmp_path)
    tool = SkillsListTool(catalog=loader)
    raw = await tool.execute()
    data = json.loads(raw)
    assert data["success"]
    assert data["count"] == 0
    assert data["skills"] == []


# ---------------------------------------------------------------------------
# SkillViewTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_view_returns_content(tmp_path: Path) -> None:
    loader, ws_skills, _ = _make_loader(tmp_path)
    _write_skill(ws_skills, "alpha", description="A skill", body="Do alpha things.")

    tool = SkillViewTool(catalog=loader)
    raw = await tool.execute(name="alpha")
    data = json.loads(raw)
    assert data["success"]
    assert data["name"] == "alpha"
    assert "Do alpha things." in data["content"]
    assert data["source"] == "workspace"
    assert data["mutable"] is True


@pytest.mark.asyncio
async def test_skill_view_reads_supporting_file(tmp_path: Path) -> None:
    loader, ws_skills, _ = _make_loader(tmp_path)
    _write_skill(ws_skills, "beta")
    ref_dir = ws_skills / "beta" / "references"
    ref_dir.mkdir()
    (ref_dir / "spec.md").write_text("# Spec content", encoding="utf-8")

    tool = SkillViewTool(catalog=loader)
    raw = await tool.execute(name="beta", file_path="references/spec.md")
    data = json.loads(raw)
    assert data["success"]
    assert data["content"] == "# Spec content"


@pytest.mark.asyncio
async def test_skill_view_rejects_path_traversal(tmp_path: Path) -> None:
    loader, ws_skills, _ = _make_loader(tmp_path)
    _write_skill(ws_skills, "gamma")

    tool = SkillViewTool(catalog=loader)
    raw = await tool.execute(name="gamma", file_path="../../../etc/passwd")
    data = json.loads(raw)
    assert not data["success"]
    assert "not found or not accessible" in data["error"]


@pytest.mark.asyncio
async def test_skill_view_rejects_unknown_subdir(tmp_path: Path) -> None:
    loader, ws_skills, _ = _make_loader(tmp_path)
    _write_skill(ws_skills, "delta")
    (ws_skills / "delta" / "secrets").mkdir()
    (ws_skills / "delta" / "secrets" / "key.pem").write_text("secret", encoding="utf-8")

    tool = SkillViewTool(catalog=loader)
    raw = await tool.execute(name="delta", file_path="secrets/key.pem")
    data = json.loads(raw)
    assert not data["success"]


@pytest.mark.asyncio
async def test_skill_view_not_found(tmp_path: Path) -> None:
    loader, _, _ = _make_loader(tmp_path)
    tool = SkillViewTool(catalog=loader)
    raw = await tool.execute(name="nonexistent")
    data = json.loads(raw)
    assert not data["success"]
    assert "not found" in data["error"]


@pytest.mark.asyncio
async def test_skill_view_missing_name(tmp_path: Path) -> None:
    loader, _, _ = _make_loader(tmp_path)
    tool = SkillViewTool(catalog=loader)
    raw = await tool.execute()
    data = json.loads(raw)
    assert not data["success"]
    assert "required" in data["error"]


@pytest.mark.asyncio
async def test_skill_view_builtin_skill(tmp_path: Path) -> None:
    loader, _, builtin = _make_loader(tmp_path)
    _write_skill(builtin, "builtin-skill", description="A builtin", body="Builtin content.")

    tool = SkillViewTool(catalog=loader)
    raw = await tool.execute(name="builtin-skill")
    data = json.loads(raw)
    assert data["success"]
    assert data["source"] == "builtin"
    assert data["mutable"] is False
