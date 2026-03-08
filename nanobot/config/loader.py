"""Configuration loading utilities."""

import json
import os
from pathlib import Path
from typing import Any

from nanobot.config.schema import Config
from nanobot.utils.helpers import ensure_dir


def _apply_env_overrides(config: Config) -> Config:
    root = os.environ.get("NANOBOT_ROOT", "").strip()
    if root:
        config.paths.root = root
    return config


def get_config_path() -> Path:
    """Get config path from env override or default root."""
    explicit = os.environ.get("NANOBOT_CONFIG", "").strip()
    if explicit:
        return Path(explicit).expanduser()

    root = os.environ.get("NANOBOT_ROOT", "").strip()
    root_path = Path(root).expanduser() if root else Path.home() / ".nanobot"
    return root_path / "config.json"


def get_data_dir(config: Config | None = None, config_path: Path | None = None) -> Path:
    """Get the nanobot instance data directory."""
    loaded = config or load_config(config_path=config_path)
    return ensure_dir(loaded.root_path)


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            config = _apply_env_overrides(Config.model_validate(data))
            os.environ["NANOBOT_ROOT"] = str(config.root_path)
            return config
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")

    config = _apply_env_overrides(Config())
    os.environ["NANOBOT_ROOT"] = str(config.root_path)
    return config


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data
