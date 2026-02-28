from pathlib import Path

from nanobot.agent.memory import MemoryStore
from nanobot.config.schema import MemoryConfig


def test_embedding_runtime_config_fallback_to_legacy_gemini() -> None:
    cfg = MemoryConfig()
    cfg.gemini.api_key = "g-key"
    cfg.gemini.api_base = "https://generativelanguage.googleapis.com/v1beta"
    cfg.gemini.model = "models/gemini-embedding-001"
    cfg.embedding.api_key = ""

    store = MemoryStore(Path("."), cfg)
    resolved = store._embedding_runtime_config()

    assert resolved["provider"] == "gemini"
    assert resolved["api_key"] == "g-key"
    assert resolved["model"] == "models/gemini-embedding-001"


def test_embedding_runtime_config_prefers_openai_compatible_when_set() -> None:
    cfg = MemoryConfig()
    cfg.embedding.provider = "openai_compatible"
    cfg.embedding.api_key = "oa-key"
    cfg.embedding.api_base = "https://api.openai.com/v1"
    cfg.embedding.model = "text-embedding-3-small"
    cfg.embedding.output_dimensionality = 1536

    store = MemoryStore(Path("."), cfg)
    resolved = store._embedding_runtime_config()

    assert resolved["provider"] == "openai_compatible"
    assert resolved["api_key"] == "oa-key"
    assert resolved["model"] == "text-embedding-3-small"
    assert resolved["output_dimensionality"] == 1536
