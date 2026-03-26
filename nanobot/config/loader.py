"""Configuration loading utilities."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from nanobot.config.schema import Config


def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".nanobot" / "config.json"


def get_data_dir() -> Path:
    """Get the nanobot data directory."""
    from nanobot.utils.paths import get_data_path

    return get_data_path()


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from file or create default.

    The config file must conform to the current schema. No migration or
    rewriting is performed — invalid configs abort startup with a clear
    error message instead of silently falling back to defaults.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
            sys.exit(1)
        try:
            return Config.model_validate(data)
        except ValueError as e:
            print(f"Error: config validation failed for {path}:\n{e}", file=sys.stderr)
            sys.exit(1)

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """Save configuration to file."""
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.chmod(path, 0o600)
