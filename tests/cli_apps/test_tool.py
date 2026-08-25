from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from nanobot.agent.tools import cli_apps as cli_apps_tool
from nanobot.agent.tools.cli_apps import CliAppsTool
from nanobot.agent.tools.context import RequestContext
from nanobot.apps.cli.service import CliAppManager, CliAppsRuntimeConfig


def _write_cache(path: Path, registry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"_cached_at": time.time(), "data": registry}),
        encoding="utf-8",
    )


def test_run_cli_app_uses_installed_registry_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    registry = {
        "meta": {"updated": "2026-04-16"},
        "clis": [
            {
                "name": "gimp",
                "display_name": "GIMP",
                "version": "1.0.0",
                "description": "Image editing",
                "category": "image",
                "install_cmd": "pip install cli-anything-gimp",
                "entry_point": "cli-anything-gimp",
            }
        ],
    }
    _write_cache(data_dir / "harness_registry_cache.json", registry)
    _write_cache(data_dir / "public_registry_cache.json", {"meta": {}, "clis": []})
    _write_cache(data_dir / "extensions_registry_cache.json", {"meta": {}, "clis": []})
    CliAppManager(workspace=workspace, data_dir=data_dir)._save_installed(
        {"gimp": {"entry_point": "cli-anything-gimp"}}
    )
    resolved = str(tmp_path / "bin" / "cli-anything-gimp")
    monkeypatch.setattr(
        "nanobot.apps.cli.service.shutil.which",
        lambda entry: resolved if entry == "cli-anything-gimp" else None,
    )

    class _Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"tool:--json project list", b""

    async def fake_create_subprocess_exec(*argv: str, **kwargs: object) -> _Process:
        assert argv == (resolved, "--json", "project", "list")
        assert "shell" not in kwargs
        return _Process()

    monkeypatch.setattr(
        "nanobot.apps.cli.service.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr("nanobot.apps.cli.service._WindowsJob.create", lambda: None)
    monkeypatch.setattr("nanobot.apps.cli.service.get_runtime_subdir", lambda _name: data_dir)

    tool = CliAppsTool(
        workspace=workspace,
        restrict_to_workspace=True,
        runtime=CliAppsRuntimeConfig(run_timeout=5),
    )
    assert tool.name == "run_cli_app"

    result = asyncio.run(
        tool.execute(
            name="gimp",
            args=["project", "list"],
            json=True,
            working_dir=str(workspace),
        )
    )

    assert "CLI app 'gimp' exited 0" in result
    assert "tool:--json project list" in result


def test_run_cli_app_rejects_uninstalled_app(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    registry = {
        "meta": {"updated": "2026-04-16"},
        "clis": [
            {
                "name": "gimp",
                "display_name": "GIMP",
                "version": "1.0.0",
                "description": "Image editing",
                "category": "image",
                "install_cmd": "pip install cli-anything-gimp",
                "entry_point": "cli-anything-gimp",
            }
        ],
    }
    _write_cache(data_dir / "harness_registry_cache.json", registry)
    _write_cache(data_dir / "public_registry_cache.json", {"meta": {}, "clis": []})
    _write_cache(data_dir / "extensions_registry_cache.json", {"meta": {}, "clis": []})
    monkeypatch.setattr("nanobot.apps.cli.service.get_runtime_subdir", lambda _name: data_dir)
    tool = CliAppsTool(workspace=workspace, restrict_to_workspace=True)

    result = asyncio.run(tool.execute(name="gimp"))

    assert "not installed" in result


def test_run_cli_app_description_names_only_settings_installed_apps(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    CliAppManager(workspace=workspace, data_dir=data_dir)._save_installed(
        {"drawio": {"entry_point": "cli-anything-drawio"}}
    )
    monkeypatch.setattr("nanobot.apps.cli.service.get_runtime_subdir", lambda _name: data_dir)

    tool = CliAppsTool(workspace=workspace)

    assert "Settings CLI Apps: drawio" in tool.description
    assert "ordinary system CLIs such as git, gh" in tool.description


def test_cli_app_tool_provides_context_only_for_attachment(tmp_path: Path) -> None:
    tool = CliAppsTool(workspace=tmp_path)
    provider = tool.runtime_context_provider()
    assert provider is not None

    empty = asyncio.run(provider(RequestContext(
        channel="websocket",
        chat_id="chat",
        original_user_text="hello",
        workspace=tmp_path,
    )))
    attached = asyncio.run(provider(RequestContext(
        channel="websocket",
        chat_id="chat",
        original_user_text="use @drawio",
        metadata={
            "cli_apps": [{
                "name": "drawio",
                "entry_point": "cli-anything-drawio",
            }],
        },
        workspace=tmp_path,
    )))

    assert empty is None
    assert attached is not None
    assert attached.source == "cli_apps"
    assert "CLI App Attachment: @drawio" in attached.content


@pytest.mark.asyncio
async def test_run_cli_app_uses_threaded_sync_fallback_for_compatible_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_loop_thread = threading.get_ident()
    seen: dict[str, object] = {}

    class CompatibleManager:
        def __init__(
            self,
            *,
            workspace: Path,
            runtime: CliAppsRuntimeConfig,
        ) -> None:
            seen["workspace"] = workspace
            seen["runtime"] = runtime

        def run_async(self, *_args: object, **_kwargs: object) -> str:
            raise AssertionError("a synchronous compatibility method must not be awaited")

        def run(self, name: str, **kwargs: object) -> str:
            seen["thread"] = threading.get_ident()
            seen["name"] = name
            seen["kwargs"] = kwargs
            return "compatible result"

    monkeypatch.setattr(cli_apps_tool, "CliAppManager", CompatibleManager)
    runtime = CliAppsRuntimeConfig(run_timeout=7)
    tool = CliAppsTool(workspace=tmp_path, restrict_to_workspace=True, runtime=runtime)

    result = await tool.execute(
        name="demo",
        args=["show"],
        json=True,
        working_dir=str(tmp_path),
        timeout=3,
    )

    assert result == "compatible result"
    assert seen["workspace"] == tmp_path
    assert seen["runtime"] is runtime
    assert seen["thread"] != event_loop_thread
    assert seen["name"] == "demo"
    assert seen["kwargs"] == {
        "args": ["show"],
        "json_output": True,
        "working_dir": str(tmp_path),
        "timeout": 3,
        "restrict_to_workspace": True,
    }


@pytest.mark.asyncio
async def test_run_cli_app_preserves_native_manager_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fake_run_async(self: CliAppManager, name: str, **_kwargs: object) -> str:
        assert name == "demo"
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("unreachable")

    def fail_sync_run(self: CliAppManager, name: str, **_kwargs: object) -> str:
        raise AssertionError(f"native async manager fell back to run({name!r})")

    monkeypatch.setattr(CliAppManager, "run_async", fake_run_async)
    monkeypatch.setattr(CliAppManager, "run", fail_sync_run)
    tool = CliAppsTool(workspace=tmp_path)

    task = asyncio.create_task(tool.execute(name="demo"))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
