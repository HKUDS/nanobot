"""Helpers for discovering switchable runtime instances from config files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nanobot.config.loader import get_config_path


@dataclass(frozen=True)
class RuntimeInstance:
    """A runtime instance discovered from a config file."""

    name: str
    config_path: Path
    aliases: tuple[str, ...]


def instance_name_from_path(config_path: Path) -> str:
    """Return a friendly instance name inferred from the config location."""
    parent_name = config_path.parent.name
    if parent_name == ".nanobot":
        return "default"
    prefix = ".nanobot-"
    if parent_name.startswith(prefix) and len(parent_name) > len(prefix):
        return parent_name[len(prefix):]
    stem = config_path.stem.strip()
    if stem and stem != "config":
        return stem
    cleaned = parent_name.lstrip(".").strip()
    return cleaned or "default"


def _build_aliases(name: str, config_path: Path) -> tuple[str, ...]:
    """Return exact-match aliases accepted for an instance switch command."""
    aliases: list[str] = []

    def _add(value: str) -> None:
        value = value.strip()
        if value and value not in aliases:
            aliases.append(value)

    parent_name = config_path.parent.name
    _add(name)
    _add(parent_name)
    _add(parent_name.lstrip("."))
    if parent_name.startswith(".nanobot-"):
        _add(parent_name[len(".nanobot-"):])
    if parent_name == ".nanobot":
        _add("nanobot")
    stem = config_path.stem.strip()
    if stem and stem != "config":
        _add(stem)
    return tuple(aliases)


def discover_runtime_instances() -> list[RuntimeInstance]:
    """Discover runtime instances from nanobot config directories."""
    current = get_config_path().expanduser().resolve(strict=False)
    candidate_paths: set[Path] = {current}

    try:
        for path in Path.home().glob(".nanobot*/config.json"):
            candidate_paths.add(path.expanduser().resolve(strict=False))
    except Exception:
        pass

    rows: list[RuntimeInstance] = []
    used_names: set[str] = set()
    for config_path in sorted(candidate_paths, key=lambda item: str(item)):
        if not config_path.exists():
            continue
        name = instance_name_from_path(config_path)
        lowered = name.lower()
        if lowered in used_names:
            fallback = config_path.parent.name.lstrip(".") or name
            name = fallback
            lowered = name.lower()
        used_names.add(lowered)
        rows.append(
            RuntimeInstance(
                name=name,
                config_path=config_path,
                aliases=_build_aliases(name, config_path),
            )
        )
    return rows


def find_runtime_instance(name: str) -> RuntimeInstance | None:
    """Find a discovered instance by exact, case-insensitive alias match."""
    wanted = name.strip().lower()
    if not wanted:
        return None
    for instance in discover_runtime_instances():
        if any(alias.lower() == wanted for alias in instance.aliases):
            return instance
    return None
