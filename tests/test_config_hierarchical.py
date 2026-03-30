"""Tests for the new hierarchical AgentConfig."""

from __future__ import annotations

from nanobot.config.agent import AgentConfig
from nanobot.config.memory import MemoryConfig
from nanobot.config.mission import MissionConfig


class TestMissionConfig:
    def test_defaults(self):
        mc = MissionConfig()
        assert mc.max_concurrent == 3
        assert mc.max_iterations == 15
        assert mc.result_max_chars == 4000


class TestAgentConfigHierarchical:
    def test_defaults(self):
        ac = AgentConfig(workspace="/tmp/test", model="test")
        assert ac.workspace == "/tmp/test"
        assert ac.model == "test"
        assert isinstance(ac.memory, MemoryConfig)
        assert isinstance(ac.mission, MissionConfig)
        assert ac.memory.window == 100
        assert ac.mission.max_concurrent == 3

    def test_nested_memory_override(self):
        ac = AgentConfig(
            workspace="/tmp/test",
            model="test",
            memory=MemoryConfig(window=50, rollout_mode="disabled"),
        )
        assert ac.memory.window == 50
        assert ac.memory.rollout_mode == "disabled"

    def test_feature_flags(self):
        ac = AgentConfig(workspace="/tmp/test", model="test")
        assert ac.planning_enabled is True
        assert ac.memory_enabled is True
        assert ac.skills_enabled is True
        assert ac.streaming_enabled is True

    def test_from_raw_flat(self):
        ac = AgentConfig.from_raw({"workspace": "/tmp/test", "model": "test", "max_tokens": 4096})
        assert ac.max_tokens == 4096

    def test_from_raw_nested(self):
        ac = AgentConfig.from_raw(
            {
                "workspace": "/tmp/test",
                "model": "test",
                "memory": {"window": 50, "reranker": {"mode": "shadow"}},
            }
        )
        assert ac.memory.window == 50
        assert ac.memory.reranker.mode == "shadow"

    def test_from_raw_with_overrides(self):
        ac = AgentConfig.from_raw(
            {"workspace": "/tmp/test", "model": "base"},
            model="override",
        )
        assert ac.model == "override"

    def test_workspace_path(self):
        ac = AgentConfig(workspace="~/test", model="test")
        assert ac.workspace_path.name == "test"

    def test_snake_case_json(self):
        ac = AgentConfig.model_validate(
            {
                "workspace": "/tmp/t",
                "model": "test",
                "max_tokens": 16384,
                "memory": {"token_budget": 500},
            }
        )
        assert ac.max_tokens == 16384
        assert ac.memory.token_budget == 500


class TestConfigRoundTrip:
    """Verify JSON → AgentConfig → JSON loses no data."""

    def test_round_trip_preserves_all_fields(self):
        """model_validate → model_dump round-trip is lossless."""
        original = {
            "workspace": "/test/ws",
            "model": "test-model",
            "max_tokens": 4096,
            "temperature": 0.5,
            "max_iterations": 20,
            "context_window_tokens": 64_000,
            "planning_enabled": False,
            "verification_mode": "always",
            "memory_enabled": False,
            "skills_enabled": False,
            "streaming_enabled": False,
            "shell_mode": "allowlist",
            "restrict_to_workspace": False,
            "tool_result_max_chars": 500,
            "tool_result_context_tokens": 100,
            "tool_summary_model": "gpt-4o-mini",
            "vision_model": "gpt-4o",
            "summary_model": "gpt-4o-mini",
            "message_timeout": 60,
            "max_session_cost_usd": 1.5,
            "max_session_wall_time_seconds": 600,
            "memory": {
                "window": 50,
                "retrieval_k": 10,
                "token_budget": 500,
                "rollout_mode": "shadow",
                "micro_extraction_enabled": True,
                "micro_extraction_model": "gpt-4o-mini",
                "graph_enabled": True,
                "reranker": {"mode": "shadow", "alpha": 0.8, "model": "custom/m"},
                "vector": {"user_id": "custom", "add_debug": True},
            },
            "mission": {"max_concurrent": 5, "max_iterations": 30},
        }
        ac = AgentConfig(**original)
        dumped = ac.model_dump()

        # Every key in the original must be present with the same value
        for key, value in original.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, dict):
                        for sub_sub_key, sub_sub_value in sub_value.items():
                            assert dumped[key][sub_key][sub_sub_key] == sub_sub_value, (
                                f"{key}.{sub_key}.{sub_sub_key}"
                            )
                    else:
                        assert dumped[key][sub_key] == sub_value, f"{key}.{sub_key}"
            else:
                assert dumped[key] == value, key

    def test_snake_case_round_trip(self):
        """snake_case JSON → AgentConfig → snake_case JSON preserves keys."""
        snake_json = {
            "workspace": "/tmp/t",
            "model": "test",
            "max_tokens": 16384,
            "memory": {"token_budget": 500, "reranker": {"mode": "shadow"}},
            "mission": {"max_concurrent": 5},
        }
        ac = AgentConfig.model_validate(snake_json)
        dumped = ac.model_dump()
        assert dumped["max_tokens"] == 16384
        assert dumped["memory"]["token_budget"] == 500
        assert dumped["memory"]["reranker"]["mode"] == "shadow"
        assert dumped["mission"]["max_concurrent"] == 5


