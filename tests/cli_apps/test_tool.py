from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

from nanobot.agent.tools.cli_apps import CliAppsTool
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
    CliAppManager(workspace=workspace, data_dir=data_dir)._save_installed(
        {"gimp": {"entry_point": "cli-anything-gimp"}}
    )
    resolved = str(tmp_path / "bin" / "cli-anything-gimp")
    monkeypatch.setattr(
        "nanobot.apps.cli.service.shutil.which",
        lambda entry: resolved if entry == "cli-anything-gimp" else None,
    )

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert "shell" not in kwargs or kwargs["shell"] is False
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="tool:" + " ".join(argv[1:]),
            stderr="",
        )

    monkeypatch.setattr("nanobot.apps.cli.service.subprocess.run", fake_run)
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
