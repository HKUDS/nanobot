"""Configuration module for nanobot."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.config.errors import ConfigIssue, ConfigLoadError
    from nanobot.config.loader import get_config_path, load_config
    from nanobot.config.paths import (
        get_cli_history_path,
        get_cron_dir,
        get_data_dir,
        get_legacy_sessions_dir,
        get_logs_dir,
        get_media_dir,
        get_runtime_subdir,
        get_webui_dir,
        get_workspace_path,
        is_default_workspace,
    )
    from nanobot.config.schema import Config


_EXPORTS = {
    "Config": "nanobot.config.schema",
    "ConfigIssue": "nanobot.config.errors",
    "ConfigLoadError": "nanobot.config.errors",
    "load_config": "nanobot.config.loader",
    "get_config_path": "nanobot.config.loader",
    "get_data_dir": "nanobot.config.paths",
    "get_runtime_subdir": "nanobot.config.paths",
    "get_media_dir": "nanobot.config.paths",
    "get_cron_dir": "nanobot.config.paths",
    "get_logs_dir": "nanobot.config.paths",
    "get_webui_dir": "nanobot.config.paths",
    "get_workspace_path": "nanobot.config.paths",
    "is_default_workspace": "nanobot.config.paths",
    "get_cli_history_path": "nanobot.config.paths",
    "get_legacy_sessions_dir": "nanobot.config.paths",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = [
    "Config",
    "ConfigIssue",
    "ConfigLoadError",
    "load_config",
    "get_config_path",
    "get_data_dir",
    "get_runtime_subdir",
    "get_media_dir",
    "get_cron_dir",
    "get_logs_dir",
    "get_webui_dir",
    "get_workspace_path",
    "is_default_workspace",
    "get_cli_history_path",
    "get_legacy_sessions_dir",
]
