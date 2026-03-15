"""Configuration loading utilities."""

import json
import re
from pathlib import Path

from nanobot.config.schema import Config


# Global variable to store current config path (for multi-instance support)
_current_config_path: Path | None = None


def set_config_path(path: Path) -> None:
    """Set the current config path (used to derive data directory)."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the configuration file path."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".nanobot" / "config.json"


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
            # Normalise camelCase keys to snake_case so that init-kwargs and
            # env_settings both use the same key format.  Without this,
            # {"apiKey": "file-val"} and the env var producing {"api_key": "env-val"}
            # end up as two separate keys in the deep-merged dict; Pydantic then
            # resolves the alias (camelCase) over the field name, making env vars lose.
            return Config(**_normalize_keys(data))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")

    return Config()


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


def _camel_to_snake(name: str) -> str:
    """Convert a single camelCase (or PascalCase) identifier to snake_case."""
    # Insert underscore between a lowercase/digit and an uppercase letter
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def _normalize_keys(data: dict) -> dict:
    """Recursively convert all dict keys from camelCase to snake_case.

    Config JSON files use camelCase aliases (e.g. ``apiKey``), while
    pydantic-settings' env var source uses snake_case field names
    (e.g. ``api_key`` from ``NANOBOT_PROVIDERS__ANTHROPIC__API_KEY``).
    Normalising both to snake_case lets pydantic-settings merge the two
    sources correctly so that environment variables can override file values.
    """
    result = {}
    for k, v in data.items():
        result[_camel_to_snake(k)] = _normalize_keys(v) if isinstance(v, dict) else v
    return result


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data

