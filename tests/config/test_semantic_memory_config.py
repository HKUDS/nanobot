from __future__ import annotations

import pytest
from pydantic import ValidationError

from nanobot.config.schema import AgentDefaults, SemanticMemoryConfig


def test_semantic_memory_is_disabled_by_default() -> None:
    assert AgentDefaults().semantic_memory.enabled is False


def test_semantic_memory_accepts_camel_case() -> None:
    config = SemanticMemoryConfig.model_validate({
        "enabled": True,
        "dsnFile": "/tmp/db.env",
        "topK": 6,
        "candidateK": 12,
    })
    assert config.dsn_file == "/tmp/db.env"
    assert config.top_k == 6
    assert "db.env" not in repr(config.dsn)


def test_enabled_semantic_memory_requires_connection_source() -> None:
    with pytest.raises(ValidationError, match="dsn"):
        SemanticMemoryConfig(enabled=True)


def test_candidate_count_cannot_be_smaller_than_result_count() -> None:
    with pytest.raises(ValidationError, match="candidateK"):
        SemanticMemoryConfig(top_k=10, candidate_k=5)


def test_dsn_is_hidden_from_repr() -> None:
    secret = "postgresql://user:secret@example/db"
    config = SemanticMemoryConfig(enabled=True, dsn=secret)
    assert secret not in repr(config)
