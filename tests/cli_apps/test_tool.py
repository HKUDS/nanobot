from __future__ import annotations

import asyncio
import json
import os
import stat
import time
from pathlib import Path

from nanobot.agent.tools.cli_apps import CliAppsTool
from nanobot.cli_apps.service import CliAppManager, CliAppsRuntimeConfig


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
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cli = bin_dir / "cli-anything-gimp"
    cli.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('tool:' + ' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr("nanobot.cli_apps.service.get_runtime_subdir", lambda _name: data_dir)

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
    monkeypatch.setattr("nanobot.cli_apps.service.get_runtime_subdir", lambda _name: data_dir)
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
    monkeypatch.setattr("nanobot.cli_apps.service.get_runtime_subdir", lambda _name: data_dir)

    tool = CliAppsTool(workspace=workspace)

    assert "Settings CLI Apps: drawio" in tool.description
    assert "ordinary system CLIs such as git, gh" in tool.description
