import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.cli_apps import CliAppsTool
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool
from nanobot.agent.tools.image_generation import ImageGenerationError, ImageGenerationTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.search import GrepTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.apps.cli.service import CliAppManager, CliAppsRuntimeConfig
from nanobot.config.schema import ImageGenerationToolConfig, ProviderConfig, ToolsConfig
from nanobot.security.workspace_access import (
    WORKSPACE_SCOPE_METADATA_KEY,
    WorkspaceScopeError,
    bind_workspace_scope,
    default_workspace_scope,
    reset_workspace_scope,
    validate_workspace_scope_payload,
    workspace_scope_from_metadata,
)

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdacd\xfc\xff\x1f\x00\x03\x03"
    b"\x02\x00\xef\xbf\xa7\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_workspace_scope_defaults_match_legacy_config(tmp_path: Path) -> None:
    unrestricted = default_workspace_scope(tmp_path, restrict_to_workspace=False)
    restricted = default_workspace_scope(tmp_path, restrict_to_workspace=True)

    assert unrestricted.project_path == tmp_path.resolve()
    assert unrestricted.access_mode == "full"
    assert unrestricted.restrict_to_workspace is False
    assert restricted.access_mode == "restricted"
    assert restricted.restrict_to_workspace is True


def test_workspace_scope_rejects_invalid_project_path(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceScopeError, match="absolute"):
        validate_workspace_scope_payload(
            {"project_path": "relative/project", "access_mode": "restricted"},
            default_workspace=tmp_path,
            default_restrict_to_workspace=False,
        )

    with pytest.raises(WorkspaceScopeError, match="existing directory"):
        validate_workspace_scope_payload(
            {"project_path": str(tmp_path / "missing"), "access_mode": "restricted"},
            default_workspace=tmp_path,
            default_restrict_to_workspace=False,
        )


def test_workspace_scope_accepts_home_relative_project_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = home / "Desktop" / "Photos"
    project.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    scope = validate_workspace_scope_payload(
        {"project_path": "~/Desktop/Photos", "access_mode": "restricted"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=False,
    )

    assert scope.project_path == project.resolve()
    assert scope.metadata()["project_path"] == str(project.resolve())


def test_workspace_scope_metadata_falls_back_for_stale_session(tmp_path: Path) -> None:
    scope = workspace_scope_from_metadata(
        {
            WORKSPACE_SCOPE_METADATA_KEY: {
                "project_path": str(tmp_path / "missing"),
                "access_mode": "restricted",
            }
        },
        default_workspace=tmp_path,
        default_restrict_to_workspace=False,
    )

    assert scope.project_path == tmp_path.resolve()
    assert scope.access_mode == "full"


@pytest.mark.asyncio
async def test_filesystem_tool_uses_current_restricted_workspace_scope(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope")
    inside = project / "inside.txt"
    inside.write_text("ok")
    tool = ReadFileTool(workspace=tmp_path, restrict_to_workspace=False)
    scope = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "restricted"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=False,
    )
    token = bind_workspace_scope(scope)
    try:
        assert "ok" in await tool.execute(path="inside.txt")
        assert "outside allowed directory" in await tool.execute(path=str(outside))
    finally:
        reset_workspace_scope(token)


@pytest.mark.asyncio
async def test_restricted_project_can_read_agent_skills_and_exact_history(tmp_path: Path) -> None:
    agent_workspace = tmp_path / "agent"
    project = tmp_path / "project"
    skill_file = agent_workspace / "skills" / "custom" / "SKILL.md"
    history_file = agent_workspace / "memory" / "history.jsonl"
    private_memory_file = agent_workspace / "memory" / "private.txt"
    private_file = agent_workspace / "private.txt"
    project_file = project / "project.txt"
    skill_file.parent.mkdir(parents=True)
    history_file.parent.mkdir(parents=True)
    project.mkdir()
    skill_file.write_text("global skill", encoding="utf-8")
    history_file.write_text('{"content":"global history"}\n', encoding="utf-8")
    private_memory_file.write_text("private memory", encoding="utf-8")
    private_file.write_text("private", encoding="utf-8")
    project_file.write_text("project", encoding="utf-8")

    ctx = ToolContext(
        config=ToolsConfig(restrict_to_workspace=True),
        workspace=str(agent_workspace),
    )
    read_tool = ReadFileTool.create(ctx)
    grep_tool = GrepTool.create(ctx)
    write_tool = WriteFileTool.create(ctx)
    scope = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "restricted"},
        default_workspace=agent_workspace,
        default_restrict_to_workspace=True,
    )

    token = bind_workspace_scope(scope)
    try:
        project_result = await read_tool.execute(path="project.txt")
        skill_result = await read_tool.execute(path=str(skill_file))
        history_result = await grep_tool.execute(
            pattern="global history",
            path=str(history_file),
            output_mode="content",
        )
        private_memory_result = await read_tool.execute(path=str(private_memory_file))
        private_result = await read_tool.execute(path=str(private_file))
        write_result = await write_tool.execute(path=str(skill_file), content="changed")
        history_write_result = await write_tool.execute(path=str(history_file), content="changed")
    finally:
        reset_workspace_scope(token)

    assert "project" in project_result
    assert "global skill" in skill_result
    assert "global history" in history_result
    assert "outside allowed directory" in private_memory_result
    assert "outside allowed directory" in private_result
    assert "outside allowed directory" in write_result
    assert "outside allowed directory" in history_write_result
    assert skill_file.read_text(encoding="utf-8") == "global skill"
    assert history_file.read_text(encoding="utf-8") == '{"content":"global history"}\n'


