"""Tests for LayeredMemoryConfig schema."""

import pytest
from pydantic import ValidationError

from nanobot.config.schema import (
    AgentDefaults,
    LayeredMemoryConfig,
    LayeredMemoryOffloadConfig,
    LayeredMemoryPipelineConfig,
    LayeredMemoryRecallConfig,
    LayeredMemorySubagentConfig,
)


def test_layered_memory_offload_defaults() -> None:
    cfg = LayeredMemoryOffloadConfig()
    assert cfg.enable is False
    assert cfg.max_canvas_chars == 1500
    assert cfg.max_node_summary_chars == 120
    assert cfg.update_canvas_every_n_tools == 0


def test_layered_memory_pipeline_defaults() -> None:
    cfg = LayeredMemoryPipelineConfig()
    assert cfg.every_n_conversations == 5
    assert cfg.enable_warmup is True
    assert cfg.l1_idle_timeout_seconds == 600
    assert cfg.l2_delay_after_l1_seconds == 90
    assert cfg.l2_min_interval_seconds == 900
    assert cfg.l2_max_interval_seconds == 3600
    assert cfg.session_active_window_hours == 24
    assert cfg.max_memories_per_session == 20
    assert cfg.enable_l1_dedup is True


def test_layered_memory_recall_defaults() -> None:
    cfg = LayeredMemoryRecallConfig()
    assert cfg.enable is False
    assert cfg.strategy == "hybrid"
    assert cfg.top_k == 8
    assert cfg.timeout_ms == 5000
    assert cfg.max_search_calls_per_turn == 3


def test_layered_memory_config_defaults() -> None:
    cfg = LayeredMemoryConfig()
    assert cfg.enable is False
    assert cfg.offload.enable is False
    assert cfg.capture.l0_retention_days == 30
    assert cfg.embedding.enable is False
    assert cfg.subagent.enable_offload is False
    assert cfg.offload_enabled() is False
    assert cfg.capture_enabled() is False
    assert cfg.recall_enabled() is False


def test_layered_memory_enable_flags() -> None:
    cfg = LayeredMemoryConfig(
        enable=True,
        offload=LayeredMemoryOffloadConfig(enable=True),
        recall=LayeredMemoryRecallConfig(enable=True),
    )
    assert cfg.offload_enabled() is True
    assert cfg.recall_enabled() is True
    assert cfg.offload_enabled(is_subagent=True) is False
    assert cfg.recall_enabled(is_subagent=True) is False


def test_layered_memory_subagent_overrides() -> None:
    cfg = LayeredMemoryConfig(
        enable=True,
        offload=LayeredMemoryOffloadConfig(enable=True),
        subagent=LayeredMemorySubagentConfig(enable_offload=True),
    )
    assert cfg.offload_enabled(is_subagent=True) is True


def test_layered_memory_accepts_nested_camel_case() -> None:
    cfg = LayeredMemoryConfig.model_validate(
        {
            "enable": True,
            "offload": {
                "enable": True,
                "maxCanvasChars": 2000,
                "updateCanvasEveryNTools": 5,
            },
            "pipeline": {
                "everyNConversations": 3,
                "l1IdleTimeoutSeconds": 300,
            },
            "recall": {
                "enable": True,
                "strategy": "fts",
                "topK": 5,
                "timeoutMs": 4000,
            },
        }
    )
    assert cfg.enable is True
    assert cfg.offload.max_canvas_chars == 2000
    assert cfg.offload.update_canvas_every_n_tools == 5
    assert cfg.pipeline.every_n_conversations == 3
    assert cfg.pipeline.l1_idle_timeout_seconds == 300
    assert cfg.recall.strategy == "fts"
    assert cfg.recall.top_k == 5
    assert cfg.recall.timeout_ms == 4000


def test_layered_memory_recall_strategy_validation() -> None:
    with pytest.raises(ValidationError):
        LayeredMemoryRecallConfig(strategy="vector")  # type: ignore[arg-type]


def test_agent_defaults_includes_layered_memory() -> None:
    defaults = AgentDefaults()
    assert isinstance(defaults.layered_memory, LayeredMemoryConfig)
    assert defaults.layered_memory.enable is False


def test_agent_defaults_layered_memory_from_json_alias() -> None:
    defaults = AgentDefaults.model_validate(
        {
            "layeredMemory": {
                "enable": True,
                "offload": {"enable": True},
            },
        }
    )
    assert defaults.layered_memory.enable is True
    assert defaults.layered_memory.offload.enable is True
