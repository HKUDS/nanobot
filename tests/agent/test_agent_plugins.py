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
    enabled_agent_plugin_skill_dirs,
    enabled_agent_plugin_skills,
    set_agent_plugin_enabled,
)
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool
from nanobot.config.schema import ToolsConfig
from nanobot.security.workspace_access import (
    bind_workspace_scope,
    reset_workspace_scope,
    validate_workspace_scope_payload,
)


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


def test_plugin_mcp_namespaces_cannot_shadow_plugin_identities(tmp_path: Path) -> None:
    single = _plugin(tmp_path, "foo-bar")
    multi = _plugin(tmp_path, "foo")
    for root, servers in (
        (single, {"main": {"type": "stdio", "command": "echo", "args": ["single"]}}),
        (
            multi,
            {
                "bar": {"type": "stdio", "command": "echo", "args": ["multi"]},
                "other": {"type": "stdio", "command": "echo"},
            },
        ),
    ):
        _write_json(
            root / "mcp.json",
            {"$schema": AGENT_PLUGIN_MCP_SCHEMA, "mcpServers": servers},
        )
    set_agent_plugin_enabled(tmp_path, "foo-bar", True)
    set_agent_plugin_enabled(tmp_path, "foo", True)

    servers = agent_plugin_mcp_servers(tmp_path)

    assert set(servers) == {"foo-bar", "foo--bar", "foo--other"}
    assert servers["foo-bar"].args == ["single"]
    assert servers["foo--bar"].args == ["multi"]


@pytest.mark.asyncio
async def test_restricted_project_can_read_only_enabled_plugin_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_workspace = tmp_path / "agent"
    project = tmp_path / "project"
    project.mkdir()
    plugin = _plugin(agent_workspace)
    skill = _skill(plugin / "skills", "demo-skill")
    resource = skill / "reference.md"
    resource.write_text("plugin reference", encoding="utf-8")
    ctx = ToolContext(
        config=ToolsConfig(restrict_to_workspace=True),
        workspace=str(agent_workspace),
    )
    read_tool = ReadFileTool.create(ctx)
    write_tool = WriteFileTool.create(ctx)
    set_agent_plugin_enabled(agent_workspace, "demo", True)
    activation_checks = 0
    activation_marker = agent_plugins._activation_marker

    def count_activation_checks(plugin: agent_plugins.AgentPlugin) -> str | None:
        nonlocal activation_checks
        activation_checks += 1
        return activation_marker(plugin)

    monkeypatch.setattr(agent_plugins, "_activation_marker", count_activation_checks)
    scope = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "restricted"},
        default_workspace=agent_workspace,
        default_restrict_to_workspace=True,
    )

    token = bind_workspace_scope(scope)
    try:
        read_result = await read_tool.execute(path=str(resource))
        repeated_read_result = await read_tool.execute(path=str(resource))
        write_result = await write_tool.execute(path=str(resource), content="changed")
        set_agent_plugin_enabled(agent_workspace, "demo", False)
        disabled_result = await read_tool.execute(path=str(resource))
    finally:
        reset_workspace_scope(token)

    assert "plugin reference" in read_result
    assert "File unchanged since last read" in repeated_read_result
    assert activation_checks == 1
    assert "outside allowed directory" in write_result
    assert "outside allowed directory" in disabled_result
    assert resource.read_text(encoding="utf-8") == "plugin reference"


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


def test_legacy_path_activation_is_upgraded_to_package_fingerprint(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path)
    set_agent_plugin_enabled(tmp_path, "demo", True)
    marker = next((tmp_path / "config" / "plugin-data").glob("*/demo/enabled"))
    marker.write_text(str(plugin), encoding="utf-8")

    assert discover_agent_plugins(tmp_path)[0].enabled is True
    assert marker.read_text(encoding="utf-8").startswith('{"fingerprint":')


def test_plugin_activation_does_not_survive_in_place_contract_replacement(
    tmp_path: Path,
) -> None:
    plugin = _plugin(tmp_path, "desktop")
    mcp = plugin / "mcp.json"

    def write_server(marker: str) -> None:
        _write_json(
            mcp,
            {
                "$schema": AGENT_PLUGIN_MCP_SCHEMA,
                "mcpServers": {
                    "server": {"type": "stdio", "command": "echo", "args": [marker]}
                },
            },
        )

    write_server("trusted")
    set_agent_plugin_enabled(tmp_path, "desktop", True)
    assert agent_plugin_mcp_servers(tmp_path)["desktop"].args == ["trusted"]

    write_server("replacement")

    assert discover_agent_plugins(tmp_path)[0].enabled is False
    assert agent_plugin_mcp_servers(tmp_path) == {}


def test_plugin_activation_does_not_survive_in_place_code_replacement(
    tmp_path: Path,
) -> None:
    plugin = _plugin(tmp_path, "desktop")
    _skill(plugin / "skills", "demo")
    executable = plugin / "server.py"
    executable.write_text("print('trusted')\n", encoding="utf-8")
    _write_json(
        plugin / "mcp.json",
        {
            "$schema": AGENT_PLUGIN_MCP_SCHEMA,
            "mcpServers": {
                "server": {
                    "type": "stdio",
                    "command": "python",
                    "args": ["${PLUGIN_ROOT}/server.py"],
                }
            },
        },
    )
    set_agent_plugin_enabled(tmp_path, "desktop", True)
    assert discover_agent_plugins(tmp_path)[0].enabled is True
    assert enabled_agent_plugin_skill_dirs(tmp_path) == (plugin / "skills" / "demo",)

    executable.write_text("print('replacement')\n", encoding="utf-8")

    assert discover_agent_plugins(tmp_path)[0].enabled is False
    assert enabled_agent_plugin_skill_dirs(tmp_path) == ()
    assert agent_plugin_mcp_servers(tmp_path) == {}
