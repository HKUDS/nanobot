import json
import shutil
from pathlib import Path

import pytest

from nanobot.agent import plugins as agent_plugins
from nanobot.agent.plugins import (
    AGENT_PLUGIN_MCP_SCHEMA,
    AGENT_PLUGIN_SCHEMA,
    agent_plugin_mcp_servers,
    discover_agent_plugins,
    enabled_agent_plugin_skills,
    set_agent_plugin_enabled,
)
from nanobot.agent.skills import SkillsLoader


@pytest.fixture(autouse=True)
def _isolate_plugin_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_plugins, "get_config_path", lambda: tmp_path / "config" / "config.json"
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _manifest(name: str, **fields: object) -> dict[str, object]:
    return {"$schema": AGENT_PLUGIN_SCHEMA, "name": name, **fields}


def _plugin(workspace: Path, name: str = "demo", **fields: object) -> Path:
    root = workspace / "plugins" / name
    _write_json(root / "plugin.json", _manifest(name, **fields))
    return root


def _skill(root: Path, name: str, frontmatter: str | None = None, body: str = "") -> Path:
    path = root / name
    path.mkdir(parents=True)
    metadata = frontmatter or f"name: {name}\ndescription: Plugin skill."
    (path / "SKILL.md").write_text(f"---\n{metadata}\n---\n\n{body}\n", encoding="utf-8")
    return path


def _loaded_skills(workspace: Path) -> list[str]:
    return [name for name, _ in enabled_agent_plugin_skills(workspace)]


def test_plugin_skill_lifecycle_and_precedence(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path)
    _skill(
        plugin / "skills",
        "shared",
        "name: shared\ndescription: Plugin version.\nalways: true",
        "Plugin body.",
    )
    _skill(tmp_path / "builtin", "shared", body="Built-in body.")
    workspace_skill = _skill(
        tmp_path / "skills", "shared", "name: shared\ndescription: Workspace version."
    )
    loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "builtin")

    assert [entry["source"] for entry in loader.list_skills()] == ["workspace"]
    assert "Workspace version" in (loader.load_skill("shared") or "")
    set_agent_plugin_enabled(tmp_path, "demo", True)
    assert [entry["source"] for entry in loader.list_skills()] == ["workspace"]

    shutil.rmtree(workspace_skill)
    assert [entry["source"] for entry in loader.list_skills()] == ["plugin"]
    assert loader.get_explicitly_invoked_skills("Use $shared") == ["shared"]
    assert loader.get_always_skills() == ["shared"]
    assert "Plugin body" in (loader.load_skill("shared") or "")
    assert "`demo/skills/shared/SKILL.md`" in loader.build_skills_summary()

    set_agent_plugin_enabled(tmp_path, "demo", False)
    assert [entry["source"] for entry in loader.list_skills()] == ["builtin"]
    assert "Built-in body" in (loader.load_skill("shared") or "")


def test_plugin_skills_are_direct_valid_and_contained(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path)
    skills = plugin / "skills"
    _skill(skills, "direct")
    _skill(skills / "group", "nested")
    for name, frontmatter in (
        ("wrong-directory", "name: another\ndescription: Mismatch."),
        ("missing-description", "name: missing-description"),
        ("Bad-Name", "name: Bad-Name\ndescription: Invalid name."),
    ):
        _skill(skills, name, frontmatter)
    outside = _skill(tmp_path / "outside", "escaped")
    try:
        (skills / "escaped").symlink_to(outside, target_is_directory=True)
    except OSError:
        pass

    set_agent_plugin_enabled(tmp_path, "demo", True)
    assert _loaded_skills(tmp_path) == ["direct"]


