"""Configuration loading utilities."""

import json
from pathlib import Path
from typing import Any

from nanobot.config.schema import Config
from nanobot.config.secret_resolver import has_env_ref, resolve_config, resolve_env_vars

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
                raw_data = json.load(f)
            raw_data = _migrate_config(raw_data)

            # Record original values of fields containing {env:VAR} references
            env_refs: dict[str, dict[str, str]] = {}
            _collect_env_refs(raw_data, "", env_refs)

            resolved_data = resolve_config(raw_data)
            config = Config.model_validate(resolved_data)
            config._env_refs = env_refs  # Preserve original {env:VAR} values for save_config
            return config
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

    # Preserve original {env:VAR} placeholders only for values unchanged since load.
    data = config.model_dump(by_alias=True)
    if config._env_refs:
        _restore_env_refs(data, config._env_refs)

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


def _collect_env_refs(obj: Any, path: str, refs: dict[str, dict[str, str]]) -> None:
    """Collect field paths with original and resolved values for {env:VAR} strings."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}" if path else key
            _collect_env_refs(value, child_path, refs)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _collect_env_refs(item, f"{path}[{idx}]", refs)
    elif isinstance(obj, str) and has_env_ref(obj):
        refs[path] = {
            "original": obj,
            "resolved": resolve_env_vars(obj),
        }


def _restore_env_refs(data: dict, refs: dict[str, dict[str, str]]) -> None:
    """Restore original {env:VAR} values into unchanged fields."""
    for path, record in refs.items():
        found, current_value = _get_by_path(data, path)
        if not found:
            continue
        if current_value == record["resolved"]:
            _set_by_path(data, path, record["original"])


def _parse_path(path: str) -> list[str | int]:
    """Parse dotted/list path like providers.openai.apiKey or args[0]."""
    tokens: list[str | int] = []
    buf = ""
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == ".":
            if buf:
                tokens.append(buf)
                buf = ""
            i += 1
            continue
        if ch == "[":
            if buf:
                tokens.append(buf)
                buf = ""
            close = path.find("]", i + 1)
            if close == -1:
                return []
            idx = path[i + 1 : close]
            if not idx.isdigit():
                return []
            tokens.append(int(idx))
            i = close + 1
            continue
        buf += ch
        i += 1
    if buf:
        tokens.append(buf)
    return tokens


def _get_by_path(data: Any, path: str) -> tuple[bool, Any]:
    """Get value from nested dict/list path."""
    tokens = _parse_path(path)
    if not tokens:
        return False, None

    current = data
    for token in tokens:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                return False, None
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                return False, None
            current = current[token]
    return True, current


def _set_by_path(data: Any, path: str, value: Any) -> None:
    """Set value in nested dict/list path."""
    tokens = _parse_path(path)
    if not tokens:
        return

    current = data
    for token in tokens[:-1]:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                return
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                return
            current = current[token]

    last = tokens[-1]
    if isinstance(last, int):
        if isinstance(current, list) and last < len(current):
            current[last] = value
        return

    if isinstance(current, dict) and last in current:
        current[last] = value
