"""Configuration loading utilities."""

import json
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

    config.sync_legacy_defaults()
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

    agents = data.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    models = agents.get("models")

    if not models:
        legacy_model = defaults.get("model") or "anthropic/claude-opus-4-5"
        legacy_provider = defaults.get("provider") or "auto"
        agents["models"] = [
            {
                "id": defaults.get("modelId") or "default",
                "name": legacy_model,
                "provider": legacy_provider,
                "model": legacy_model,
                "apiKey": None,
                "apiBase": None,
                "extraHeaders": None,
                "maxTokens": defaults.get("maxTokens", 8192),
                "contextWindowTokens": defaults.get("contextWindowTokens", 65_536),
                "temperature": defaults.get("temperature", 0.1),
                "reasoningEffort": defaults.get("reasoningEffort"),
                "enabled": True,
            }
        ]
    else:
        for item in models:
            if isinstance(item, dict) and item.get("name") == "默认模型":
                item["name"] = item.get("model") or "默认模型"

    if "modelId" not in defaults:
        first_enabled = next((item for item in agents["models"] if item.get("enabled", True)), None)
        defaults["modelId"] = (first_enabled or agents["models"][0]).get("id", "default")
    return data
