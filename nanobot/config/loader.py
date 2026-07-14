"""Configuration loading and persistence entry points."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from nanobot.config.repository import (
    ConfigCommit,
    FileConfigRepository,
)
from nanobot.config.schema import Config

# Default path for process entry points that do not receive an explicit path.
_current_config_path: Path | None = None


def set_config_path(path: Path) -> None:
    """Set the default configuration path for subsequent entry-point calls."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the default configuration file path."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".nanobot" / "config.json"


def get_config_repository(config_path: Path | None = None) -> FileConfigRepository:
    """Return an instance-scoped repository for *config_path*."""
    return FileConfigRepository(config_path or get_config_path())


def load_raw_config(config_path: Path | None = None) -> Config:
    """Load raw persisted config without applying process runtime policy."""
    return get_config_repository(config_path).load_raw().config


def load_effective_config(config_path: Path | None = None) -> Config:
    """Load a fresh runtime config with environment references resolved."""
    return get_config_repository(config_path).load_effective().config


def save_config(config: Config, config_path: Path | None = None) -> None:
    """Atomically save a complete config.

    New read-modify-write flows should use :func:`update_config` so concurrent
    writers for the same file cannot silently overwrite one another.
    """
    get_config_repository(config_path).save(config)


def update_config(
    mutator: Callable[[Config], None],
    config_path: Path | None = None,
    *,
    expected_revision: str | None = None,
) -> ConfigCommit:
    """Atomically mutate the latest raw config and return the resulting commit."""
    return get_config_repository(config_path).update(
        mutator,
        expected_revision=expected_revision,
    )


def apply_config_runtime_policies(config: Config) -> None:
    """Apply process-level policies when starting or reconfiguring a runtime."""
    from nanobot.security.network import configure_ssrf_whitelist

    configure_ssrf_whitelist(config.tools.ssrf_whitelist)


def merge_missing_defaults(existing: Any, defaults: Any) -> Any:
    """Recursively add missing defaults without replacing configured values."""
    if not isinstance(existing, dict) or not isinstance(defaults, dict):
        return existing

    merged = dict(existing)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
        else:
            merged[key] = merge_missing_defaults(merged[key], value)
    return merged


__all__ = [
    "apply_config_runtime_policies",
    "get_config_path",
    "get_config_repository",
    "load_raw_config",
    "load_effective_config",
    "merge_missing_defaults",
    "save_config",
    "set_config_path",
    "update_config",
]
