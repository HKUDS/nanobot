"""Configuration loading utilities."""

import json
import os
from pathlib import Path

import pydantic
from dotenv import load_dotenv
from loguru import logger

from janniebot.config.schema import Config

# Global variable to store current config path (for multi-instance support)
_current_config_path: Path | None = None


def load_project_dotenv() -> None:
    """Load .env files into os.environ.

    Load order (later files do NOT overwrite earlier values):
      1. ``./.env`` (project root)
      2. ``~/.janniebot/.env`` (user home)

    Variables already present in the shell environment are never overwritten.

    After loading, bare provider API-key env vars (e.g. ``OPENROUTER_API_KEY``)
    are bridged into the ``JANNIEBOT_PROVIDERS__<NAME>__API_KEY`` namespace so
    that pydantic-settings picks them up automatically.
    """
    load_dotenv(Path.cwd() / ".env", override=False)
    load_dotenv(Path.home() / ".janniebot" / ".env", override=False)
    _bridge_provider_env_keys()


def _bridge_provider_env_keys() -> None:
    """Copy bare ``<PROVIDER>_API_KEY`` env vars into the pydantic-settings namespace.

    For each provider in the registry that defines an ``env_key``
    (e.g. ``OPENROUTER_API_KEY``), if that var is set but the corresponding
    ``JANNIEBOT_PROVIDERS__<NAME>__API_KEY`` is not, copy the value across.
    This lets users write simple ``OPENROUTER_API_KEY=...`` in ``.env``
    without needing the verbose ``JANNIEBOT_PROVIDERS__OPENROUTER__API_KEY``.
    """
    from janniebot.providers.registry import PROVIDERS

    for spec in PROVIDERS:
        if not spec.env_key:
            continue
        val = os.environ.get(spec.env_key)
        if not val:
            continue
        settings_key = f"JANNIEBOT_PROVIDERS__{spec.name.upper()}__API_KEY"
        os.environ.setdefault(settings_key, val)


def set_config_path(path: Path) -> None:
    """Set the current config path (used to derive data directory)."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the configuration file path."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".janniebot" / "config.json"


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
    from janniebot.security.network import configure_ssrf_whitelist

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
