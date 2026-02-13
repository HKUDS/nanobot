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
            config = Config.model_validate(convert_keys(data))
            # Register custom providers from config
            _register_custom_providers(config)
            return config
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")
    
    config = Config()
    # Register custom providers from default config
    _register_custom_providers(config)
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


def convert_keys(data: Any) -> Any:
    """Convert camelCase keys to snake_case for Pydantic."""
    if isinstance(data, dict):
        return {camel_to_snake(k): convert_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [convert_keys(item) for item in data]
    return data


def convert_to_camel(data: Any) -> Any:
    """Convert snake_case keys to camelCase."""
    if isinstance(data, dict):
        return {snake_to_camel(k): convert_to_camel(v) for k, v in data.items()}
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


def _register_custom_providers(config: Config) -> None:
    """
    Register custom providers from configuration to the provider registry.
    
    This function is called automatically when config is loaded.
    """
    from nanobot.providers.registry import register_custom_provider, clear_custom_providers
    
    # Clear any previously registered custom providers
    clear_custom_providers()
    
    # Register each custom provider from config
    for custom_provider in config.providers.custom_providers:
        # Generate keywords from models if not provided
        keywords = tuple(custom_provider.models) if custom_provider.models else (custom_provider.name,)
        
        # Generate env_key if not provided
        env_key = custom_provider.env_key or f"{custom_provider.name.upper()}_API_KEY"
        
        # Register the custom provider
        register_custom_provider(
            name=custom_provider.name,
            display_name=custom_provider.display_name or custom_provider.name.title(),
            keywords=keywords,
            env_key=env_key,
            litellm_prefix=custom_provider.litellm_prefix,
            skip_prefixes=(),
            env_extras=tuple(custom_provider.env_extras),
            is_gateway=custom_provider.is_gateway,
            is_local=False,
            detect_by_key_prefix="",
            detect_by_base_keyword="",
            default_api_base=custom_provider.default_api_base,
            strip_model_prefix=False,
            model_overrides=(),
        )
