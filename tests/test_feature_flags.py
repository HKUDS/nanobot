"""Tests for FeaturesConfig and feature-flag propagation."""

from __future__ import annotations

from nanobot.config.agent import AgentConfig
from nanobot.config.schema import Config, FeaturesConfig, LogConfig

# ---------------------------------------------------------------------------
# FeaturesConfig defaults
# ---------------------------------------------------------------------------


class TestFeaturesConfigDefaults:
    def test_all_enabled_by_default(self):
        fc = FeaturesConfig()
        assert fc.planning_enabled is True
        assert fc.verification_enabled is True
        assert fc.delegation_enabled is True
        assert fc.memory_enabled is True
        assert fc.skills_enabled is True
        assert fc.streaming_enabled is True

    def test_disable_individual_flag(self):
        fc = FeaturesConfig(planning_enabled=False)
        assert fc.planning_enabled is False
        # Others remain default
        assert fc.delegation_enabled is True

    def test_all_disabled(self):
        fc = FeaturesConfig(
            planning_enabled=False,
            verification_enabled=False,
            delegation_enabled=False,
            memory_enabled=False,
            skills_enabled=False,
            streaming_enabled=False,
        )
        assert not fc.planning_enabled
        assert not fc.verification_enabled
        assert not fc.delegation_enabled
        assert not fc.memory_enabled
        assert not fc.skills_enabled
        assert not fc.streaming_enabled


# ---------------------------------------------------------------------------
# Config root includes features
# ---------------------------------------------------------------------------


class TestConfigFeatures:
    def test_default_features_in_config(self):
        cfg = Config()
        assert isinstance(cfg.features, FeaturesConfig)
        assert cfg.features.planning_enabled is True

    def test_override_features(self):
        cfg = Config(features=FeaturesConfig(memory_enabled=False))
        assert cfg.features.memory_enabled is False


# ---------------------------------------------------------------------------
# AgentConfig feature flags
# ---------------------------------------------------------------------------


class TestAgentConfigFlags:
    def test_default_flags(self):
        ac = AgentConfig(workspace="/tmp/test", model="test")
        assert ac.planning_enabled is True
        assert ac.delegation_enabled is True
        assert ac.memory_enabled is True
        assert ac.skills_enabled is True
        assert ac.streaming_enabled is True

    def test_override_via_constructor(self):
        ac = AgentConfig(
            workspace="/tmp/test",
            model="test",
            delegation_enabled=False,
            memory_enabled=False,
        )
        assert ac.delegation_enabled is False
        assert ac.memory_enabled is False


# ---------------------------------------------------------------------------
# Direct construction (replaces from_defaults tests)
# ---------------------------------------------------------------------------


class TestDirectConstruction:
    def test_basic_construction(self):
        ac = AgentConfig(model="gpt-4o", workspace="/tmp/ws")
        assert ac.model == "gpt-4o"
        assert ac.workspace == "/tmp/ws"

    def test_reranker_defaults(self):
        ac = AgentConfig(workspace="/tmp/test", model="test")
        assert ac.memory.reranker.mode == "enabled"
        assert ac.memory.reranker.alpha == 0.5

    def test_vector_defaults(self):
        ac = AgentConfig(workspace="/tmp/test", model="test")
        assert ac.memory.vector.user_id == "nanobot"
        assert ac.memory.vector.verify_write is True
        assert ac.memory.vector.force_infer is False

    def test_override_via_constructor(self):
        ac = AgentConfig(model="gpt-3.5", workspace="/tmp/ws")
        assert ac.model == "gpt-3.5"

    def test_feature_flags_default(self):
        """Feature flags have correct defaults."""
        ac = AgentConfig(workspace="/tmp/test", model="test")
        assert ac.planning_enabled is True
        assert ac.delegation_enabled is True

    def test_graph_enabled(self):
        ac = AgentConfig(workspace="/tmp/test", model="test", graph_enabled=True)
        assert ac.graph_enabled is True


# ---------------------------------------------------------------------------
# LogConfig defaults
# ---------------------------------------------------------------------------


class TestLogConfig:
    def test_defaults(self):
        lc = LogConfig()
        assert lc.level == "INFO"
        assert lc.json_stdout is False
        assert lc.json_file == ""

    def test_override(self):
        lc = LogConfig(level="DEBUG", json_stdout=True, json_file="/tmp/nanobot.log")
        assert lc.level == "DEBUG"
        assert lc.json_stdout is True
        assert lc.json_file == "/tmp/nanobot.log"

    def test_config_root_has_log(self):
        cfg = Config()
        assert isinstance(cfg.log, LogConfig)
        assert cfg.log.level == "INFO"
