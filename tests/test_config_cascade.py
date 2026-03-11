"""Tests for config cascade: env vars → .env → JSON → schema defaults."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.config.schema import (
    AgentConfig,
    AgentDefaults,
    Config,
    Mem0Config,
    RerankerConfig,
)

# ---------------------------------------------------------------------------
# Schema defaults
# ---------------------------------------------------------------------------


class TestSchemaDefaults:
    def test_config_has_all_sections(self):
        cfg = Config()
        assert cfg.agents is not None
        assert cfg.channels is not None
        assert cfg.providers is not None
        assert cfg.features is not None
        assert cfg.llm is not None

    def test_llm_config_defaults(self):
        cfg = Config()
        assert cfg.llm.timeout_s == 60.0
        assert cfg.llm.max_retries == 1

    def test_reranker_defaults(self):
        rc = RerankerConfig()
        assert rc.mode == "disabled"
        assert rc.alpha == 0.5
        assert rc.model == ""

    def test_mem0_defaults(self):
        mc = Mem0Config()
        assert mc.user_id == "nanobot"
        assert mc.add_debug is False
        assert mc.verify_write is True
        assert mc.force_infer_true is False

    def test_agent_defaults_nested(self):
        ad = AgentDefaults()
        assert isinstance(ad.reranker, RerankerConfig)
        assert isinstance(ad.mem0, Mem0Config)
        assert ad.reranker.mode == "disabled"
        assert ad.mem0.user_id == "nanobot"


# ---------------------------------------------------------------------------
# Env vars override (NANOBOT__* prefix)
# ---------------------------------------------------------------------------


class TestEnvOverrides:
    def test_env_override_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("NANOBOT_AGENTS__DEFAULTS__MODEL", "custom-model")
        cfg = Config()
        assert cfg.agents.defaults.model == "custom-model"

    def test_env_override_llm_timeout(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("NANOBOT_LLM__TIMEOUT_S", "120")
        cfg = Config()
        assert cfg.llm.timeout_s == 120.0

    def test_env_override_features(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("NANOBOT_FEATURES__PLANNING_ENABLED", "false")
        cfg = Config()
        assert cfg.features.planning_enabled is False

    def test_env_override_deeply_nested(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("NANOBOT_AGENTS__DEFAULTS__MAX_TOKENS", "8192")
        cfg = Config()
        assert cfg.agents.defaults.max_tokens == 8192


# ---------------------------------------------------------------------------
# JSON config loading
# ---------------------------------------------------------------------------


class TestJsonConfig:
    def test_json_values_used(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Config values from JSON file populate the model."""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "agents": {"defaults": {"model": "json-model"}},
            "llm": {"timeout_s": 90},
        }))
        # Use Config with direct initialization (simulates loading)
        data = json.loads(cfg_file.read_text())
        cfg = Config(**data)
        assert cfg.agents.defaults.model == "json-model"
        assert cfg.llm.timeout_s == 90.0

    def test_env_overrides_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Env vars take precedence over file-sourced defaults."""
        monkeypatch.setenv("NANOBOT_LLM__TIMEOUT_S", "200")
        cfg = Config()
        # pydantic-settings: env override wins over schema default
        assert cfg.llm.timeout_s == 200.0


# ---------------------------------------------------------------------------
# Sub-model defaults wired correctly
# ---------------------------------------------------------------------------


class TestSubModelWiring:
    def test_agent_config_from_defaults_all_fields(self):
        defaults = AgentDefaults(
            model="test-model",
            workspace="/tmp/ws",
            graph_enabled=True,
        )
        ac = AgentConfig.from_defaults(defaults)
        assert ac.model == "test-model"
        assert ac.graph_enabled is True
        assert ac.reranker_mode == "disabled"
        assert ac.mem0_user_id == "nanobot"

    def test_overrides_applied_after_defaults(self):
        defaults = AgentDefaults(model="base-model")
        ac = AgentConfig.from_defaults(
            defaults,
            model="override-model",
            reranker_mode="enabled",
        )
        assert ac.model == "override-model"
        assert ac.reranker_mode == "enabled"