@pytest.mark.asyncio
async def test_agent_skill_write_requires_full_project_scope(tmp_path: Path) -> None:
    agent_workspace = tmp_path / "agent"
    project = tmp_path / "project"
    skill_file = agent_workspace / "skills" / "custom" / "SKILL.md"
    agent_workspace.mkdir()
    project.mkdir()
    tool = WriteFileTool.create(
        ToolContext(
            config=ToolsConfig(restrict_to_workspace=False),
            workspace=str(agent_workspace),
        )
    )
    content = "---\nname: custom\ndescription: custom skill\n---\n"

    restricted = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "restricted"},
        default_workspace=agent_workspace,
        default_restrict_to_workspace=False,
    )
    token = bind_workspace_scope(restricted)
    try:
        denied = await tool.execute(path=str(skill_file), content=content)
    finally:
        reset_workspace_scope(token)

    assert "outside allowed directory" in denied
    assert not skill_file.exists()

    full = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "full"},
        default_workspace=agent_workspace,
        default_restrict_to_workspace=False,
    )
    token = bind_workspace_scope(full)
    try:
        written = await tool.execute(path=str(skill_file), content=content)
    finally:
        reset_workspace_scope(token)

    assert "Successfully wrote" in written
    assert "custom" in {
        entry["name"] for entry in SkillsLoader(agent_workspace).list_skills(False)
    }


@pytest.mark.asyncio
async def test_filesystem_write_tool_full_scope_allows_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    tool = WriteFileTool(workspace=tmp_path, allowed_dir=tmp_path, restrict_to_workspace=True)
    scope = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "full"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=True,
    )
    token = bind_workspace_scope(scope)
    try:
        result = await tool.execute(path=str(outside / "outside.txt"), content="ok")
    finally:
        reset_workspace_scope(token)

    assert "Successfully wrote" in result
    assert (outside / "outside.txt").read_text(encoding="utf-8") == "ok"


@pytest.mark.asyncio
async def test_exec_tool_uses_scope_project_as_default_cwd(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    tool = ExecTool(working_dir=str(tmp_path), restrict_to_workspace=False, timeout=5)
    scope = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "restricted"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=False,
    )
    token = bind_workspace_scope(scope)
    try:
        result = await tool.execute(
            command=(
                'python -c "from pathlib import Path; '
                "Path('scoped-marker.txt').write_text('ok')\""
            )
        )
    finally:
        reset_workspace_scope(token)

    assert "Exit code: 0" in result
    assert (project / "scoped-marker.txt").read_text() == "ok"


@pytest.mark.asyncio
async def test_exec_full_scope_allows_explicit_cwd_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    tool = ExecTool(working_dir=str(tmp_path), restrict_to_workspace=True, timeout=5)
    scope = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "full"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=True,
    )
    token = bind_workspace_scope(scope)
    try:
        result = await tool.execute(
            command=(
                'python -c "from pathlib import Path; '
                "Path('outside-marker.txt').write_text('ok')\""
            ),
            working_dir=str(outside),
        )
    finally:
        reset_workspace_scope(token)

    assert "Exit code: 0" in result
    assert (outside / "outside-marker.txt").read_text() == "ok"


