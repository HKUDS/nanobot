"""Configuration loading utilities."""

import json
from pathlib import Path
from typing import Any

from nanobot.config.schema import Config


def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".nanobot" / "config.json"


def get_data_dir() -> Path:
    """Get the nanobot data directory."""
    from nanobot.utils.helpers import get_data_path
    return get_data_path()


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
            with open(path) as f:
                data = json.load(f)
            data = _migrate_config(data)
            return Config.model_validate(convert_keys(data))
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
    
    # Convert to camelCase format
    data = config.model_dump()
    data = convert_to_camel(data)
    
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data


# Keys whose dict values should NOT have their sub-keys transformed.
# These hold user-defined mappings (e.g. HTTP header names) that must be
# preserved verbatim.
_PRESERVE_VALUE_KEYS = frozenset({"extraHeaders", "extra_headers"})


def convert_keys(data: Any) -> Any:
    """Convert camelCase keys to snake_case for Pydantic.
    
    Keys listed in _PRESERVE_VALUE_KEYS have their *values* passed through
    without key conversion, so that e.g. HTTP-Referer stays HTTP-Referer.
    """
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            new_key = camel_to_snake(k)
            if k in _PRESERVE_VALUE_KEYS or new_key in _PRESERVE_VALUE_KEYS:
                # Preserve the dict value as-is (don't transform its keys)
                result[new_key] = v
            else:
                result[new_key] = convert_keys(v)
        return result
    if isinstance(data, list):
        return [convert_keys(item) for item in data]
    return data


def convert_to_camel(data: Any) -> Any:
    """Convert snake_case keys to camelCase.
    
    Keys listed in _PRESERVE_VALUE_KEYS have their *values* passed through
    without key conversion.
    """
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            new_key = snake_to_camel(k)
            if k in _PRESERVE_VALUE_KEYS or new_key in _PRESERVE_VALUE_KEYS:
                result[new_key] = v
            else:
                result[new_key] = convert_to_camel(v)
        return result
    if isinstance(data, list):
        return [convert_to_camel(item) for item in data]
    return data


def camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            result.append("_")
        result.append(char.lower())
    return "".join(result)


def snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])
