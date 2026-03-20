"""Configuration module for nanobot."""

from __future__ import annotations

from nanobot.config.loader import get_config_path, load_config
from nanobot.config.schema import Config

__all__ = ["Config", "load_config", "get_config_path"]
