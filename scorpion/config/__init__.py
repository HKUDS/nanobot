"""Configuration module for scorpion."""

from scorpion.config.loader import load_config, get_config_path
from scorpion.config.schema import Config

__all__ = ["Config", "load_config", "get_config_path"]
