"""Configuration loading utilities."""

import json
import os
import re
from pathlib import Path

from pydantic.alias_generators import to_camel
import pydantic
from loguru import logger

from nanobot.config.schema import Config


_OPAQUE_KEYS = frozenset({"env", "headers", "extraHeaders", "extra_headers"})
_NAMED_KEYS = frozenset({"mcp_servers", "mcpServers"})


def _keys_to_camel(obj, _mode="convert"):
    """Recursively convert dict keys from snake_case to camelCase.

    _mode controls how dict keys at the current level are handled:
      "convert"  – normal: keys are converted, recurse into values
      "preserve" – keys are kept as-is, values still recurse normally
                   (for named dicts like mcpServers whose keys are user names)
      "opaque"   – keys are kept as-is, values are NOT recursed
                   (for data dicts like env vars, HTTP headers)
    """
    if isinstance(obj, dict):
        if _mode == "opaque":
            return dict(obj)
        if _mode == "preserve":
            return {k: _keys_to_camel(v, _mode="convert") for k, v in obj.items()}
        return {
            to_camel(k): _keys_to_camel(
                v,
                _mode="opaque" if k in _OPAQUE_KEYS
                else "preserve" if k in _NAMED_KEYS
                else "convert",
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_keys_to_camel(i, _mode=_mode) for i in obj]
    return obj


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
    return Path.home() / ".hiperone" / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    config = Config()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            config = Config.model_validate(data)
        except (json.JSONDecodeError, ValueError, pydantic.ValidationError) as e:
            logger.warning(f"Failed to load config from {path}: {e}")
            logger.warning("Using default configuration.")

    _apply_ssrf_whitelist(config)
    return config


def _apply_ssrf_whitelist(config: Config) -> None:
    """Apply SSRF whitelist from config to the network security module."""
    from nanobot.security.network import configure_ssrf_whitelist

    configure_ssrf_whitelist(config.tools.ssrf_whitelist)


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", by_alias=True)
    data = _keys_to_camel(data)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def resolve_config_env_vars(config: Config) -> Config:
    """Return a copy of *config* with ``${VAR}`` env-var references resolved.

    Only string values are affected; other types pass through unchanged.
    Raises :class:`ValueError` if a referenced variable is not set.
    """
    data = config.model_dump(mode="json", by_alias=True)
    data = _resolve_env_vars(data)
    return Config.model_validate(data)


def _resolve_env_vars(obj: object) -> object:
    """Recursively resolve ``${VAR}`` patterns in string values."""
    if isinstance(obj, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _env_replace, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


def _env_replace(match: re.Match[str]) -> str:
    name = match.group(1)
    value = os.environ.get(name)
    if value is None:
        raise ValueError(
            f"Environment variable '{name}' referenced in config is not set"
        )
    return value


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data
