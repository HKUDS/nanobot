"""Persistence and environment compatibility for optional Langfuse settings."""

import json

import pytest

from nanobot.config.errors import ConfigLoadError
from nanobot.config.loader import load_config, resolve_config_env_vars, save_config
from nanobot.config.schema import Config
from nanobot.observability.config import (
    DEFAULT_LANGFUSE_BASE_URL,
    LangfuseConfig,
    editable_langfuse_config,
    resolve_langfuse_config,
)


@pytest.fixture(autouse=True)
def legacy_environment(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "legacy-public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "legacy-secret")
    monkeypatch.setenv("LANGFUSE_HOST", "https://legacy.example")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_TRACING_ENABLED", raising=False)


@pytest.mark.parametrize("observability", [{}, {"langfuse": None}])
def test_unrelated_save_keeps_legacy_environment_behavior(tmp_path, observability):
    path = tmp_path / "config.json"
    config = Config.model_validate({"observability": observability})
    config.agents.defaults.bot_name = "renamed"
    save_config(config, path)

    saved = json.loads(path.read_text())
    assert saved["observability"].get("langfuse") is None
    reloaded = load_config(path)
    effective = resolve_langfuse_config(reloaded)
    assert effective.enabled and effective.configured
    assert effective.secret_key == "legacy-secret"
    assert effective.base_url == "https://legacy.example"
    assert reloaded.observability.langfuse is None


def test_explicit_whole_block_never_inherits_legacy_keys_or_host():
    disabled = Config.model_validate({"observability": {"langfuse": {"enabled": False}}})
    effective = resolve_langfuse_config(disabled)
    assert not effective.enabled
    assert not effective.configured
    assert effective.secret_key == ""
    assert effective.base_url == DEFAULT_LANGFUSE_BASE_URL


def test_explicit_enabled_references_override_legacy_disable_without_mutation(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    monkeypatch.setenv("TRACE_PUBLIC", "new-public")
    monkeypatch.setenv("TRACE_SECRET", "new-secret")
    monkeypatch.setenv("TRACE_HOST", "trace.example")
    config = Config.model_validate({"observability": {"langfuse": {
        "enabled": True, "baseUrl": "https://${TRACE_HOST}",
        "publicKey": "${TRACE_PUBLIC}", "secretKey": "${TRACE_SECRET}",
    }}})
    effective = resolve_langfuse_config(config)
    assert effective.enabled and effective.configured
    assert effective.base_url == "https://trace.example"
    assert effective.secret_key == "new-secret"
    assert editable_langfuse_config(config).secret_key == "${TRACE_SECRET}"
    assert resolve_config_env_vars(config).observability.langfuse == effective
    assert "new-secret" not in repr(effective)
    assert "new-public" not in repr(effective)


def test_first_explicit_save_uses_legacy_references_not_resolved_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://preferred.example")
    config = Config()
    editable = editable_langfuse_config(config)
    assert editable.base_url == "${LANGFUSE_BASE_URL}"
    assert editable.public_key == "${LANGFUSE_PUBLIC_KEY}"
    assert editable.secret_key == "${LANGFUSE_SECRET_KEY}"
    config.observability.langfuse = editable
    path = tmp_path / "config.json"
    save_config(config, path)
    saved = path.read_text()
    assert "legacy-secret" not in saved
    assert "${LANGFUSE_SECRET_KEY}" in saved
    assert resolve_langfuse_config(load_config(path)).base_url == "https://preferred.example"


def test_legacy_disable_and_missing_optional_references(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    assert not resolve_langfuse_config(Config()).enabled
    monkeypatch.delenv("TRACE_MISSING", raising=False)
    config = Config()
    config.observability.langfuse = LangfuseConfig(enabled=True, secret_key="${TRACE_MISSING}")
    assert not resolve_langfuse_config(config).configured
    with pytest.raises(ConfigLoadError, match="missing"):
        resolve_config_env_vars(config)
