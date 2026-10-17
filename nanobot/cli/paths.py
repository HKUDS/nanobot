"""Read-only inspection of instance paths and their sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

import typer
from rich.console import Console
from rich.table import Table

from nanobot.cli.runtime_config import (
    _print_config_error,
    _resolve_workspace_override,
)
from nanobot.config.errors import ConfigLoadError
from nanobot.config.home import InstancePaths, get_instance_paths, get_selected_home_path
from nanobot.config.loader import get_selected_config_path, load_config, resolve_env_refs


class InstancePathReport(TypedDict):
    home: str
    config: str
    workspace: str
    sources: dict[str, str]
    paths: dict[str, str]
    legacy: dict[str, str]
    changes: list[str]


def _has_saved_workspace(config_path: Path) -> bool:
    if not config_path.exists():
        return False
    data: object = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return False
    agents = cast(dict[str, object], data).get("agents")
    if not isinstance(agents, dict):
        return False
    defaults = cast(dict[str, object], agents).get("defaults")
    return isinstance(defaults, dict) and "workspace" in defaults


def instance_path_report(config: str | None, workspace: str | None) -> InstancePathReport:
    if config is not None and not config.strip():
        raise typer.BadParameter("must not be empty", param_hint="--config")
    selected_home = get_selected_home_path()
    selected_config = config is not None or get_selected_config_path() is not None
    paths = (
        InstancePaths.resolve(Path(config), home=selected_home)
        if config is not None else get_instance_paths()
    )
    loaded = load_config(paths.config_path, home=paths.home)
    saved_workspace = _has_saved_workspace(paths.config_path)
    configured_workspace = "workspace" in loaded.agents.defaults.model_fields_set
    raw_workspace = resolve_env_refs(loaded.agents.defaults.workspace)
    loaded.agents.defaults.workspace = (
        _resolve_workspace_override(workspace) if workspace is not None else raw_workspace
    )
    effective_workspace = loaded.workspace_path
    legacy_selector_home = selected_home or Path.home() / ".nanobot"
    if workspace is not None:
        legacy_workspace = effective_workspace
    elif configured_workspace:
        legacy_workspace = Path(raw_workspace).expanduser().resolve()
    else:
        legacy_workspace = legacy_selector_home / "workspace"
    legacy = {
        "home": str(paths.config_path.parent),
        "workspace": str(legacy_workspace),
        "cli_history": str(legacy_selector_home / "history" / "cli_history"),
    }
    owned_paths = {
        "auth": str(paths.home / "auth"),
        "sessions": str(paths.home / "sessions"),
        "pairing": str(paths.home / "pairing.json"),
        "media": str(paths.home / "media"),
        "logs": str(paths.home / "logs"),
        "run": str(paths.home / "run"),
        "webui": str(paths.home / "webui"),
        "cli_history": str(paths.home / "history" / "cli_history"),
    }
    current = {
        "home": str(paths.home),
        "workspace": str(effective_workspace),
        "cli_history": owned_paths["cli_history"],
    }
    home_source = "default"
    if selected_home is not None:
        home_source = "--home"
    elif selected_config:
        home_source = "config parent"
    workspace_source = "home/workspace"
    if workspace is not None:
        workspace_source = "--workspace"
    elif saved_workspace:
        workspace_source = "agents.defaults.workspace"
    elif configured_workspace:
        workspace_source = "environment"
    return {
        "home": current["home"],
        "config": str(paths.config_path),
        "workspace": current["workspace"],
        "sources": {
            "home": home_source,
            "config": "--config" if selected_config else "home/config.json",
            "workspace": workspace_source,
        },
        "paths": owned_paths,
        "legacy": legacy,
        "changes": [name for name in current if current[name] != legacy[name]],
    }


def paths(
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Agent workspace directory"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable paths"),
) -> None:
    """Show resolved instance paths without creating files or starting processes."""
    console = Console()
    try:
        report = instance_path_report(config, workspace)
    except ConfigLoadError as exc:
        _print_config_error(exc)
        raise typer.Exit(1) from exc
    except (OSError, ValueError) as exc:
        console.print(str(exc), style="red", markup=False)
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return
    table = Table("Path", "Location", "Source")
    for name in ("home", "config", "workspace"):
        table.add_row(name, report[name], report["sources"][name])
    for name, value in report["paths"].items():
        table.add_row(name, value, "home")
    console.print(table)
    for name in report["changes"]:
        console.print(f"Previous {name}: {report['legacy'][name]}", markup=False)