class TestConfigCompleteness:
    """Verify every AgentConfig field is reachable from JSON config data."""

    def test_all_top_level_fields_settable(self):
        """Every top-level field on AgentConfig can be set via from_raw()."""
        data = {
            "workspace": "/test/ws",
            "model": "test-model",
            "max_tokens": 4096,
            "temperature": 0.5,
            "max_iterations": 20,
            "context_window_tokens": 64_000,
            "planning_enabled": False,
            "verification_mode": "always",
            "memory_enabled": False,
            "skills_enabled": False,
            "streaming_enabled": False,
            "shell_mode": "allowlist",
            "restrict_to_workspace": False,
            "tool_result_max_chars": 500,
            "tool_result_context_tokens": 100,
            "tool_summary_model": "gpt-4o-mini",
            "vision_model": "gpt-4o",
            "summary_model": "gpt-4o-mini",
            "message_timeout": 60,
            "max_session_cost_usd": 1.5,
            "max_session_wall_time_seconds": 600,
            "memory": {"graph_enabled": True},
        }
        ac = AgentConfig.from_raw(data)
        assert ac.workspace == "/test/ws"
        assert ac.model == "test-model"
        assert ac.max_tokens == 4096
        assert ac.temperature == 0.5
        assert ac.max_iterations == 20
        assert ac.context_window_tokens == 64_000
        assert ac.planning_enabled is False
        assert ac.verification_mode == "always"
        assert ac.memory_enabled is False
        assert ac.skills_enabled is False
        assert ac.streaming_enabled is False
        assert ac.shell_mode == "allowlist"
        assert ac.restrict_to_workspace is False
        assert ac.tool_result_max_chars == 500
        assert ac.tool_result_context_tokens == 100
        assert ac.tool_summary_model == "gpt-4o-mini"
        assert ac.vision_model == "gpt-4o"
        assert ac.summary_model == "gpt-4o-mini"
        assert ac.message_timeout == 60
        assert ac.max_session_cost_usd == 1.5
        assert ac.max_session_wall_time_seconds == 600
        assert ac.memory.graph_enabled is True

    def test_all_memory_fields_settable(self):
        """Every MemoryConfig field is reachable via nested JSON."""
        data = {
            "workspace": "/tmp/t",
            "model": "test",
            "memory": {
                "window": 50,
                "retrieval_k": 10,
                "token_budget": 500,
                "md_token_cap": 800,
                "uncertainty_threshold": 0.3,
                "enable_contradiction_check": False,
                "conflict_auto_resolve_gap": 0.5,
                "rollout_mode": "shadow",
                "type_separation_enabled": False,
                "router_enabled": False,
                "reflection_enabled": False,
                "shadow_mode": True,
                "shadow_sample_rate": 0.5,
                "vector_health_enabled": False,
                "auto_reindex_on_empty_vector": False,
                "history_fallback_enabled": True,
                "fallback_allowed_sources": ["profile"],
                "fallback_max_summary_chars": 100,
                "rollout_gate_min_recall_at_k": 0.7,
                "rollout_gate_min_precision_at_k": 0.4,
                "rollout_gate_max_avg_context_tokens": 2000.0,
                "rollout_gate_max_history_fallback_ratio": 0.1,
                "section_weights": {},
                "micro_extraction_enabled": True,
                "micro_extraction_model": "gpt-4o-mini",
                "raw_turn_ingestion": False,
                "reranker": {"mode": "shadow", "alpha": 0.8, "model": "custom/model"},
                "vector": {
                    "user_id": "custom",
                    "add_debug": True,
                    "verify_write": False,
                    "force_infer": True,
                },
            },
        }
        ac = AgentConfig.from_raw(data)
        m = ac.memory
        assert m.window == 50
        assert m.retrieval_k == 10
        assert m.token_budget == 500
        assert m.md_token_cap == 800
        assert m.uncertainty_threshold == 0.3
        assert m.enable_contradiction_check is False
        assert m.conflict_auto_resolve_gap == 0.5
        assert m.rollout_mode == "shadow"
        assert m.type_separation_enabled is False
        assert m.router_enabled is False
        assert m.reflection_enabled is False
        assert m.shadow_mode is True
        assert m.shadow_sample_rate == 0.5
        assert m.vector_health_enabled is False
        assert m.auto_reindex_on_empty_vector is False
        assert m.history_fallback_enabled is True
        assert m.fallback_allowed_sources == ["profile"]
        assert m.fallback_max_summary_chars == 100
        assert m.rollout_gate_min_recall_at_k == 0.7
        assert m.rollout_gate_min_precision_at_k == 0.4
        assert m.rollout_gate_max_avg_context_tokens == 2000.0
        assert m.rollout_gate_max_history_fallback_ratio == 0.1
        assert m.micro_extraction_enabled is True
        assert m.micro_extraction_model == "gpt-4o-mini"
        assert m.raw_turn_ingestion is False
        assert m.reranker.mode == "shadow"
        assert m.reranker.alpha == 0.8
        assert m.reranker.model == "custom/model"
        assert m.vector.user_id == "custom"
        assert m.vector.add_debug is True
        assert m.vector.verify_write is False
        assert m.vector.force_infer is True

    def test_all_mission_fields_settable(self):
        """Every MissionConfig field is reachable via nested JSON."""
        data = {
            "workspace": "/tmp/t",
            "model": "test",
            "mission": {
                "max_concurrent": 5,
                "max_iterations": 30,
                "result_max_chars": 8000,
            },
        }
        ac = AgentConfig.from_raw(data)
        assert ac.mission.max_concurrent == 5
        assert ac.mission.max_iterations == 30
        assert ac.mission.result_max_chars == 8000