def test_image_reference_scope_restricted_blocks_outside_and_full_allows(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    ref = outside / "ref.png"
    ref.write_bytes(PNG_BYTES)
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(enabled=True),
        provider_config=ProviderConfig(api_key="sk-test"),
    )

    restricted = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "restricted"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=False,
    )
    token = bind_workspace_scope(restricted)
    try:
        with pytest.raises(ImageGenerationError, match="inside the workspace"):
            tool._resolve_reference_image(str(ref))
    finally:
        reset_workspace_scope(token)

    full = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "full"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=True,
    )
    token = bind_workspace_scope(full)
    try:
        assert tool._resolve_reference_image(str(ref)) == str(ref.resolve())
    finally:
        reset_workspace_scope(token)


def test_message_media_scope_restricted_blocks_outside_and_full_allows(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    media = outside / "shot.png"
    media.write_bytes(PNG_BYTES)
    tool = MessageTool(workspace=tmp_path, restrict_to_workspace=True)

    restricted = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "restricted"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=False,
    )
    token = bind_workspace_scope(restricted)
    try:
        with pytest.raises(PermissionError):
            tool._resolve_media([str(media)])
    finally:
        reset_workspace_scope(token)

    full = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "full"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=True,
    )
    token = bind_workspace_scope(full)
    try:
        assert tool._resolve_media([str(media)]) == [str(media)]
    finally:
        reset_workspace_scope(token)


@pytest.mark.asyncio
async def test_cli_app_scope_controls_working_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    data_dir = tmp_path / "data"
    project.mkdir()
    outside.mkdir()
    registry = {
        "meta": {},
        "clis": [
            {
                "name": "demo",
                "display_name": "Demo",
                "version": "1.0",
                "description": "demo",
                "category": "test",
                "install_cmd": "pip install demo",
                "entry_point": "demo-cli",
            }
        ],
    }
    data_dir.mkdir()
    (data_dir / "harness_registry_cache.json").write_text(
        json.dumps({"_cached_at": time.time(), "data": registry}),
        encoding="utf-8",
    )
    (data_dir / "public_registry_cache.json").write_text(
        json.dumps({"_cached_at": time.time(), "data": {"meta": {}, "clis": []}}),
        encoding="utf-8",
    )
    (data_dir / "extensions_registry_cache.json").write_text(
        json.dumps({"_cached_at": time.time(), "data": {"meta": {}, "clis": []}}),
        encoding="utf-8",
    )
    CliAppManager(workspace=project, data_dir=data_dir)._save_installed(
        {"demo": {"entry_point": "demo-cli"}}
    )
    monkeypatch.setattr("nanobot.apps.cli.service.get_runtime_subdir", lambda _name: data_dir)
    monkeypatch.setattr(
        "nanobot.apps.cli.service.shutil.which",
        lambda entry: "/usr/bin/demo-cli" if entry == "demo-cli" else None,
    )

    seen: dict[str, str] = {}

    def fake_run(argv, **kwargs):
        seen["cwd"] = kwargs["cwd"]
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("nanobot.apps.cli.service.subprocess.run", fake_run)
    tool = CliAppsTool(
        workspace=tmp_path,
        restrict_to_workspace=True,
        runtime=CliAppsRuntimeConfig(run_timeout=5),
    )

    restricted = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "restricted"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=False,
    )
    token = bind_workspace_scope(restricted)
    try:
        blocked = await tool.execute(name="demo", working_dir=str(outside))
    finally:
        reset_workspace_scope(token)
    assert "outside the configured workspace" in blocked

    full = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "full"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=True,
    )
    token = bind_workspace_scope(full)
    try:
        result = await tool.execute(name="demo", working_dir=str(outside))
    finally:
        reset_workspace_scope(token)
    assert "CLI app 'demo' exited 0" in result
    assert seen["cwd"] == str(outside.resolve())


@pytest.mark.asyncio
async def test_spawn_tool_forwards_current_workspace_scope(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    scope = validate_workspace_scope_payload(
        {"project_path": str(project), "access_mode": "restricted"},
        default_workspace=tmp_path,
        default_restrict_to_workspace=False,
    )

    class Manager:
        max_concurrent_subagents = 4

        def __init__(self) -> None:
            self.seen = None

        def get_running_count(self) -> int:
            return 0

        async def spawn(self, **kwargs):
            self.seen = kwargs
            return "spawned"

    manager = Manager()
    tool = SpawnTool(manager)  # type: ignore[arg-type]
    token = bind_workspace_scope(scope)
    try:
        with request_context(RequestContext(
            channel="test",
            chat_id="chat",
            runtime=MagicMock(),
        )):
            result = await tool.execute(task="inspect")
    finally:
        reset_workspace_scope(token)

    assert result == "spawned"
    assert manager.seen["workspace_scope"] == scope
