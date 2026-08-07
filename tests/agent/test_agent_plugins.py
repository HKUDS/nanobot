import json
import shutil
from pathlib import Path

import pytest

from nanobot.agent.agent_plugins import AGENT_PLUGIN_SCHEMA, discover_agent_plugin_skills
from nanobot.agent.skills import SkillsLoader


def _write_skill(root: Path, name: str, *, description: str = "Plugin skill.") -> Path:
    skill = root / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return skill


def _write_plugin(
    workspace: Path,
    directory: str,
    *,
    name: str | None = None,
    manifest: dict[str, object] | None = None,
) -> Path:
    root = workspace / "plugins" / directory
    root.mkdir(parents=True)
    payload = manifest or {
        "$schema": AGENT_PLUGIN_SCHEMA,
        "name": name or directory,
    }
    (root / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_skills_loader_discovers_agent_plugin_skill(tmp_path: Path) -> None:
    plugin = _write_plugin(tmp_path, "acme-tools")
    _write_skill(plugin, "release-notes", description="Draft release notes from changes.")

    loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "builtin")

    assert loader.list_skills() == [
        {
            "name": "release-notes",
            "path": str(plugin / "skills" / "release-notes" / "SKILL.md"),
            "source": "plugin",
            "plugin": "acme-tools",
        }
    ]
    assert loader.get_explicitly_invoked_skills("Use $release-notes") == ["release-notes"]
    assert "Draft release notes" in (loader.load_skill("release-notes") or "")
    assert "### Agent Plugin skills" in loader.build_skills_summary()
    assert "`acme-tools/skills/release-notes/SKILL.md`" in loader.build_skills_summary()


def test_skills_loader_sees_plugin_installed_after_startup(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "builtin")
    assert loader.list_skills() == []

    plugin = _write_plugin(tmp_path, "acme-tools")
    _write_skill(plugin, "release-notes")

    assert [entry["name"] for entry in loader.list_skills()] == ["release-notes"]

    shutil.rmtree(plugin)

    assert loader.list_skills() == []
    assert loader.build_skills_summary() == ""


def test_agent_plugin_skills_are_direct_children_only(tmp_path: Path) -> None:
    plugin = _write_plugin(tmp_path, "acme-tools")
    _write_skill(plugin, "direct")
    nested = plugin / "skills" / "group" / "nested"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(
        "---\nname: nested\ndescription: Nested skill.\n---\n",
        encoding="utf-8",
    )

    assert [skill.name for skill in discover_agent_plugin_skills(tmp_path)] == ["direct"]


@pytest.mark.parametrize(
    "manifest",
    [
        {"$schema": "https://agent-plugins.org/schemas/2.0.0/plugin.schema.json", "name": "demo"},
        {"$schema": AGENT_PLUGIN_SCHEMA, "name": "Bad-Name"},
        {"$schema": AGENT_PLUGIN_SCHEMA, "name": "demo", "author": None},
        {"$schema": AGENT_PLUGIN_SCHEMA, "name": "demo", "keywords": None},
    ],
)
def test_invalid_agent_plugin_manifest_is_skipped(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    plugin = _write_plugin(tmp_path, "demo", manifest=manifest)
    _write_skill(plugin, "example")

    assert discover_agent_plugin_skills(tmp_path) == []


def test_unknown_manifest_fields_and_non_object_extensions_are_ignored(tmp_path: Path) -> None:
    plugin = _write_plugin(
        tmp_path,
        "demo",
        manifest={
            "$schema": AGENT_PLUGIN_SCHEMA,
            "name": "demo",
            "futureField": True,
            "extensions": "invalid but non-fatal",
        },
    )
    _write_skill(plugin, "example")

    assert [skill.name for skill in discover_agent_plugin_skills(tmp_path)] == ["example"]


@pytest.mark.parametrize(
    ("skill_name", "frontmatter"),
    [
        ("wrong-directory", "name: another\ndescription: Mismatch."),
        ("missing-description", "name: missing-description"),
        ("Bad-Name", "name: Bad-Name\ndescription: Invalid name."),
    ],
)
def test_invalid_agent_skill_is_skipped(
    tmp_path: Path,
    skill_name: str,
    frontmatter: str,
) -> None:
    plugin = _write_plugin(tmp_path, "demo")
    skill = plugin / "skills" / skill_name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n", encoding="utf-8")

    assert discover_agent_plugin_skills(tmp_path) == []


def test_workspace_skill_overrides_plugin_skill(tmp_path: Path) -> None:
    plugin = _write_plugin(tmp_path, "demo")
    _write_skill(plugin, "shared", description="Plugin version.")
    workspace_skill = tmp_path / "skills" / "shared"
    workspace_skill.mkdir(parents=True)
    (workspace_skill / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Workspace version.\n---\n",
        encoding="utf-8",
    )

    loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "builtin")

    assert [entry["source"] for entry in loader.list_skills()] == ["workspace"]
    assert "Workspace version" in (loader.load_skill("shared") or "")


def test_plugin_skill_symlink_cannot_escape_plugin_root(tmp_path: Path) -> None:
    plugin = _write_plugin(tmp_path, "demo")
    outside = tmp_path / "outside"
    _write_skill(outside, "escaped")
    skills_root = plugin / "skills"
    skills_root.mkdir()
    try:
        (skills_root / "escaped").symlink_to(
            outside / "skills" / "escaped",
            target_is_directory=True,
        )
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")

    assert discover_agent_plugin_skills(tmp_path) == []