@pytest.mark.parametrize(
    ("manifest", "valid"),
    [
        ({"$schema": "https://agent-plugins.org/schemas/2.0.0/plugin.schema.json", "name": "demo"}, False),
        (_manifest("Bad-Name"), False),
        (_manifest("demo", futureField=True, extensions="invalid but non-fatal"), True),
    ],
)
def test_plugin_manifest_boundary(tmp_path: Path, manifest: object, valid: bool) -> None:
    _write_json(tmp_path / "plugins" / "candidate" / "plugin.json", manifest)
    assert bool(discover_agent_plugins(tmp_path)) is valid


def test_plugin_logo_is_validated_and_contained(tmp_path: Path) -> None:
    extension = {"extensions": {"dev.nanobot": {"logo": "./assets/icon.png"}}}
    plugin = _plugin(tmp_path, "demo", **extension)
    icon = plugin / "assets" / "icon.png"
    icon.parent.mkdir()
    icon.write_bytes(b"\x89PNG\r\n\x1a\nlogo")
    escaped = _plugin(tmp_path, "escaped", **extension)
    (escaped / "assets").mkdir()
    try:
        (escaped / "assets" / "icon.png").symlink_to(icon)
    except OSError:
        pass

    assert {plugin.name: plugin.logo for plugin in discover_agent_plugins(tmp_path)} == {
        "demo": "data:image/png;base64,iVBORw0KGgpsb2dv",
        "escaped": None,
    }


def test_plugin_mcp_requires_explicit_enable(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path, "desktop")
    executable = plugin / "bin" / "server"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    _write_json(
        plugin / "mcp.json",
        {
            "$schema": AGENT_PLUGIN_MCP_SCHEMA,
            "mcpServers": {
                "desktop": {
                    "type": "stdio",
                    "command": "./bin/server",
                    "args": ["--data", "${PLUGIN_DATA}/state"],
                    "cwd": "${PLUGIN_ROOT}",
                },
                "public-http": {"type": "streamable-http", "url": "http://example.com/mcp"},
                "escape": {"type": "stdio", "command": "../outside"},
            },
        },
    )

    assert agent_plugin_mcp_servers(tmp_path) == {}
    set_agent_plugin_enabled(tmp_path, "desktop", True)
    server = agent_plugin_mcp_servers(tmp_path)["desktop"]
    assert (server.command, server.cwd, server.env["PLUGIN_ROOT"]) == (
        str(executable),
        str(plugin),
        str(plugin),
    )
    assert server.args[1].endswith("/state")
    set_agent_plugin_enabled(tmp_path, "desktop", False)
    assert agent_plugin_mcp_servers(tmp_path) == {}


def test_plugin_state_symlink_cannot_escape_config_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (config / "plugin-data").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")
    monkeypatch.setattr(agent_plugins, "get_config_path", lambda: config / "config.json")
    _plugin(tmp_path, "desktop")

    with pytest.raises(RuntimeError, match="escapes its parent"):
        set_agent_plugin_enabled(tmp_path, "desktop", True)


def test_plugin_activation_requires_one_stable_package_identity(tmp_path: Path) -> None:
    roots = [tmp_path / "plugins" / directory for directory in ("first", "second")]
    for root, marker in zip(roots, ("trusted", "replacement"), strict=True):
        _write_json(root / "plugin.json", _manifest("duplicate"))
        _write_json(
            root / "mcp.json",
            {
                "$schema": AGENT_PLUGIN_MCP_SCHEMA,
                "mcpServers": {
                    "server": {"type": "stdio", "command": "echo", "args": [marker]}
                },
            },
        )

    assert discover_agent_plugins(tmp_path) == []
    with pytest.raises(ValueError, match="unknown Agent Plugin"):
        set_agent_plugin_enabled(tmp_path, "duplicate", True)

    shutil.rmtree(roots[1])
    set_agent_plugin_enabled(tmp_path, "duplicate", True)
    assert discover_agent_plugins(tmp_path)[0].enabled is True

    moved = tmp_path / "plugins" / "moved"
    roots[0].rename(moved)
    assert discover_agent_plugins(tmp_path)[0].enabled is False
    assert agent_plugin_mcp_servers(tmp_path) == {}
