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
        assert ac.delegation_enabled is True
        assert ac.memory_enabled is True
        assert ac.skills_enabled is True
        assert ac.streaming_enabled is True

    def test_from_raw_flat(self):
        ac = AgentConfig.from_raw({"workspace": "/tmp/test", "model": "test", "maxTokens": 4096})
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

    def test_camel_case_json(self):
        ac = AgentConfig.model_validate(
            {
                "workspace": "/tmp/t",
                "model": "test",
                "maxTokens": 16384,
                "memory": {"tokenBudget": 500},
            }
        )
        assert ac.max_tokens == 16384
        assert ac.memory.token_budget == 500
