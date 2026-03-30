"""Tests for memory backend configuration."""


def test_memory_config_defaults():
    from nanobot.config.schema import MemoryConfig

    cfg = MemoryConfig()
    assert cfg.backend == "default"


def test_memory_config_backend_can_be_set():
    from nanobot.config.schema import MemoryConfig

    cfg = MemoryConfig(backend="graphiti")
    assert cfg.backend == "graphiti"


def test_config_has_memory_field():
    from nanobot.config.schema import Config

    cfg = Config()
    assert cfg.memory.backend == "default"
