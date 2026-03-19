"""Tests that NANOBOT_* environment variables override config.json values.

Regression tests for https://github.com/HKUDS/nanobot/issues/1791 - when a
config.json file exists, pydantic-settings env var sources were bypassed because
Config.model_validate() skips BaseSettings.__init__.  The fix switches to
Config(**data) so env vars are read and settings_customise_sources puts
env_settings first (highest priority).
"""

import json

from nanobot.config.loader import load_config


def test_env_var_overrides_model_in_config_file(tmp_path, monkeypatch) -> None:
    """NANOBOT_AGENTS__DEFAULTS__MODEL overrides agents.defaults.model from file."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"model": "anthropic/claude-opus-4-5"}}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("NANOBOT_AGENTS__DEFAULTS__MODEL", "openai/gpt-4o")

    config = load_config(config_path)

    assert config.agents.defaults.model == "openai/gpt-4o"


def test_file_value_used_when_no_env_var_set(tmp_path, monkeypatch) -> None:
    """When no env var is set, the config.json value is used unchanged."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"model": "deepseek/deepseek-chat"}}}),
        encoding="utf-8",
    )

    monkeypatch.delenv("NANOBOT_AGENTS__DEFAULTS__MODEL", raising=False)

    config = load_config(config_path)

    assert config.agents.defaults.model == "deepseek/deepseek-chat"


def test_env_var_overrides_provider_api_key_in_config_file(tmp_path, monkeypatch) -> None:
    """NANOBOT_PROVIDERS__ANTHROPIC__API_KEY overrides providers.anthropic.api_key from file."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"providers": {"anthropic": {"apiKey": "key-from-file"}}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("NANOBOT_PROVIDERS__ANTHROPIC__API_KEY", "key-from-env")

    config = load_config(config_path)

    assert config.providers.anthropic.api_key == "key-from-env"


def test_file_api_key_used_when_no_env_var(tmp_path, monkeypatch) -> None:
    """When no env var is set, api_key from config.json is preserved."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"providers": {"anthropic": {"apiKey": "sk-ant-file-key"}}}),
        encoding="utf-8",
    )

    monkeypatch.delenv("NANOBOT_PROVIDERS__ANTHROPIC__API_KEY", raising=False)

    config = load_config(config_path)

    assert config.providers.anthropic.api_key == "sk-ant-file-key"


def test_env_var_works_without_config_file(tmp_path, monkeypatch) -> None:
    """NANOBOT_* env vars are honoured even when no config.json exists."""
    config_path = tmp_path / "nonexistent.json"

    monkeypatch.setenv("NANOBOT_AGENTS__DEFAULTS__MODEL", "groq/llama-3.3-70b-versatile")

    config = load_config(config_path)

    assert config.agents.defaults.model == "groq/llama-3.3-70b-versatile"


def test_multiple_env_vars_override_multiple_file_values(tmp_path, monkeypatch) -> None:
    """Multiple env vars can override multiple fields from a single config.json."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"model": "anthropic/claude-opus-4-5", "maxTokens": 4096}},
                "providers": {"openai": {"apiKey": "file-openai-key"}},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("NANOBOT_AGENTS__DEFAULTS__MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("NANOBOT_PROVIDERS__OPENAI__API_KEY", "env-openai-key")

    config = load_config(config_path)

    assert config.agents.defaults.model == "openai/gpt-4o-mini"
    assert config.providers.openai.api_key == "env-openai-key"
    # File-only value (maxTokens) is still read from the file
    assert config.agents.defaults.max_tokens == 4096
