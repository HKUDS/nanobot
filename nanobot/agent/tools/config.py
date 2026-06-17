"""Tool-owned configuration parsing helpers."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel

_CONFIG_CLASSES_BY_KEY: dict[str, type[BaseModel]] | None = None


def _extra_values(config: BaseModel) -> dict[str, Any]:
    return getattr(config, "__pydantic_extra__", None) or {}


def _set_extra_value(config: BaseModel, key: str, value: Any) -> None:
    setattr(config, key, value)


def _config_classes_by_key() -> dict[str, type[BaseModel]]:
    global _CONFIG_CLASSES_BY_KEY
    if _CONFIG_CLASSES_BY_KEY is not None:
        return _CONFIG_CLASSES_BY_KEY

    from nanobot.agent.tools.loader import ToolLoader

    classes: dict[str, type[BaseModel]] = {}
    for tool_cls in ToolLoader().discover_config_classes():
        key = getattr(tool_cls, "config_key", "")
        config_cls = tool_cls.config_cls()
        if not key or config_cls is None:
            continue
        previous = classes.get(key)
        if previous is not None and previous is not config_cls:
            logger.warning(
                "Tool config key collision for %s: %s replaces %s",
                key,
                config_cls.__name__,
                previous.__name__,
            )
        classes[key] = config_cls
    _CONFIG_CLASSES_BY_KEY = classes
    return classes


def _materialize_config(config: BaseModel, key: str, config_cls: type[BaseModel]) -> BaseModel:
    raw = _extra_values(config).get(key, None)
    if isinstance(raw, config_cls):
        return raw
    if raw is None:
        parsed = config_cls()
    elif isinstance(raw, BaseModel):
        parsed = config_cls.model_validate(raw.model_dump(mode="python"))
    else:
        parsed = config_cls.model_validate(raw)
    _set_extra_value(config, key, parsed)
    return parsed


def tool_config_by_key(config: Any, key: str) -> Any:
    """Return the parsed config section for a tool config key."""
    if not isinstance(config, BaseModel):
        return getattr(config, key)
    config_cls = _config_classes_by_key().get(key)
    if config_cls is None:
        raise KeyError(key)
    return _materialize_config(config, key, config_cls)


def materialize_tool_configs(config: Any) -> Any:
    """Parse all discoverable tool config sections on a ToolsConfig object."""
    if not isinstance(config, BaseModel):
        return config
    for key, config_cls in _config_classes_by_key().items():
        _materialize_config(config, key, config_cls)
    return config
