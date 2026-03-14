"""Configuration loading utilities."""

import json
import os
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel

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
            if not isinstance(data, dict):
                raise ValueError("Config file must contain a JSON object at the top level")
            data = _migrate_config(data)
            data = _normalize_model_data(Config, data)
            env_overrides = _load_env_overrides()
            if env_overrides:
                data = _deep_merge(data, env_overrides)
            return Config.model_validate(data)
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


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data


def _load_env_overrides() -> dict[str, Any]:
    """Collect NANOBOT_* environment overrides into a nested config dict."""
    prefix = "NANOBOT_"
    overrides: dict[str, Any] = {}

    for key, raw_value in os.environ.items():
        if not key.startswith(prefix):
            continue

        path = [part.lower() for part in key[len(prefix):].split("__") if part]
        if not path:
            continue

        current = overrides
        for part in path[:-1]:
            current = current.setdefault(part, {})
        current[path[-1]] = _parse_env_value(raw_value)

    return overrides


def _normalize_model_data(model: type[BaseModel], data: dict[str, Any]) -> dict[str, Any]:
    """Normalize config dict keys to Pydantic field names before merging overrides."""
    normalized: dict[str, Any] = {}

    field_lookup = {}
    for field_name, field in model.model_fields.items():
        field_lookup[field_name] = (field_name, field.annotation)
        if field.alias:
            field_lookup[field.alias] = (field_name, field.annotation)

    for raw_key, value in data.items():
        field_info = field_lookup.get(raw_key)
        if field_info is None:
            normalized[raw_key] = _normalize_untyped_value(value)
            continue

        field_name, annotation = field_info
        normalized[field_name] = _normalize_value(annotation, value)

    return normalized


def _normalize_value(annotation: Any, value: Any) -> Any:
    """Normalize nested config values using their annotated model types."""
    model = _extract_model_type(annotation)
    if model and isinstance(value, dict):
        return _normalize_model_data(model, value)

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is dict and len(args) == 2 and isinstance(value, dict):
        return {key: _normalize_value(args[1], item) for key, item in value.items()}

    if origin is list and len(args) == 1 and isinstance(value, list):
        return [_normalize_value(args[0], item) for item in value]

    return value


def _extract_model_type(annotation: Any) -> type[BaseModel] | None:
    """Return the nested Pydantic model type from an annotation, if present."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation

    for arg in get_args(annotation):
        model = _extract_model_type(arg)
        if model is not None:
            return model

    return None


def _normalize_untyped_value(value: Any) -> Any:
    """Recursively copy unknown nested structures without changing their keys."""
    if isinstance(value, dict):
        return {key: _normalize_untyped_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_untyped_value(item) for item in value]
    return value


def _parse_env_value(value: str) -> Any:
    """Parse JSON-like environment values while keeping plain strings intact."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge env overrides onto config file data."""
    merged = dict(base)

    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value

    return merged
