"""Tests for nanobot.config.schema."""

import pytest


def test_memory_index_defaults():
    from nanobot.config.schema import MemoryIndexConfig

    cfg = MemoryIndexConfig()
    assert cfg.enabled is False
    assert cfg.embedding.provider == "ollama"
    assert cfg.embedding.model == "nomic-embed-text"
    assert cfg.embedding.base_url == "http://localhost:11434"
    assert cfg.embedding.batch_size == 16
    assert cfg.embedding.dim == 768
    assert cfg.query.top_k == 5
    assert cfg.query.mmr_lambda == 0.5
    assert cfg.query.temporal_decay_half_life_days == 90.0


def test_memory_index_on_root_config():
    from nanobot.config.schema import Config

    cfg = Config()
    assert cfg.memory_index.enabled is False


def test_memory_index_camel_case():
    from nanobot.config.schema import MemoryIndexConfig

    # snake_case keys (populate_by_name=True)
    cfg = MemoryIndexConfig.model_validate(
        {
            "enabled": True,
            "embedding": {"model": "mxbai-embed-large", "dim": 1024},
        }
    )
    assert cfg.enabled is True
    assert cfg.embedding.model == "mxbai-embed-large"
    assert cfg.embedding.dim == 1024

    # camelCase keys (alias_generator=to_camel)
    cfg2 = MemoryIndexConfig.model_validate(
        {
            "enabled": True,
            "embedding": {"batchSize": 32, "baseUrl": "http://localhost:22222"},
        }
    )
    assert cfg2.embedding.batch_size == 32
    assert cfg2.embedding.base_url == "http://localhost:22222"
